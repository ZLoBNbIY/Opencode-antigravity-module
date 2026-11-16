"""DeepSeek Platform API (sk- keys) balance tracking for Antigravity Hub.

This module is intentionally separate from the legacy DeepSeek Web integration.
The paid Platform API exposes ``GET /user/balance`` which returns a prepaid
balance rather than the 5h/weekly window quotas used by Google or ChatGPT.
"""

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, Optional

import hub_paths
from secure_storage import atomic_write, protect_secret, unprotect_secret

CONFIG_FILE = hub_paths.ACCOUNTS_DIR / "deepseek-api.json"
SECRET_FILE = hub_paths.SECURE_DIR / "deepseek-api-key.json"
DEFAULT_BASE_URL = "https://api.deepseek.com"
USER_AGENT = "AntigravityHub-DeepSeek/1.0 (Windows NT 10.0; Win64; x64)"
_ENV_KEYS = ("DEEPSEEK_API_KEY", "DEEPSEEK_KEY")
_PLACEHOLDERS = {"hub-web-placeholder", "sk-...", "your-api-key", "your_api_key", "changeme", "none", "null"}


def _default_config() -> Dict[str, Any]:
    return {"base_url": DEFAULT_BASE_URL, "connected": False, "cached_balance": {}}


def load_config() -> Dict[str, Any]:
    cfg = _default_config()
    if CONFIG_FILE.exists():
        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                cfg.update({k: v for k, v in data.items() if k in cfg})
        except (OSError, ValueError, TypeError):
            pass
    if not isinstance(cfg.get("base_url"), str) or not cfg["base_url"].strip():
        cfg["base_url"] = DEFAULT_BASE_URL
    if not isinstance(cfg.get("cached_balance"), dict):
        cfg["cached_balance"] = {}
    return cfg


def save_config(cfg: Dict[str, Any]) -> bool:
    try:
        atomic_write(CONFIG_FILE, json.dumps(cfg, indent=2, ensure_ascii=False))
        return True
    except Exception as exc:
        print(f"[DeepSeek API] Failed to save config: {exc}")
        return False


def clean_key(value: Any) -> str:
    return str(value or "").strip()


def is_valid_key(value: Any) -> bool:
    key = clean_key(value)
    return len(key) >= 20 and key.lower() not in _PLACEHOLDERS


def mask_key(key: Any) -> Optional[str]:
    key = clean_key(key)
    if not key:
        return None
    if len(key) <= 8:
        return "••••"
    return f"{key[:3]}••••{key[-4:]}"


def save_api_key(key: Any) -> bool:
    key = clean_key(key)
    if not is_valid_key(key):
        raise ValueError("Укажите корректный API-ключ DeepSeek (sk-...)")
    atomic_write(SECRET_FILE, json.dumps(protect_secret("deepseek-api-key", {"apiKey": key})))
    cfg = load_config()
    cfg["connected"] = True
    save_config(cfg)
    return True


def clear_api_key() -> bool:
    try:
        SECRET_FILE.unlink(missing_ok=True)
    except OSError:
        pass
    cfg = load_config()
    cfg["connected"] = False
    cfg["cached_balance"] = {}
    save_config(cfg)
    return True


def _key_from_environment() -> str:
    for name in _ENV_KEYS:
        value = clean_key(os.environ.get(name))
        if is_valid_key(value):
            return value
    return ""


def _key_from_opencode_config() -> str:
    path = hub_paths.OPENCODE_CONFIG_FILE
    if not path.exists():
        return ""
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return ""
    for section in ("provider", "providers"):
        providers = data.get(section)
        if not isinstance(providers, dict):
            continue
        for name, provider in providers.items():
            if "deepseek" not in str(name).lower() or not isinstance(provider, dict):
                continue
            for holder in (provider, provider.get("options"), provider.get("settings")):
                if not isinstance(holder, dict):
                    continue
                for field in ("apiKey", "api_key", "apikey", "token"):
                    value = clean_key(holder.get(field))
                    if is_valid_key(value):
                        return value
    return ""


def load_api_key() -> str:
    """Return the stored key; on first run adopt it from env or OpenCode config."""
    if SECRET_FILE.exists():
        try:
            record = json.loads(SECRET_FILE.read_text(encoding="utf-8"))
            return clean_key(unprotect_secret(record, "deepseek-api-key").get("apiKey"))
        except Exception:
            return ""
    imported = _key_from_environment() or _key_from_opencode_config()
    if imported:
        try:
            save_api_key(imported)
        except Exception:
            pass
    return imported


def api_origin(base_url: Optional[str] = None) -> str:
    raw = (base_url or load_config().get("base_url") or DEFAULT_BASE_URL).strip().rstrip("/")
    parsed = urllib.parse.urlparse(raw)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Укажите корректный HTTPS URL DeepSeek API без логина и пароля")
    return f"https://{parsed.hostname}{':' + str(parsed.port) if parsed.port else ''}"


