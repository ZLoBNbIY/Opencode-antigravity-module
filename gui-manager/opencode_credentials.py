"""Read API keys that OpenCode stores for itself.

OpenCode 2.x keeps credentials in the ``credential`` table of
``opencode.db`` (``value`` is ``{"type": "key", "key": "..."}``), and some
builds/configs keep a plain key in ``opencode.json(c)`` under
``provider.<id>.options.apiKey``.  The Hub mirrors the keys it manages into
that store, so reading both sources is what makes the exchange two-way:
a key typed in OpenCode can be adopted by the Hub, and the timestamp of the
newest copy decides which side wins when they differ.
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import threading
import time
from contextlib import closing
from pathlib import Path
from typing import Optional, Sequence, Tuple

import jsonc_config

_PLACEHOLDERS = {
    "antigravity", "hub-web-placeholder", "sk-...", "your-api-key",
    "your_api_key", "changeme", "none", "null",
}
_CONFIG_FIELDS = ("apiKey", "api_key", "apikey", "token", "key")
_KEY_TYPES = ("key", "api", None)

_CACHE_TTL = 2.0
_cache: dict = {}
_cache_lock = threading.Lock()


def _clean(value) -> str:
    text = value.strip() if isinstance(value, str) else ""
    return "" if not text or text.lower() in _PLACEHOLDERS else text


def _cached(name, loader):
    now = time.monotonic()
    with _cache_lock:
        entry = _cache.get(name)
        if entry is not None and now - entry[0] < _CACHE_TTL:
            return entry[1]
    try:
        value = loader()
    except Exception:
        value = {}
    with _cache_lock:
        _cache[name] = (time.monotonic(), value)
    return value


def invalidate() -> None:
    """Forget cached credentials (call after writing to OpenCode)."""
    with _cache_lock:
        _cache.clear()


def database_path() -> Optional[Path]:
    """Locate ``opencode.db`` for the installed OpenCode build."""
    override = os.environ.get("OPENCODE_DATA_DIR")
    if override:
        candidate = Path(os.path.expanduser(override))
        db = candidate if candidate.suffix == ".db" else candidate / "opencode.db"
        db = db.resolve()
        return db if db.is_file() else None
    home = Path.home()
    candidates = []
    xdg = os.environ.get("XDG_DATA_HOME")
    if xdg:
        candidates.append(Path(xdg) / "opencode" / "opencode.db")
    # OpenCode 2.x uses an XDG layout on every platform.
    candidates.append(home / ".local" / "share" / "opencode" / "opencode.db")
    if sys.platform == "win32":
        for env in ("LOCALAPPDATA", "APPDATA"):
            base = os.environ.get(env)
            if base:
                candidates.append(Path(base) / "opencode" / "opencode.db")
    else:
        candidates.append(home / ".config" / "opencode" / "opencode.db")
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    return None


def _db_records(db: Path, integration_ids: Sequence[str]) -> dict:
    """Newest key credential per integration id: {id: (credential_id, key, ms)}."""
    ids = tuple(integration_ids)
    cache_key = ("db", str(db), ids)

    def load():
        records = {}
        marks = ",".join("?" for _ in ids)
        with closing(sqlite3.connect(f"{db.as_uri()}?mode=ro", uri=True, timeout=2)) as conn:
            rows = conn.execute(
                "SELECT id, integration_id, value, time_updated FROM credential "
                f"WHERE integration_id IN ({marks}) ORDER BY time_updated DESC",
                ids,
            ).fetchall()
        for credential_id, integration_id, raw, updated in rows or []:
            try:
                value = json.loads(raw)
            except (TypeError, ValueError):
                continue
            if not isinstance(value, dict) or value.get("type") not in _KEY_TYPES:
                continue
            key = _clean(value.get("key") or value.get("apiKey") or value.get("api_key"))
            if not key:
                continue
            try:
                timestamp = int(updated or 0)
            except (TypeError, ValueError, OverflowError):
                continue
            current = records.get(integration_id)
            if current is None or timestamp > current[2]:
                records[integration_id] = (str(credential_id or ""), key, timestamp)
        return records

    return _cached(cache_key, load)


def read_config_key(path: Optional[Path], name_hint: str, *,
                    integration_ids: Sequence[str] = ()) -> Tuple[str, int]:
    """Key stored in ``opencode.json(c)`` plus that file's modification time."""
    if not path:
        return "", 0
    path = Path(path)
    try:
        if not path.exists():
            return "", 0
        timestamp = int(path.stat().st_mtime_ns // 1_000_000)
        data = jsonc_config.parse_config(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return "", 0
    hint = str(name_hint or "").lower()
    exact_ids = {name.casefold() for name in integration_ids}
    for section in ("provider", "providers"):
        providers = data.get(section)
        if not isinstance(providers, dict):
            continue
        for name, provider in providers.items():
            name = str(name).casefold()
            if (name not in exact_ids if exact_ids else not hint or hint not in name) or not isinstance(provider, dict):
                continue
            for holder in (provider, provider.get("options"), provider.get("settings")):
                if not isinstance(holder, dict):
                    continue
                for field in _CONFIG_FIELDS:
                    key = _clean(holder.get(field))
                    if key:
                        return key, timestamp
    return "", 0


def read_key(integration_ids: Sequence[str], config_path: Optional[Path] = None,
             name_hint: str = "", *, exact_config: bool = False) -> Tuple[str, int]:
    """Newest key for the given integrations, with its freshness in ms."""
    candidates = []
    db = database_path()
    if db is not None:
        for _, key, timestamp in _db_records(db, integration_ids).values():
            candidates.append((key, timestamp))
    if config_path is not None and name_hint:
        key, timestamp = read_config_key(config_path, name_hint,
                                         integration_ids=integration_ids if exact_config else ())
        if key:
            candidates.append((key, timestamp))
    if not candidates:
        return "", 0
    return max(candidates, key=lambda item: item[1])


def has_credential(integration_id: str) -> bool:
    db = database_path()
    if db is None:
        return False
    return bool(_db_records(db, (integration_id,)).get(integration_id))


def credential_id(integration_id: str) -> str:
    """Existing key credential id, so an import updates it instead of duplicating."""
    db = database_path()
    if db is None:
        return ""
    record = _db_records(db, (integration_id,)).get(integration_id)
    return record[0] if record else ""
