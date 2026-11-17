"""DeepSeek Platform API (sk- keys) balance tracking for Antigravity Hub.

This module is intentionally separate from the legacy DeepSeek Web integration.
The paid Platform API exposes ``GET /user/balance`` which returns a prepaid
balance rather than the 5h/weekly window quotas used by Google or ChatGPT.
"""

import json
import os
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request
from contextlib import closing
from pathlib import Path
from typing import Any, Dict, List, Optional

import hub_paths
import jsonc_config
import openai_manager
from secure_storage import atomic_write, protect_secret, unprotect_secret

CONFIG_FILE = hub_paths.ACCOUNTS_DIR / "deepseek-api.json"
SECRET_FILE = hub_paths.SECURE_DIR / "deepseek-api-key.json"
DEFAULT_BASE_URL = "https://api.deepseek.com"
USER_AGENT = "AntigravityHub-DeepSeek/1.0 (Windows NT 10.0; Win64; x64)"
_ENV_KEYS = ("DEEPSEEK_API_KEY", "DEEPSEEK_KEY")
_PLACEHOLDERS = {"hub-web-placeholder", "sk-...", "your-api-key", "your_api_key", "changeme", "none", "null"}
_auto_import_pending = False

# OpenCode provider descriptor written for the DeepSeek Platform API.
PROVIDER_ID = "deepseek-account"
PROVIDER_NAME = "DeepSeek API"
_OPENCODE_INTEGRATIONS = ("deepseek", "deepseek-account")
MODEL_LIMITS = {
    "deepseek-chat": {"context": 65536, "output": 8192},
    "deepseek-reasoner": {"context": 65536, "output": 8192},
}
FALLBACK_MODELS: List[Dict[str, Any]] = [
    {"id": "deepseek-chat", "name": "DeepSeek Chat", "context": 65536, "output": 8192},
    {"id": "deepseek-reasoner", "name": "DeepSeek Reasoner", "context": 65536, "output": 8192},
]


def _default_config() -> Dict[str, Any]:
    return {"base_url": DEFAULT_BASE_URL, "connected": False, "cached_balance": {},
            "auto_import_disabled": False, "models": [], "selected_models": []}


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
    if not isinstance(cfg.get("models"), list):
        cfg["models"] = []
    if not isinstance(cfg.get("selected_models"), list):
        cfg["selected_models"] = []
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
    # An explicit key always re-enables adoption from OpenCode/env on next start.
    cfg["auto_import_disabled"] = False
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
    cfg["auto_import_disabled"] = True
    save_config(cfg)
    return True


def _key_from_environment() -> str:
    for name in _ENV_KEYS:
        value = clean_key(os.environ.get(name))
        if is_valid_key(value):
            return value
    return ""


def _key_from_opencode_db() -> str:
    """OpenCode stores API-key credentials in its SQLite credential table."""
    db = Path(os.path.expanduser("~/.local/share/opencode/opencode.db"))
    if not db.exists():
        return ""
    try:
        with closing(sqlite3.connect(f"{db.as_uri()}?mode=ro", uri=True, timeout=2)) as conn:
            marks = ",".join("?" * len(_OPENCODE_INTEGRATIONS))
            row = conn.execute(
                f"SELECT value FROM credential WHERE integration_id IN ({marks}) "
                "ORDER BY time_updated DESC LIMIT 1",
                _OPENCODE_INTEGRATIONS,
            ).fetchone()
        if not row:
            return ""
        value = json.loads(row[0])
        if not isinstance(value, dict) or value.get("type") not in ("key", "api", None):
            return ""
        candidate = clean_key(value.get("key") or value.get("apiKey") or value.get("api_key"))
        return candidate if is_valid_key(candidate) else ""
    except Exception:
        return ""


