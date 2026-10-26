"""
Xpiki Claude API Provider Integration for Antigravity Hub.
Provides support for third-party Claude API gateways (api.xpiki.com, etc.)
with models: claude-opus-5, claude-opus-4-8, claude-opus-4-7, claude-sonnet-5,
claude-sonnet-4-6, claude-haiku-4-5, claude-fable-5.
Supports 1-click configuration for OpenCode, Claude Code CLI, and Claude Desktop.
"""

import os
import sys
import json
import socket
import urllib.request
import urllib.parse
import urllib.error
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple

CONFIG_DIR = Path.home() / ".config" / "opencode"
XPIKI_CONFIG_FILE = CONFIG_DIR / "xpiki.json"
DEFAULT_BASE_URL = "https://api.xpiki.com/v1"
BALANCE_URL = "https://api.xpiki.com/key"
USER_AGENT = "AntigravityHub-Xpiki/1.0 (Windows NT 10.0; Win64; x64)"

XPIKI_MODELS = {
    "claude-opus-5": {
        "name": "Claude Opus 5",
        "limit": {"context": 200000, "output": 64000},
        "description": "Флагманская модель нового поколения Opus 5",
    },
    "claude-opus-4-8": {
        "name": "Claude Opus 4.8",
        "limit": {"context": 200000, "output": 64000},
        "description": "Улучшенная модель высокой производительности Opus 4.8",
    },
    "claude-opus-4-7": {
        "name": "Claude Opus 4.7",
        "limit": {"context": 200000, "output": 64000},
        "description": "Стабильная модель глубоких рассуждений Opus 4.7",
    },
    "claude-sonnet-5": {
        "name": "Claude Sonnet 5",
        "limit": {"context": 200000, "output": 64000},
        "description": "Новейшая быстрая кодовая модель Sonnet 5",
    },
    "claude-sonnet-4-6": {
        "name": "Claude Sonnet 4.6",
        "limit": {"context": 200000, "output": 64000},
        "description": "Сбалансированная модель кодинга Sonnet 4.6",
    },
    "claude-haiku-4-5": {
        "name": "Claude Haiku 4.5",
        "limit": {"context": 200000, "output": 8192},
        "description": "Молниеносная компактная модель Haiku 4.5",
    },
    "claude-fable-5": {
        "name": "Claude Fable 5",
        "limit": {"context": 200000, "output": 64000},
        "description": "Специализированная модель Fable 5",
    },
}


def get_active_proxy() -> Optional[str]:
    """Returns proxy to use (VLESS DEFAULT_HTTP_PORT if running, or user proxy)."""
    try:
        from vless_manager import DEFAULT_HTTP_PORT
        with socket.create_connection(("127.0.0.1", DEFAULT_HTTP_PORT), timeout=0.2):
            return f"http://127.0.0.1:{DEFAULT_HTTP_PORT}"
    except Exception:
        pass

    try:
        cfg_file = CONFIG_DIR / "antigravity.json"
        if cfg_file.exists():
            cfg = json.loads(cfg_file.read_text(encoding="utf-8"))
            if cfg.get("vless_enabled") and cfg.get("vless_url"):
                from vless_manager import DEFAULT_HTTP_PORT
                return f"http://127.0.0.1:{DEFAULT_HTTP_PORT}"
            user_proxy = cfg.get("proxy")
            if user_proxy and user_proxy != "http://127.0.0.1:51180":
                return user_proxy
    except Exception:
        pass
    return None


