"""Real DeepSeek token and money usage from the local OpenCode database.

The DeepSeek Platform API exposes only the prepaid balance, not per-key usage.
OpenCode already records every assistant message with its provider, model and
billed tokens, so the Hub charts those local records instead of inventing
numbers and prices them with DeepSeek's official tariff in the currency of the
platform balance (CNY or USD). Only the paid ``deepseek`` provider is counted
(the free DeepSeek models served by ``providerID: opencode`` are a different
product).
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

DB_PATH = Path(os.path.expanduser("~/.local/share/opencode/opencode.db"))
PROVIDER = "deepseek"
SOURCE = "OpenCode"
CACHE_TTL_SECONDS = 60
_MODEL_LIKE = ('%"providerID":"deepseek"%', '%"providerID": "deepseek"%')
DEFAULT_CURRENCY = "CNY"

# Official DeepSeek prices per 1M tokens: (cache hit input, cache miss input,
# output). Reasoning tokens are billed at the output rate. Peak hours cost 2x.
# https://api-docs.deepseek.com/quick_start/pricing
FLASH = "deepseek-flash"
PRO = "deepseek-v4-pro"
PRICES: Dict[str, Dict[str, Tuple[float, float, float]]] = {
    FLASH: {"CNY": (0.02, 1.0, 4.0), "USD": (0.003, 0.15, 0.6)},
    PRO: {"CNY": (0.15, 4.5, 13.5), "USD": (0.022, 0.66, 1.98)},
}
MODEL_ALIASES = {
    "deepseek-flash": FLASH,
    "deepseek-v4-flash": FLASH,
    "deepseek-v4-flash-vision-exp": FLASH,
    "deepseek-v4.1-flash": FLASH,
    "deepseek-v4.1-flash-1017": FLASH,
    "deepseek-v4-pro": PRO,
    "deepseek-v4-pro-0813": PRO,
}
PEAK_MULTIPLIER = 2.0

_cache: Dict[Tuple[int, str], Tuple[float, Dict[str, Any]]] = {}


def _empty_day(day: str) -> Dict[str, Any]:
    return {
        "date": day,
        "cost": 0.0,
        "cost_usd": 0.0,
        "tokens_input": 0,
        "tokens_output": 0,
        "tokens_reasoning": 0,
        "tokens_cache_read": 0,
        "tokens_total": 0,
        "messages": 0,
        "unpriced_messages": 0,
    }


def _series(days: int, today: date) -> Dict[str, Dict[str, Any]]:
    first = today - timedelta(days=days - 1)
    buckets = {}
    for offset in range(days):
        day = (first + timedelta(days=offset)).isoformat()
        buckets[day] = _empty_day(day)
    return buckets


def _table_exists(con: sqlite3.Connection, name: str) -> bool:
    return con.execute(
        "select 1 from sqlite_master where type = 'table' and name = ?", (name,)
    ).fetchone() is not None


def _int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _float(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _model_id(raw: Any) -> str:
    try:
        payload = json.loads(raw) if isinstance(raw, str) else raw
    except (TypeError, ValueError):
        return ""
    if not isinstance(payload, dict):
        return ""
    return str(payload.get("id") or "").strip().lower()


def _sessions(con: sqlite3.Connection) -> Dict[str, Dict[str, Any]]:
    """DeepSeek sessions with their cumulative cost/tokens as a fallback."""
    sessions: Dict[str, Dict[str, Any]] = {}
    for table in ("session_v2", "session"):
        if not _table_exists(con, table):
            continue
        where = " or ".join("model like ?" for _ in _MODEL_LIKE)
        try:
            rows = con.execute(
                f'select id, model, cost, tokens_input, tokens_output, tokens_reasoning, '
                f'tokens_cache_read, time_created, time_updated from "{table}" where {where}',
                _MODEL_LIKE,
            ).fetchall()
        except sqlite3.Error:
            continue
        for row in rows:
            session_id = row[0]
            if not session_id or session_id in sessions:
                continue
            sessions[session_id] = {
                "model": _model_id(row[1]),
                "cost": _float(row[2]),
                "tokens_input": _int(row[3]),
                "tokens_output": _int(row[4]),
                "tokens_reasoning": _int(row[5]),
                "tokens_cache_read": _int(row[6]),
                "at": _int(row[8] or row[7]),
            }
    return sessions


def _messages(con: sqlite3.Connection, session_ids: List[str]) -> List[Tuple[Any, Any, Any]]:
    if not session_ids or not _table_exists(con, "session_message"):
        return []
    rows: List[Tuple[Any, Any, Any]] = []
    for start in range(0, len(session_ids), 400):
        chunk = session_ids[start:start + 400]
        marks = ",".join("?" * len(chunk))
        try:
            rows.extend(con.execute(
                f"select session_id, time_created, data from session_message "
                f"where type = 'assistant' and session_id in ({marks})",
                chunk,
            ).fetchall())
        except sqlite3.Error:
            return rows
    return rows


def is_peak(ts_ms: Any) -> bool:
    """Peak hours: 01:00-04:00 and 06:00-10:00 UTC, Monday through Friday.

    Chinese public holidays are not modelled; they are billed as off-peak.
    """
    ts = _int(ts_ms)
    if not ts:
        return False
    moment = datetime.fromtimestamp(ts / 1000, tz=timezone.utc)
    if moment.weekday() >= 5:
        return False
    return 1 <= moment.hour < 4 or 6 <= moment.hour < 10


def _token_cost(model_id: str, tokens: Any, currency: str, peak: bool) -> Optional[float]:
    canonical = MODEL_ALIASES.get(str(model_id or "").strip().lower())
    price = PRICES.get(canonical or "", {}).get(currency)
    if price is None:
        return None
    payload = tokens if isinstance(tokens, dict) else {}
    cache = payload.get("cache") if isinstance(payload.get("cache"), dict) else {}
    cached = _int(cache.get("read"))
    fresh = _int(payload.get("input"))
    output = _int(payload.get("output")) + _int(payload.get("reasoning"))
    cost = (cached * price[0] + fresh * price[1] + output * price[2]) / 1_000_000
    return cost * PEAK_MULTIPLIER if peak else cost


def _add(buckets: Dict[str, Dict[str, Any]], ts_ms: Any, model_id: str,
         usd_cost: Any, tokens: Any, currency: str, messages: int = 1,
         peak: Optional[bool] = None) -> bool:
    ts = _int(ts_ms)
    if not ts:
        return False
    day = datetime.fromtimestamp(ts / 1000).date().isoformat()
    bucket = buckets.get(day)
    if bucket is None:
        return False
    payload = tokens if isinstance(tokens, dict) else {}
    cache = payload.get("cache") if isinstance(payload.get("cache"), dict) else {}
    fresh = _int(payload.get("input"))
    output = _int(payload.get("output"))
    reasoning = _int(payload.get("reasoning"))
    cached = _int(cache.get("read"))
    bucket["cost_usd"] += _float(usd_cost)
    bucket["tokens_input"] += fresh
    bucket["tokens_output"] += output
    bucket["tokens_reasoning"] += reasoning
    bucket["tokens_cache_read"] += cached
    bucket["tokens_total"] += fresh + output + reasoning + cached
    bucket["messages"] += max(0, messages)
    local_cost = _token_cost(model_id, payload, currency,
                             is_peak(ts) if peak is None else peak)
    if local_cost is None:
        bucket["unpriced_messages"] += max(0, messages)
    else:
        bucket["cost"] += local_cost
    return True


def deepseek_usage(days: int = 30, now: Optional[datetime] = None,
                   currency: str = DEFAULT_CURRENCY) -> Dict[str, Any]:
    """Aggregate DeepSeek cost/tokens per local day from OpenCode's database."""
    try:
        days = max(1, min(int(days), 90))
    except (TypeError, ValueError):
        days = 30
    currency = str(currency or DEFAULT_CURRENCY).upper()
    if currency not in PRICES[FLASH]:
        currency = DEFAULT_CURRENCY

    cached = _cache.get((days, currency))
    if cached and time.time() - cached[0] < CACHE_TTL_SECONDS:
        return dict(cached[1])

    current = now or datetime.now()
    buckets = _series(days, current.date())
    result: Dict[str, Any] = {
        "status": "ok",
        "source": SOURCE,
        "provider": PROVIDER,
        "currency": currency,
        "pricing": "DeepSeek official tariff",
        "peak_multiplier": PEAK_MULTIPLIER,
        "window_days": days,
        "days": list(buckets.values()),
        "totals": {"cost": 0.0, "cost_usd": 0.0, "tokens_total": 0,
                   "messages": 0, "unpriced_messages": 0},
        "checked_at": int(time.time()),
        "error": None,
    }

    db = Path(DB_PATH)
    if not db.exists():
        result["status"] = "unavailable"
        result["error"] = "Локальная база OpenCode не найдена — расход пока недоступен"
        _cache[(days, currency)] = (time.time(), result)
        return dict(result)

    con = None
    try:
        con = sqlite3.connect(f"{db.as_uri()}?mode=ro", uri=True, timeout=2)
        sessions = _sessions(con)
        seen = set()
        for session_id, created, data in _messages(con, sorted(sessions)):
            try:
                payload = json.loads(data)
            except (TypeError, ValueError):
                continue
            if not isinstance(payload, dict):
                continue
            model = payload.get("model")
            if not isinstance(model, dict) or model.get("providerID") != PROVIDER:
                continue
            timing = payload.get("time")
            occurred = timing.get("created") if isinstance(timing, dict) else None
            if _add(buckets, occurred or created, model.get("id"), payload.get("cost"),
                    payload.get("tokens"), currency):
                seen.add(session_id)
        # Sessions without per-message records (older OpenCode versions) still
        # carry cumulative totals; price them off-peak at the last update.
        for session_id, info in sessions.items():
            if session_id in seen:
                continue
            _add(buckets, info["at"], info["model"], info["cost"], {
                "input": info["tokens_input"],
                "output": info["tokens_output"],
                "reasoning": info["tokens_reasoning"],
                "cache": {"read": info["tokens_cache_read"]},
            }, currency, messages=0, peak=False)
    except sqlite3.Error:
        result["status"] = "error"
        result["error"] = "Не удалось прочитать базу OpenCode (файл занят или повреждён)"
        _cache[(days, currency)] = (time.time(), result)
        return dict(result)
    finally:
        if con is not None:
            try:
                con.close()
            except sqlite3.Error:
                pass

    totals = {"cost": 0.0, "cost_usd": 0.0, "tokens_total": 0,
              "messages": 0, "unpriced_messages": 0}
    for bucket in buckets.values():
        bucket["cost"] = round(bucket["cost"], 8)
        bucket["cost_usd"] = round(bucket["cost_usd"], 8)
        for key in totals:
            totals[key] += bucket[key]
    for key in ("cost", "cost_usd"):
        totals[key] = round(totals[key], 8)
    result["totals"] = totals
    _cache[(days, currency)] = (time.time(), result)
    return dict(result)