def _key_from_opencode_config() -> str:
    try:
        import jsonc_config
        path = jsonc_config.config_path(hub_paths.OPENCODE_CONFIG_DIR)
    except Exception:
        path = hub_paths.OPENCODE_CONFIG_FILE
    if not path.exists():
        return ""
    try:
        import jsonc_config
        data = jsonc_config.parse_config(path.read_text(encoding="utf-8-sig"))
    except Exception:
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
    global _auto_import_pending
    if SECRET_FILE.exists():
        try:
            record = json.loads(SECRET_FILE.read_text(encoding="utf-8"))
            stored = clean_key(unprotect_secret(record, "deepseek-api-key").get("apiKey"))
            if is_valid_key(stored):
                return stored
        except Exception:
            pass
    if load_config().get("auto_import_disabled"):
        return ""
    imported = _key_from_environment() or _key_from_opencode_db() or _key_from_opencode_config()
    if imported:
        try:
            save_api_key(imported)
            _auto_import_pending = True
        except Exception:
            pass
    return imported


def api_origin(base_url: Optional[str] = None) -> str:
    raw = (base_url or load_config().get("base_url") or DEFAULT_BASE_URL).strip().rstrip("/")
    parsed = urllib.parse.urlparse(raw)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Укажите корректный HTTPS URL DeepSeek API без логина и пароля")
    host = f"[{parsed.hostname}]" if ":" in parsed.hostname else parsed.hostname
    return f"https://{host}{':' + str(parsed.port) if parsed.port else ''}"


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


def _pick_primary_balance(balances: list) -> Dict[str, Any]:
    """Pick the currency that is actually worth showing.

    ``GET /user/balance`` returns one entry per currency and their order is not
    stable: the same account may answer ``[USD, CNY]`` and a second later
    ``[CNY, USD]``. Taking the first entry made the Hub flash between the real
    CNY balance and ``0.00 USD``. Prefer a funded currency, then the largest
    amount, and fall back to CNY when every entry is empty.
    """
    funded = [item for item in balances if (item.get("total_balance") or 0) > 0]
    if funded:
        return max(funded, key=lambda item: item.get("total_balance") or 0)
    cny = [item for item in balances if str(item.get("currency") or "").upper() == "CNY"]
    return cny[0] if cny else balances[0]


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

    primary = _pick_primary_balance(balances)
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
    cfg["cached_balance"] = result
    save_config(cfg)
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
    global _auto_import_pending
    cfg = load_config()
    key = load_api_key()
    if _auto_import_pending:
        _auto_import_pending = False
        try:
            fetch_balance()
        except Exception:
            pass
    balance = cached_balance()
    return {
        "connected": bool(key and cfg.get("connected")),
        "hasKey": bool(key),
        "keyLabel": mask_key(key),
        "baseUrl": cfg.get("base_url") or DEFAULT_BASE_URL,
        "balance": balance,
        "models": cfg.get("models") or FALLBACK_MODELS,
        "selectedModels": selected_models(),
        "providerId": find_provider_id(),
    }


# ---------------------------------------------------------------------------
# OpenCode provider registration (so DeepSeek appears as a real provider)
# ---------------------------------------------------------------------------
def _opencode_config_path() -> Path:
    return jsonc_config.config_path(hub_paths.OPENCODE_CONFIG_DIR)


def _read_opencode_config() -> tuple[Path, str, dict]:
    path = _opencode_config_path()
    original = path.read_text(encoding="utf-8-sig") if path.exists() else "{}\n"
    return path, original, jsonc_config.parse_config(original)


def _provider_base_host(provider: Any) -> str:
    if not isinstance(provider, dict):
        return ""
    for holder in (provider.get("options"), provider.get("settings"), provider):
        if isinstance(holder, dict):
            raw = holder.get("baseURL") or holder.get("baseUrl")
            if isinstance(raw, str) and raw.strip():
                try:
                    return (urllib.parse.urlparse(raw.strip()).hostname or "").lower()
                except ValueError:
                    return ""
    return ""