def get_http_opener(timeout: int = 12):
    """Route balance requests through the Hub dispatcher (provider route / VLESS / proxy)."""
    import provider_proxy
    proxy = provider_proxy.proxy_url_for_hub_requests()
    return urllib.request.build_opener(urllib.request.ProxyHandler({"http": proxy, "https": proxy}))


def empty_balance(status: str = "error") -> Dict[str, Any]:
    return {
        "status": status,
        "is_available": None,
        "currency": None,
        "total_balance": None,
        "granted_balance": None,
        "topped_up_balance": None,
        "balances": [],
        "checked_at": None,
        "error": None,
    }


def parse_balance_payload(payload: Any) -> Dict[str, Any]:
    """Convert GET /user/balance JSON into a stable Hub quota object."""
    if not isinstance(payload, dict):
        raise ValueError("Некорректный ответ DeepSeek")

    def amount(value: Any) -> Optional[float]:
        try:
            return round(float(value), 4)
        except (TypeError, ValueError):
            return None

    infos = payload.get("balance_infos")
    if not isinstance(infos, list) or not infos:
        raise ValueError("DeepSeek не вернул данные о балансе")

    balances = []
    for info in infos:
        if not isinstance(info, dict):
            continue
        balances.append({
            "currency": info.get("currency") or "CNY",
            "total_balance": amount(info.get("total_balance")),
            "granted_balance": amount(info.get("granted_balance")),
            "topped_up_balance": amount(info.get("topped_up_balance")),
        })
    if not balances:
        raise ValueError("DeepSeek не вернул данные о балансе")

    primary = balances[0]
    available = payload.get("is_available")
    return {
        "status": "ok",
        "is_available": bool(available) if isinstance(available, bool) else None,
        "currency": primary["currency"],
        "total_balance": primary["total_balance"],
        "granted_balance": primary["granted_balance"],
        "topped_up_balance": primary["topped_up_balance"],
        "balances": balances,
        "checked_at": int(time.time()),
        "error": None,
    }


def fetch_balance(api_key: Optional[str] = None, base_url: Optional[str] = None,
                  timeout: int = 12) -> Dict[str, Any]:
    """Fetch DeepSeek balance; on failure keep the last known values as stale."""
    key = clean_key(api_key) or load_api_key()
    if not key:
        result = empty_balance("no_key")
        result["error"] = "Сначала сохраните API-ключ DeepSeek"
        return result

    try:
        endpoint = f"{api_origin(base_url)}/user/balance"
    except ValueError as exc:
        result = empty_balance("error")
        result["error"] = str(exc)
        return result

    req = urllib.request.Request(endpoint, headers={
        "Authorization": f"Bearer {key}",
        "Accept": "application/json",
        "User-Agent": USER_AGENT,
    }, method="GET")

    error = None
    try:
        opener = get_http_opener(timeout=timeout)
        with opener.open(req, timeout=timeout) as resp:
            result = parse_balance_payload(json.loads(resp.read().decode("utf-8")))
        cfg = load_config()
        cfg["cached_balance"] = result
        cfg["connected"] = True
        save_config(cfg)
        return result
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            error = "API-ключ DeepSeek недействителен (401)"
        elif exc.code == 403:
            error = "DeepSeek отказал в доступе к балансу (403)"
        elif exc.code == 429:
            error = "DeepSeek вернул 429 — слишком много запросов к балансу"
        else:
            error = f"Ошибка DeepSeek: HTTP {exc.code}"
    except Exception as exc:
        error = f"Ошибка сети DeepSeek: {str(exc)[:120]}"

    cfg = load_config()
    cached = cfg.get("cached_balance")
    if isinstance(cached, dict) and cached.get("status") in ("ok", "stale"):
        stale = dict(cached)
        stale["status"] = "stale"
        stale["error"] = error
        return stale
    result = empty_balance("error")
    result["error"] = error
    return result


def cached_balance() -> Dict[str, Any]:
    cached = load_config().get("cached_balance")
    if isinstance(cached, dict) and cached:
        return cached
    return empty_balance("no_key" if not load_api_key() else "error")


def refresh_balance_silent() -> Dict[str, Any]:
    """Background refresh entry point; safe to call without a configured key."""
    if not load_api_key():
        return cached_balance()
    return fetch_balance()


def provider_state() -> Dict[str, Any]:
    """Non-secret state for the web frontend."""
    cfg = load_config()
    key = load_api_key()
    balance = cached_balance()
    return {
        "connected": bool(key and cfg.get("connected")),
        "hasKey": bool(key),
        "keyLabel": mask_key(key),
        "baseUrl": cfg.get("base_url") or DEFAULT_BASE_URL,
        "balance": balance,
    }
