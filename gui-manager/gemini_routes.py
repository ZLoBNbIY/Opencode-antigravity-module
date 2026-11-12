"""Daily-updated Gemini domain rules used by the Hub's provider dispatcher."""

from __future__ import annotations

import json
import threading
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

try:
    import hub_paths
    CONFIG_DIR = hub_paths.CONFIG_DIR
    CACHE_PATH = hub_paths.GEMINI_DOMAINS_FILE
except Exception:
    CONFIG_DIR = Path.home() / ".config" / "opencode"
    CACHE_PATH = CONFIG_DIR / "gemini_domains.json"
REFRESH_SECONDS = 24 * 60 * 60
SOURCES = (
    "https://raw.githubusercontent.com/v2fly/domain-list-community/master/data/google-gemini",
    "https://raw.githubusercontent.com/v2fly/domain-list-community/master/data/google-deepmind",
    "https://raw.githubusercontent.com/itdoginfo/allow-domains/main/Services/google_ai.lst",
)
_lock = threading.Lock()
_domains: set[str] = set()
_exact: set[str] = set()
_rule_sources: dict[tuple[str, str], set[str]] = {}
_loaded = False
_refreshing = False
_last_refresh = 0.0
_last_error: str | None = None
_source_count = 0
_last_attempt = 0.0


def _parse(text: str) -> tuple[set[str], set[str]]:
    domains, exact = set(), set()
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip().lower().rstrip(".")
        if not line or line.startswith(("include:", "!")):
            continue
        if line.startswith("full:"):
            line = line[5:]
            exact.add(line)
        elif line.startswith(("domain:", "domain=")):
            line = line.split(":", 1)[-1] if line.startswith("domain:") else line.split("=", 1)[-1]
            domains.add(line)
        else:
            domains.add(line)
    return domains, exact


def _load_cache() -> None:
    global _domains, _exact, _rule_sources, _last_refresh, _loaded, _source_count
    try:
        data = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        _domains = set(data.get("domains", []))
        _exact = set(data.get("exact", []))
        _rule_sources = {}
        for rule in data.get("rules", []):
            if isinstance(rule, dict) and rule.get("domain"):
                key = (str(rule["domain"]), str(rule.get("match", "suffix")))
                _rule_sources[key] = set(rule.get("sources", []))
        if not _rule_sources:
            _rule_sources = {(domain, "suffix"): {"Источник не сохранён"} for domain in _domains}
            _rule_sources.update({(domain, "exact"): {"Источник не сохранён"} for domain in _exact})
        _last_refresh = float(data.get("updated", 0))
        _source_count = int(data.get("sources", 0))
    except (OSError, ValueError, TypeError):
        pass
    _loaded = True


def _refresh() -> None:
    global _domains, _exact, _rule_sources, _last_refresh, _refreshing, _last_error, _source_count
    try:
        domains, exact = set(), set()
        rule_sources: dict[tuple[str, str], set[str]] = {}
        loaded_sources = 0
        for url in SOURCES:
            request = urllib.request.Request(url, headers={"User-Agent": "AntigravityHub-Gemini-Rules"})
            with urllib.request.urlopen(request, timeout=15) as response:
                text = response.read().decode("utf-8-sig")
            parsed_domains, parsed_exact = _parse(text)
            domains.update(parsed_domains)
            exact.update(parsed_exact)
            for domain in parsed_domains:
                rule_sources.setdefault((domain, "suffix"), set()).add(url)
            for domain in parsed_exact:
                rule_sources.setdefault((domain, "exact"), set()).add(url)
            loaded_sources += 1
        if not domains and not exact:
            return
        updated = time.time()
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        rules = [{"domain": domain, "match": match, "sources": sorted(sources)}
                 for (domain, match), sources in sorted(rule_sources.items())]
        CACHE_PATH.write_text(json.dumps({"domains": sorted(domains), "exact": sorted(exact),
                                          "rules": rules, "updated": updated,
                                          "sources": loaded_sources}), encoding="utf-8")
        with _lock:
            _domains, _exact, _rule_sources, _last_refresh = domains, exact, rule_sources, updated
            _source_count, _last_error = loaded_sources, None
    except Exception as error:
        # Keep the last known-good cache if any upstream is unavailable.
        with _lock:
            _last_error = type(error).__name__
    finally:
        with _lock:
            _refreshing = False


def refresh_async(force: bool = False) -> None:
    global _loaded, _refreshing, _last_attempt
    with _lock:
        if not _loaded:
            _load_cache()
        if _refreshing or (not force and time.time() - _last_refresh < REFRESH_SECONDS):
            return
        if not force and _last_error and time.time() - _last_attempt < 15 * 60:
            return
        _refreshing = True
        _last_attempt = time.time()
    threading.Thread(target=_refresh, daemon=True, name="gemini-rules-update").start()


def get_status() -> dict:
    """Return cache freshness and updater health, and schedule a due refresh."""
    refresh_async()
    with _lock:
        count = len(_rule_sources) or len(_domains | _exact)
        if _refreshing:
            state = "updating"
        elif _last_error:
            state = "error"
        elif _last_refresh:
            state = "updated"
        else:
            state = "waiting"
        return {
            "state": state,
            "updated_at": datetime.fromtimestamp(_last_refresh, timezone.utc).isoformat()
                if _last_refresh else None,
            "domain_count": count,
            "sources_loaded": _source_count,
            "sources_total": len(SOURCES),
            "last_error": _last_error,
            "update_available": bool(count and _source_count == len(SOURCES) and not _last_error),
        }


def get_rules(query: str = "", limit: int = 1000) -> list[dict]:
    """Return cached rules with match semantics and source attribution."""
    refresh_async()
    needle = query.strip().lower()
    with _lock:
        rules = [
            {"domain": domain, "match": match, "sources": sorted(sources)}
            for (domain, match), sources in _rule_sources.items()
            if not needle or needle in domain or any(needle in source.lower() for source in sources)
        ]
    rules.sort(key=lambda item: (item["domain"], item["match"]))
    return rules[:max(1, min(int(limit), 5000))]


def matches(host: str) -> bool:
    host = host.strip().lower().rstrip(".")
    refresh_async()
    with _lock:
        if host in _exact:
            return True
        return any(host == domain or host.endswith("." + domain) for domain in _domains)