def find_provider_id(config: Optional[dict] = None) -> str:
    """Reuse an existing provider that already points at api.deepseek.com."""
    try:
        data = config if isinstance(config, dict) else _read_opencode_config()[2]
    except Exception:
        return PROVIDER_ID
    providers = data.get("provider")
    if isinstance(providers, dict):
        for name, provider in providers.items():
            host = _provider_base_host(provider)
            if host and (host == "api.deepseek.com" or host.endswith(".deepseek.com")):
                return str(name)
    return PROVIDER_ID


def _normalize_model(item: Any) -> Optional[Dict[str, Any]]:
    if isinstance(item, str) and item.strip():
        model_id, name = item.strip(), item.strip()
    elif isinstance(item, dict) and isinstance(item.get("id"), str) and item["id"].strip():
        model_id = item["id"].strip()
        name = str(item.get("name") or model_id)
    else:
        return None
    limits = MODEL_LIMITS.get(model_id, {"context": 65536, "output": 8192})
    context = item.get("context") if isinstance(item, dict) else None
    output = item.get("output") if isinstance(item, dict) else None
    return {
        "id": model_id,
        "name": name,
        "context": context if isinstance(context, int) and context > 0 else limits["context"],
        "output": output if isinstance(output, int) and output > 0 else limits["output"],
    }