def get_http_opener(timeout: int = 15) -> urllib.request.OpenerDirector:
    proxy = get_active_proxy()
    if proxy:
        return urllib.request.build_opener(urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
    return urllib.request.build_opener(urllib.request.ProxyHandler({}))


def load_xpiki_config() -> Dict[str, Any]:
    if not XPIKI_CONFIG_FILE.exists():
        return {
            "api_key": "",
            "base_url": DEFAULT_BASE_URL,
            "enabled_models": list(XPIKI_MODELS.keys()),
            "connected": False,
        }
    try:
        return json.loads(XPIKI_CONFIG_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {
            "api_key": "",
            "base_url": DEFAULT_BASE_URL,
            "enabled_models": list(XPIKI_MODELS.keys()),
            "connected": False,
        }


def save_xpiki_config(data: Dict[str, Any]) -> bool:
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        XPIKI_CONFIG_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        return True
    except Exception as e:
        print(f"[Xpiki] Failed to save config: {e}")
        return False


def test_xpiki_connection(api_key: str, base_url: str = DEFAULT_BASE_URL, timeout: int = 12) -> Tuple[bool, str, Dict[str, Any]]:
    """Tests connection to the Claude API gateway using Anthropic protocol."""
    api_key = api_key.strip()
    base_url = (base_url or DEFAULT_BASE_URL).strip().rstrip("/")
    if not api_key:
        return False, "Укажите API-ключ Claude (sk-...)", {}

    opener = get_http_opener(timeout=timeout)
    headers = {
        "User-Agent": USER_AGENT,
        "x-api-key": api_key,
        "Authorization": f"Bearer {api_key}",
        "anthropic-version": "2023-06-01",
        "Content-Type": "application/json",
    }

    # 1. Try /models first
    try:
        req = urllib.request.Request(f"{base_url}/models", headers=headers)
        with opener.open(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return True, "Подключение успешно установлено (каталог моделей доступен)!", data
    except Exception:
        pass

    # 2. Try lightweight ping to /messages
    try:
        probe = {
            "model": "claude-haiku-4-5",
            "max_tokens": 5,
            "messages": [{"role": "user", "content": "ping"}],
        }
        req = urllib.request.Request(
            f"{base_url}/messages",
            data=json.dumps(probe).encode("utf-8"),
            headers=headers
        )
        with opener.open(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return True, "Подключение успешно установлено (сообщения обрабатываются)!", data
    except urllib.error.HTTPError as e:
        if e.code == 401:
            return False, f"Ошибка 401: Неверный API-ключ для {base_url}.", {}
        if e.code == 403:
            return False, f"Ошибка 403: Доступ запрещен (проверьте VPN и баланс токенов).", {}
        return False, f"Сервер вернул HTTP {e.code}: {e.reason}", {}
    except Exception as e:
        return False, f"Не удалось подключиться к {base_url}: {e}", {}


def configure_opencode(api_key: str, base_url: str = DEFAULT_BASE_URL, enabled_models: Optional[List[str]] = None) -> bool:
    """Configures the xpiki provider in ~/.config/opencode/opencode.json."""
    cfg_path = CONFIG_DIR / "opencode.json"
    api_key = api_key.strip()
    base_url = (base_url or DEFAULT_BASE_URL).strip().rstrip("/")
    if enabled_models is None:
        enabled_models = list(XPIKI_MODELS.keys())

    try:
        cfg_data: Dict[str, Any] = {}
        if cfg_path.exists():
            cfg_data = json.loads(cfg_path.read_text(encoding="utf-8"))

        if "provider" not in cfg_data:
            cfg_data["provider"] = {}

        if api_key:
            models_dict = {}
            for mid in enabled_models:
                info = XPIKI_MODELS.get(mid, {"name": mid, "limit": {"context": 200000, "output": 64000}})
                models_dict[mid] = {
                    "name": info["name"],
                    "limit": info.get("limit", {"context": 200000, "output": 64000}),
                }

            cfg_data["provider"]["xpiki"] = {
                "npm": "@ai-sdk/anthropic",
                "name": "Claude API (Xpiki)",
                "options": {
                    "baseURL": base_url,
                    "apiKey": api_key,
                },
                "models": models_dict,
            }
        else:
            cfg_data["provider"].pop("xpiki", None)

        cfg_path.write_text(json.dumps(cfg_data, indent=4, ensure_ascii=False), encoding="utf-8")
        try:
            import opencode_config
            opencode_config.ensure_session_title_config(cfg_path)
        except Exception:
            pass
        return True
    except Exception as e:
        print(f"[Xpiki] Failed to configure opencode.json: {e}")
        return False


def disconnect_xpiki() -> bool:
    """Removes Xpiki from OpenCode provider configuration."""
    cfg = load_xpiki_config()
    cfg["connected"] = False
    save_xpiki_config(cfg)
    return configure_opencode("")


def fetch_xpiki_quota(api_key: str, base_url: str = DEFAULT_BASE_URL, timeout: int = 12) -> Dict[str, Any]:
    """Fetch the key quota from Xpiki's public key-status API.

    The web client uses POST /api/public/key-status with only a bearer token.
    A failed request must not be presented as a real 100M quota: the account's
    actual limit is returned by the server and can differ per key/tariff.
    """
    api_key = api_key.strip()
    base_url = (base_url or DEFAULT_BASE_URL).strip().rstrip("/")
    empty = {
        "status": "no_key" if not api_key else "error",
        "quota_limit": None,
        "quota_used": None,
        "remaining_tokens": None,
        "remaining_percent": None,
        "effective_rpm": None,
        "effective_tpm": None,
        "expires_at": "",
    }
    if not api_key:
        return empty

    opener = get_http_opener(timeout=timeout)
    parsed = urllib.parse.urlparse(base_url)
    origin = f"{parsed.scheme or 'https'}://{parsed.netloc or 'api.xpiki.com'}"
    endpoint = f"{origin}/api/public/key-status"
    headers = {
        "User-Agent": USER_AGENT,
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
    }

    try:
        # Match the request made by https://api.xpiki.com/key.  In particular,
        # it is a body-less POST, not the old JSON {} request.
        req = urllib.request.Request(endpoint, method="POST", headers=headers)
        with opener.open(req, timeout=timeout) as resp:
            raw = json.loads(resp.read().decode("utf-8"))
        if not isinstance(raw, dict) or raw.get("code") != 0 or not isinstance(raw.get("data"), dict):
            raise ValueError(raw.get("message", "Некорректный ответ Xpiki") if isinstance(raw, dict) else "Некорректный ответ Xpiki")

        d = raw["data"]
        total = int(d["quota_limit"] or 0)
        used = int(d.get("quota_used") or 0)
        remaining = max(0, total - used)
        quota_info = {
            "status": "ok",
            "quota_limit": total,
            "quota_used": used,
            "remaining_tokens": remaining,
            "remaining_percent": round((remaining / total) * 100, 1) if total > 0 else 0.0,
            "effective_rpm": int(d["effective_rpm"]) if d.get("effective_rpm") is not None else None,
            "effective_tpm": int(d["effective_tpm"]) if d.get("effective_tpm") is not None else None,
            "expires_at": d.get("expires_at") or "",
        }
        cfg = load_xpiki_config()
        cfg["cached_quota"] = quota_info
        save_xpiki_config(cfg)
        return quota_info
    except urllib.error.HTTPError as e:
        detail = f"HTTP {e.code}"
        try:
            body = e.read().decode("utf-8")
            payload = json.loads(body)
            if isinstance(payload, dict) and payload.get("message"):
                detail = f"HTTP {e.code}: {payload['message']}"
        except Exception:
            pass
        print(f"[Xpiki] Key status check error: {detail}")
        empty["error"] = detail
    except Exception as e:
        print(f"[Xpiki] Key status check error: {e}")
        empty["error"] = str(e)

    cfg = load_xpiki_config()
    cached = cfg.get("cached_quota")
    if isinstance(cached, dict) and cached.get("status") == "ok":
        stale = dict(cached)
        stale["status"] = "stale"
        stale["error"] = empty.get("error", "Не удалось обновить квоту")
        return stale
    return empty


def refresh_xpiki_quota_silent() -> Dict[str, Any]:
    """Called silently by Hub background refresh timer to update Xpiki quotas in real time."""
    cfg = load_xpiki_config()
    key = cfg.get("api_key", "").strip()
    url = cfg.get("base_url") or DEFAULT_BASE_URL
    if key and cfg.get("connected"):
        return fetch_xpiki_quota(key, url)
    return cfg.get("cached_quota") or {}
