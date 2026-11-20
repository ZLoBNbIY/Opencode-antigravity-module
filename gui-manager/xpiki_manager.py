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

import secure_storage

CONFIG_DIR = Path.home() / ".config" / "opencode"
try:
    import hub_paths
    XPIKI_CONFIG_FILE = hub_paths.XPIKI_CONFIG_FILE
except Exception:
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
    """Return the dispatcher; it applies the Xpiki provider route by host."""
    import provider_proxy
    return provider_proxy.proxy_url_for_hub_requests()


def get_http_opener(timeout: int = 15) -> urllib.request.OpenerDirector:
    proxy = get_active_proxy()
    return urllib.request.build_opener(urllib.request.ProxyHandler({"http": proxy, "https": proxy}))


def load_xpiki_config() -> Dict[str, Any]:
    default = {
        "api_key": "",
        "base_url": DEFAULT_BASE_URL,
        "enabled_models": list(XPIKI_MODELS.keys()),
        "connected": False,
    }
    if not XPIKI_CONFIG_FILE.exists():
        return default
    try:
        raw = json.loads(XPIKI_CONFIG_FILE.read_text(encoding="utf-8"))
        if isinstance(raw, dict) and "protection" in raw and "payload" in raw:
            data = secure_storage.unprotect_payload(raw, "xpiki-config")
            return data if isinstance(data, dict) else default
        if isinstance(raw, dict):
            if raw.get("api_key"):
                # Upgrade old Hub-owned plaintext records without touching OpenCode.
                save_xpiki_config(raw)
            return raw
        return default
    except Exception:
        return default


def save_xpiki_config(data: Dict[str, Any]) -> bool:
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        record = secure_storage.protect_payload("xpiki-config", data)
        secure_storage.atomic_write(
            XPIKI_CONFIG_FILE,
            json.dumps(record, indent=2, ensure_ascii=False),
        )
        return True
    except Exception as e:
        print(f"[Xpiki] Failed to save config: {e}")
        return False


def _validate_xpiki_base_url(base_url: str) -> str:
    clean = (base_url or DEFAULT_BASE_URL).strip().rstrip("/")
    parsed = urllib.parse.urlparse(clean)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Укажите корректный HTTPS URL Xpiki без логина и пароля")
    return clean


def test_xpiki_connection(api_key: str, base_url: str = DEFAULT_BASE_URL, timeout: int = 12) -> Tuple[bool, str, Dict[str, Any]]:
    """Tests connection to the Claude API gateway using Anthropic protocol."""
    api_key = str(api_key or "").strip()
    if not api_key or any(c in api_key for c in "\r\n\x00"):
        return False, "Укажите API-ключ Claude (sk-...)", {}
    try:
        base_url = _validate_xpiki_base_url(base_url)
    except ValueError as exc:
        return False, str(exc), {}

    opener = get_http_opener(timeout=timeout)
    headers = {
        "User-Agent": USER_AGENT,
        "x-api-key": api_key,
        "Authorization": f"Bearer {api_key}",
        "anthropic-version": "2023-06-01",
        "Content-Type": "application/json",
    }

    # 1. Try /models first; do not mask 401/403 auth errors with a paid /messages probe.
    try:
        req = urllib.request.Request(f"{base_url}/models", headers=headers)
        with opener.open(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return True, "Подключение успешно установлено (каталог моделей доступен)!", data
    except urllib.error.HTTPError as e:
        if e.code == 401:
            return False, f"Ошибка 401: Неверный API-ключ для {base_url}.", {}
        if e.code == 403:
            return False, "Ошибка 403: Доступ запрещен (проверьте VPN и баланс токенов).", {}
        if e.code not in (404, 405):
            return False, f"Сервер вернул HTTP {e.code}: {e.reason}", {}
    except Exception:
        pass

    # 2. Try lightweight ping to /messages only when /models is unsupported
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
            return False, "Ошибка 403: Доступ запрещен (проверьте VPN и баланс токенов).", {}
        return False, f"Сервер вернул HTTP {e.code}: {e.reason}", {}
    except Exception as e:
        return False, f"Не удалось подключиться к {base_url}: {e}", {}


def configure_opencode(api_key: str, base_url: str = DEFAULT_BASE_URL,
                       enabled_models: Optional[List[str]] = None, *, previous_key: str = "") -> bool:
    """Configures the xpiki provider in ~/.config/opencode/opencode.json(c)."""
    import jsonc_config
    api_key = str(api_key or "").strip()
    base_url = (base_url or DEFAULT_BASE_URL).strip().rstrip("/")
    if enabled_models is None:
        enabled_models = list(XPIKI_MODELS.keys())

    try:
        cfg_path = jsonc_config.config_path(CONFIG_DIR)
        original = cfg_path.read_text(encoding="utf-8-sig") if cfg_path.exists() else "{}\n"
        cfg_data = jsonc_config.parse_config(original)

        if api_key:
            models_dict = {}
            for mid in enabled_models:
                info = XPIKI_MODELS.get(mid, {"name": mid, "limit": {"context": 200000, "output": 64000}})
                models_dict[mid] = {
                    "name": info["name"],
                    "limit": info.get("limit", {"context": 200000, "output": 64000}),
                }

            updated = jsonc_config.set_property(original, ("provider", "xpiki"), {
                "npm": "@ai-sdk/anthropic",
                "name": "Claude API (Xpiki)",
                "options": {
                    "baseURL": base_url,
                    "apiKey": api_key,
                },
                "models": models_dict,
            })
        else:
            providers = cfg_data.get("provider", {})
            entry = providers.get("xpiki") if isinstance(providers, dict) else None
            opts = entry.get("options") if isinstance(entry, dict) else None
            owned = (previous_key and isinstance(opts, dict)
                     and entry.get("name") == "Claude API (Xpiki)"
                     and entry.get("npm") == "@ai-sdk/anthropic"
                     and opts.get("apiKey") == previous_key)
            updated = jsonc_config.remove_property(original, ("provider", "xpiki")) if owned else original

        if updated != original or not cfg_path.exists():
            secure_storage.atomic_write(cfg_path, updated)
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
    """Removes Xpiki from OpenCode provider configuration and clears stored key."""
    cfg = load_xpiki_config()
    if not configure_opencode("", previous_key=cfg.get("api_key", "")):
        return False
    cfg["connected"] = False
    cfg["api_key"] = ""
    cfg["cached_quota"] = {}
    return save_xpiki_config(cfg)


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
        def _safe_int(val, default=0):
            try:
                return int(float(val)) if val is not None else default
            except (TypeError, ValueError):
                return default
        total = _safe_int(d.get("quota_limit"), 0)
        used = _safe_int(d.get("quota_used"), 0)
        remaining = max(0, total - used)
        quota_info = {
            "status": "ok",
            "quota_limit": total,
            "quota_used": used,
            "remaining_tokens": remaining,
            "remaining_percent": round((remaining / total) * 100, 1) if total > 0 else 0.0,
            "effective_rpm": _safe_int(d.get("effective_rpm"), None),
            "effective_tpm": _safe_int(d.get("effective_tpm"), None),
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