def fetch_models(api_key: Optional[str] = None, base_url: Optional[str] = None,
                 timeout: int = 15) -> List[Dict[str, Any]]:
    """Read the real model catalog from GET /models on the Platform API."""
    key = clean_key(api_key) or load_api_key()
    if not key:
        raise ValueError("Сначала сохраните API-ключ DeepSeek")
    try:
        endpoint = f"{api_origin(base_url)}/models"
    except ValueError as exc:
        raise ValueError(str(exc)) from None
    request = urllib.request.Request(endpoint, headers={
        "Authorization": f"Bearer {key}",
        "Accept": "application/json",
        "User-Agent": USER_AGENT,
    }, method="GET")
    try:
        opener = get_http_opener()
        with opener.open(request, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            raise ValueError("DeepSeek отклонил API-ключ (401). Проверьте ключ.") from None
        if exc.code == 402:
            raise ValueError("DeepSeek: баланс ключа исчерпан (402)") from None
        if exc.code == 429:
            raise ValueError("DeepSeek вернул 429 — слишком частые запросы") from None
        raise ValueError(f"DeepSeek вернул HTTP {exc.code} при загрузке моделей") from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise ValueError("Не удалось подключиться к DeepSeek. Проверьте интернет и маршрут.") from None
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise ValueError("DeepSeek вернул некорректный каталог моделей") from None

    items = payload.get("data") if isinstance(payload, dict) else payload
    models: List[Dict[str, Any]] = []
    seen = set()
    for item in items if isinstance(items, list) else []:
        model = _normalize_model(item)
        if model and model["id"] not in seen:
            seen.add(model["id"])
            models.append(model)
    if not models:
        models = [dict(model) for model in FALLBACK_MODELS]
    models.sort(key=lambda model: model["id"].lower())
    return models


def selected_models(config: Optional[dict] = None) -> List[str]:
    """Selected model IDs currently registered in opencode.json(c)."""
    try:
        data = config if isinstance(config, dict) else _read_opencode_config()[2]
    except Exception:
        return []
    provider = (data.get("provider") or {}).get(find_provider_id(data), {})
    models = provider.get("models") if isinstance(provider, dict) else None
    return list(models) if isinstance(models, dict) else []


def configure_opencode_models(model_ids: Optional[List[str]] = None,
                              api_key: Optional[str] = None,
                              base_url: Optional[str] = None) -> List[str]:
    """Register the DeepSeek provider with the selected models in OpenCode."""
    key = clean_key(api_key) or load_api_key()
    if not key:
        raise ValueError("Сначала сохраните API-ключ DeepSeek")
    origin = api_origin(base_url)
    catalog = [model for model in (load_config().get("models") or FALLBACK_MODELS)
               if isinstance(model, dict) and model.get("id")]
    if not catalog:
        catalog = [dict(model) for model in FALLBACK_MODELS]
    available = {model["id"]: model for model in catalog}
    wanted = [str(mid) for mid in (model_ids or []) if str(mid) in available]
    if not wanted:
        wanted = list(available.keys())

    path, original, data = _read_opencode_config()
    provider_id = find_provider_id(data)
    providers = data.get("provider")
    if providers is not None and not isinstance(providers, dict):
        raise ValueError("Поле provider в конфигурации OpenCode должно быть объектом.")
    existing = (providers or {}).get(provider_id)
    existing_models = existing.get("models") if isinstance(existing, dict) else None

    merged: Dict[str, Any] = dict(existing_models) if isinstance(existing_models, dict) else {}
    for model_id in wanted:
        meta = available[model_id]
        merged[model_id] = {
            "name": meta.get("name") or model_id,
            "limit": {"context": meta["context"], "output": meta["output"]},
        }

    if isinstance(existing, dict):
        # Keep the user's own provider settings; only refresh the model list.
        updated = jsonc_config.set_property(original, ("provider", provider_id, "models"), merged)
    else:
        updated = jsonc_config.set_property(original, ("provider", provider_id), {
            "npm": "@ai-sdk/openai-compatible",
            "name": PROVIDER_NAME,
            "options": {"baseURL": origin},
            "models": merged,
        })
    if "$schema" not in data:
        updated = jsonc_config.set_property(updated, ("$schema",), "https://opencode.ai/config.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(path, updated)

    cfg = load_config()
    cfg["models"] = catalog
    cfg["selected_models"] = wanted
    cfg["provider_id"] = provider_id
    cfg["base_url"] = origin
    save_config(cfg)
    return wanted


def sync_opencode_credential(api_key: Optional[str] = None, provider_id: Optional[str] = None) -> None:
    """Import the key through OpenCode CLI so its credential store has it."""
    key = clean_key(api_key) or load_api_key()
    if not key:
        raise ValueError("Сначала сохраните API-ключ DeepSeek")
    cli = openai_manager.find_opencode_cli()
    if not cli:
        raise ValueError("Не найден OpenCode CLI. Запустите OpenCode и повторите подключение.")
    target = provider_id or find_provider_id()
    credential = [{
        "id": f"cred_{target}_hub",
        "integrationID": target,
        "label": f"{PROVIDER_NAME} (Antigravity Hub)",
        "active": True,
        "value": {"type": "key", "key": key},
    }]
    try:
        import subprocess
        result = subprocess.run(
            [cli, "auth", "import"],
            input=json.dumps(credential), capture_output=True, text=True,
            encoding="utf-8", timeout=15,
        )
        if result.returncode != 0:
            # Never surface CLI output: it may include the credential.
            raise ValueError("OpenCode не принял API-ключ. Перезапустите OpenCode и повторите.")
    except subprocess.TimeoutExpired:
        raise ValueError("OpenCode CLI не ответил вовремя при сохранении ключа.") from None
    except OSError:
        raise ValueError("Не удалось запустить OpenCode CLI для сохранения ключа.") from None


def disconnect_opencode() -> bool:
    """Remove the DeepSeek models from OpenCode and drop stored credentials."""
    removed = False
    try:
        path, original, data = _read_opencode_config()
        providers = data.get("provider")
        if isinstance(providers, dict):
            updated = original
            for provider_id in {find_provider_id(data), PROVIDER_ID, "deepseek"}:
                provider = providers.get(provider_id)
                if isinstance(provider, dict) and isinstance(provider.get("models"), dict):
                    updated = jsonc_config.set_property(updated, ("provider", provider_id, "models"), {})
                    removed = True
            if updated != original:
                atomic_write(path, updated)
    except Exception as exc:
        print(f"[DeepSeek API] Failed to update opencode.json: {exc}")

    cli = openai_manager.find_opencode_cli()
    if cli:
        import subprocess
        for provider_id in _OPENCODE_INTEGRATIONS:
            try:
                subprocess.run([cli, "auth", "logout", provider_id], capture_output=True, timeout=15)
            except Exception:
                pass
    return removed
