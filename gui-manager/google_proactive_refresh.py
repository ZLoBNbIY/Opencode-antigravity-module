"""Schedule generation-store refresh with a credential-free CLI response.

The CLI only refreshes enabled, bound rows with a live access token expiring
within 30 minutes. Missing/expired tokens stay on the existing on-demand path.
Hub keeps only row IDs, credential epochs and cooldowns in memory, never tokens.
To opt out, set ``google_proactive_refresh: false`` in Hub's JSON settings or
set ``AI_HUB_GOOGLE_PROACTIVE_REFRESH=0`` before starting Hub.
"""

import hashlib
import json
import os
import random
import re
import time
from pathlib import Path


CHECK_INTERVAL = 300
MIN_SPACING = 12
MAX_JITTER = 4
FAILURE_BACKOFF = 900
RATE_LIMIT_BACKOFF = 900
CLI_TIMEOUT = 45
_ROW_ID = re.compile(r"[a-zA-Z0-9_][a-zA-Z0-9_.-]{0,255}")
PLUGIN_PACKAGE = "@cortexkit/opencode-antigravity-auth"
SUPPORTED_PROFILES = {"3.0.0", "3.1.13"}
CLI_SHA256_3113 = "6e4b0fa37c3a9de34100c92bda18347f49f1bb071dacf10007f91d64c243b946"


def _is_valid_cli_3113(path: Path) -> bool:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest() == CLI_SHA256_3113
    except OSError:
        return False


def _cache_search_roots(cache: Path | None) -> list[Path]:
    default_npm = Path.home() / ".cache" / "opencode" / "npm"
    roots: list[Path] = []
    if cache is not None:
        roots.append(Path(cache))
        if Path(cache).name == "npm":
            roots.append(Path(cache).parent / "packages")
    if cache is None or Path(cache) == default_npm:
        bases = []
        xdg = os.environ.get("XDG_CACHE_HOME")
        if xdg and Path(xdg).is_absolute():
            bases.append(Path(xdg))
        bases.append(Path.home() / ".cache")
        for base in bases:
            for kind in ("npm", "packages"):
                roots.append(base / "opencode" / kind)
    seen: set[Path] = set()
    unique: list[Path] = []
    for root in roots:
        if root not in seen:
            seen.add(root)
            unique.append(root)
    return unique


def find_cli_3113(cache: Path | None = None):
    """Locate the 3.1.13 CLI in npm/packages caches (respecting XDG_CACHE_HOME)."""
    candidates: list[Path] = []
    seen: set[Path] = set()
    for root in _cache_search_roots(cache):
        for pkg_dir in (root / f"{PLUGIN_PACKAGE}@3.1.13", root / "packages" / f"{PLUGIN_PACKAGE}@3.1.13"):
            if not pkg_dir.is_dir():
                continue
            patterns = (
                f"*/node_modules/{PLUGIN_PACKAGE}/dist/cli.js",
                f"node_modules/{PLUGIN_PACKAGE}/dist/cli.js",
            )
            for pattern in patterns:
                for path in pkg_dir.glob(pattern):
                    if path.is_file() and path not in seen:
                        seen.add(path)
                        candidates.append(path)
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]
    verified = [path for path in candidates if _is_valid_cli_3113(path)]
    if not verified:
        return None
    return max(verified, key=lambda p: p.stat().st_mtime)


def _valid_id(value):
    return isinstance(value, str) and _ROW_ID.fullmatch(value) is not None


def _positive_integer(value):
    return type(value) is int and 0 < value < 2**53


class GoogleProactiveRefresh:
    """One worker per Hub; the CLI handles store locking and stale snapshots."""

    def __init__(self, run_cli, stop, enabled, *, monotonic=time.monotonic,
                 jitter=lambda: random.uniform(0, MAX_JITTER)):
        self._run_cli = run_cli
        self._stop = stop
        self._enabled = enabled
        self._now = monotonic
        self._jitter = jitter
        self._next_attempt = 0
        self._rate_limited_until = 0
        self._generation = None
        self._cooldowns = {}

    def _should_run(self):
        if self._stop.is_set():
            return False
        try:
            return self._enabled() is True
        except Exception:
            return False

    def _request(self, *args):
        try:
            result = self._run_cli(["refresh-due", *args], timeout=CLI_TIMEOUT)
            if result is not None and result.returncode == 0:
                payload = json.loads(result.stdout)
                if isinstance(payload, dict):
                    return payload
        except Exception:
            # Do not propagate subprocess output or exception attributes.
            pass
        return {}

    def check(self):
        if not self._should_run() or self._now() < self._rate_limited_until:
            return
        listing = self._request("--list")
        generation, accounts = listing.get("generation"), listing.get("accounts")
        if listing.get("status") != "ready" or not _valid_id(generation) or not isinstance(accounts, list):
            return
        if self._generation != generation:
            self._generation = generation
            self._cooldowns.clear()

        seen = set()
        for row in accounts:
            if not isinstance(row, dict):
                continue
            row_id, epoch, expires = row.get("id"), row.get("epoch"), row.get("expires")
            if not _valid_id(row_id) or not _positive_integer(epoch) or not _positive_integer(expires) or row_id in seen:
                continue
            seen.add(row_id)
            previous_epoch, until = self._cooldowns.get(row_id, (None, 0))
            if epoch == previous_epoch and self._now() < until:
                continue
            wait = self._next_attempt - self._now()
            if (wait > 0 and self._stop.wait(wait)) or not self._should_run():
                return
            result = self._request("--account", generation, row_id, str(epoch), str(expires))
            now = self._now()
            self._next_attempt = now + MIN_SPACING + self._jitter()
            status = result.get("status")
            if status == "rate_limited":
                delay = result.get("retryAfterSeconds")
                self._rate_limited_until = now + (
                    max(CHECK_INTERVAL, delay) if _positive_integer(delay) else RATE_LIMIT_BACKOFF)
                return  # Stop the whole batch, not just this account.
            if status == "invalid_grant":
                self._cooldowns[row_id] = (epoch, float("inf"))
            elif status in ("refreshed", "skipped"):
                self._cooldowns.pop(row_id, None)
            else:
                self._cooldowns[row_id] = (epoch, now + FAILURE_BACKOFF)

    def run(self):
        """Wait five minutes after Hub startup, then check without overlap."""
        deadline = self._now() + CHECK_INTERVAL
        while not self._stop.wait(max(0, deadline - self._now())):
            deadline = self._now() + CHECK_INTERVAL
            self.check()
