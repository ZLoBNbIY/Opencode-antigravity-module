"""Real DeepSeek token and money usage from the local OpenCode database.

The DeepSeek Platform API exposes only the prepaid balance, not per-key usage.
OpenCode already records every assistant message with its provider, billed
tokens and cost, so the Hub charts those local records instead of inventing
numbers. Only the paid ``deepseek`` provider is counted (the free DeepSeek
models served by ``providerID: opencode`` are a different product).
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

DB_PATH = Path(os.path.expanduser("~/.local/share/opencode/opencode.db"))
PROVIDER = "deepseek"
SOURCE = "OpenCode"
CURRENCY = "USD"
CACHE_TTL_SECONDS = 60
_MODEL_LIKE = ('%"providerID":"deepseek"%', '%"providerID": "deepseek"%')

_cache: Dict[int, Tuple[float, Dict[str, Any]]] = {}


def _empty_day(day: str) -> Dict[str, Any]:
    return {
        "date": day,
        "cost": 0.0,
        "tokens_input": 0,
        "tokens_output": 0,
        "tokens_reasoning": 0,
        "tokens_cache_read": 0,
        "tokens_total": 0,
        "messages": 0,
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


def _sessions(con: sqlite3.Connection) -> Dict[str, Dict[str, Any]]:
    """DeepSeek sessions with their cumulative cost/tokens as a fallback."""
    sessions: Dict[str, Dict[str, Any]] = {}
    for table in ("session_v2", "session"):
        if not _table_exists(con, table):
            continue
        where = " or ".join("model like ?" for _ in _MODEL_LIKE)
        try:
            rows = con.execute(
                f'select id, cost, tokens_input, tokens_output, tokens_reasoning, '
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
                "cost": _float(row[1]),
                "tokens_input": _int(row[2]),
                "tokens_output": _int(row[3]),
                "tokens_reasoning": _int(row[4]),
                "tokens_cache_read": _int(row[5]),
                "at": _int(row[7] or row[6]),
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


def _add(buckets: Dict[str, Dict[str, Any]], ts_ms: Any, cost: Any,
         tokens: Any, messages: int = 1) -> bool:
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
    bucket["cost"] += _float(cost)
    bucket["tokens_input"] += fresh
    bucket["tokens_output"] += output
    bucket["tokens_reasoning"] += reasoning
    bucket["tokens_cache_read"] += cached
    bucket["tokens_total"] += fresh + output + reasoning + cached
    bucket["messages"] += max(0, messages)
    return True


def deepseek_usage(days: int = 30, now: Optional[datetime] = None) -> Dict[str, Any]:
    """Aggregate DeepSeek cost/tokens per local day from OpenCode's database."""
    try:
        days = max(1, min(int(days), 90))
    except (TypeError, ValueError):
        days = 30

    cached = _cache.get(days)
    if cached and time.time() - cached[0] < CACHE_TTL_SECONDS:
        return dict(cached[1])

    current = now or datetime.now()
    buckets = _series(days, current.date())
    result: Dict[str, Any] = {
        "status": "ok",
        "source": SOURCE,
        "provider": PROVIDER,
        "currency": CURRENCY,
        "window_days": days,
        "days": list(buckets.values()),
        "totals": {"cost": 0.0, "tokens_total": 0, "messages": 0},
        "checked_at": int(time.time()),
        "error": None,
    }

    db = Path(DB_PATH)
    if not db.exists():
        result["status"] = "unavailable"
        result["error"] = "Локальная база OpenCode не найдена — расход пока недоступен"
        _cache[days] = (time.time(), result)
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
            if _add(buckets, occurred or created, payload.get("cost"), payload.get("tokens")):
                seen.add(session_id)
        # Sessions without per-message records (older OpenCode versions) still
        # carry cumulative totals; attribute them to the last update.
        for session_id, info in sessions.items():
            if session_id in seen:
                continue
            _add(buckets, info["at"], info["cost"], {
                "input": info["tokens_input"],
                "output": info["tokens_output"],
                "reasoning": info["tokens_reasoning"],
                "cache": {"read": info["tokens_cache_read"]},
            }, messages=0)
    except sqlite3.Error:
        result["status"] = "error"
        result["error"] = "Не удалось прочитать базу OpenCode (файл занят или повреждён)"
        _cache[days] = (time.time(), result)
        return dict(result)
    finally:
        if con is not None:
            try:
                con.close()
            except sqlite3.Error:
                pass

    totals = {"cost": 0.0, "tokens_total": 0, "messages": 0}
    for bucket in buckets.values():
        bucket["cost"] = round(bucket["cost"], 6)
        totals["cost"] += bucket["cost"]
        totals["tokens_total"] += bucket["tokens_total"]
        totals["messages"] += bucket["messages"]
    totals["cost"] = round(totals["cost"], 6)
    result["totals"] = totals
    _cache[days] = (time.time(), result)
    return dict(result)
