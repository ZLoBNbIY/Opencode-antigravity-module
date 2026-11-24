"""DeepSeek Platform API (sk- keys) balance tracking for AI HUB.

This module is intentionally separate from the legacy DeepSeek Web integration.
The paid Platform API exposes ``GET /user/balance`` which returns a prepaid
balance rather than the 5h/weekly window quotas used by Google or ChatGPT.
"""

import json
import math
import os
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

import hub_paths
import jsonc_config
import opencode_credentials
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
            "auto_import_disabled": False, "models": [], "selected_models": [],
            "provider_id": "", "managed_models": {}}


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
    cfg = load_config()
    if _stored_key()[0] != key:
        cfg["cached_balance"] = {}
    atomic_write(SECRET_FILE, json.dumps(protect_secret("deepseek-api-key", {"apiKey": key})))
    cfg["connected"] = True
    # An explicit key always re-enables adoption from OpenCode/env on next start.
    cfg["auto_import_disabled"] = False
    if not save_config(cfg):
        raise OSError("Не удалось сохранить настройки DeepSeek")
    return True


def clear_api_key() -> bool:
    global _auto_import_pending
    cfg = load_config()
    cfg.update(connected=False, cached_balance={}, auto_import_disabled=True)
    if not save_config(cfg):
        return False
    _auto_import_pending = False
    try:
        SECRET_FILE.unlink(missing_ok=True)
    except OSError:
        return False
    return True


def _key_from_environment() -> str:
    for name in _ENV_KEYS:
        value = clean_key(os.environ.get(name))
        if is_valid_key(value):
            return value
    return ""


def _config_path_safe() -> Optional[Path]:
    try:
        return _opencode_config_path()
    except Exception:
        return None


def _stored_key() -> tuple[str, int]:
    """Key held by the Hub plus the moment it was written (ms)."""
    if not SECRET_FILE.exists():
        return "", 0
    try:
        updated = int(SECRET_FILE.stat().st_mtime_ns // 1_000_000)
        record = json.loads(SECRET_FILE.read_text(encoding="utf-8"))
        stored = clean_key(unprotect_secret(record, "deepseek-api-key").get("apiKey"))
    except Exception:
        return "", 0
    return (stored, updated) if is_valid_key(stored) else ("", 0)


def _opencode_candidate() -> tuple[str, int]:
    """Newest DeepSeek key OpenCode already has, with its timestamp."""
    try:
        return opencode_credentials.read_key(
            _OPENCODE_INTEGRATIONS, config_path=_config_path_safe(), name_hint="deepseek")
    except Exception:
        return "", 0


def _key_from_opencode_db() -> str:
    try:
        return opencode_credentials.read_key(_OPENCODE_INTEGRATIONS)[0]
    except Exception:
        return ""


def _key_from_opencode_config() -> str:
    try:
        return opencode_credentials.read_config_key(_config_path_safe(), "deepseek")[0]
    except Exception:
        return ""


def load_api_key() -> str:
    """Return the stored key, adopting a newer one from OpenCode when present.

    Both directions share one rule: the newest copy wins.  A key typed in the
    Hub is pushed to OpenCode when saved, so the copies normally match; when
    they differ, the newer side replaced the key and must be adopted.
    """
    global _auto_import_pending
    stored, stored_ms = _stored_key()
    disabled = bool(load_config().get("auto_import_disabled"))
    if disabled:
        return ""
    if stored:
        candidate, candidate_ms = _opencode_candidate()
        if is_valid_key(candidate) and candidate != stored and candidate_ms > stored_ms:
            try:
                save_api_key(candidate)
                _auto_import_pending = True
                return candidate
            except Exception:
                pass
        return stored
    imported = _key_from_environment() or _opencode_candidate()[0]
    if imported and is_valid_key(imported):
        try:
            save_api_key(imported)
            _auto_import_pending = True
        except Exception:
            pass
            return ""
        return imported
    return ""


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
        if isinstance(value, bool):
            return None
        try:
            number = float(value)
            return round(number, 4) if math.isfinite(number) else None
        except (TypeError, ValueError, OverflowError):
            return None

    infos = payload.get("balance_infos")
    if not isinstance(infos, list) or not infos:
        raise ValueError("DeepSeek не вернул данные о балансе")

    balances = []
    for info in infos:
        if not isinstance(info, dict):
            continue
        total = amount(info.get("total_balance"))
        if total is None:
            continue
        balances.append({
            "currency": info.get("currency") or "CNY",
            "total_balance": total,
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
        error = "DeepSeek вернул некорректный баланс" if isinstance(exc, ValueError) else "Не удалось обновить баланс DeepSeek"

    cfg = load_config()
    cached = cfg.get("cached_balance")
    if isinstance(cached, dict) and cached.get("status") in ("ok", "stale"):
        stale = dict(cached)
        stale["status"] = "stale"
        stale["error"] = error
        result = stale
    else:
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
    key = load_api_key()
    cfg = load_config()
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
    """Reuse the DeepSeek provider OpenCode already uses, if any."""
    try:
        data = config if isinstance(config, dict) else _read_opencode_config()[2]
    except Exception:
        data = None
    providers = (data or {}).get("provider")
    if isinstance(providers, dict) and isinstance(providers.get("deepseek"), dict):
        return "deepseek"
    # A key added through OpenCode's own "Sign in" lives on the built-in
    # DeepSeek provider; writing our models there avoids a duplicate provider.
    try:
        if opencode_credentials.has_credential("deepseek"):
            return "deepseek"
    except Exception:
        pass
    if isinstance(providers, dict):
        for name, provider in providers.items():
            host = _provider_base_host(provider)
            if host and (host == "api.deepseek.com" or host.endswith(".deepseek.com")):
                return str(name)
    return PROVIDER_ID


def _uses_builtin_provider(provider_id: str) -> bool:
    """True when OpenCode already defines this provider itself (no config entry)."""
    if provider_id != "deepseek":
        return False
    try:
        return opencode_credentials.has_credential(provider_id)
    except Exception:
        return False


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
    if not isinstance(items, list):
        raise ValueError("DeepSeek вернул некорректный каталог моделей")
    for item in items:
        model = _normalize_model(item)
        if model and model["id"] not in seen:
            seen.add(model["id"])
            models.append(model)
    if items and not models:
        raise ValueError("DeepSeek вернул некорректный каталог моделей")
    models.sort(key=lambda model: model["id"].lower())
    return models


def selected_models(config: Optional[dict] = None) -> List[str]:
    """Hub-selected models still present in OpenCode, not user-owned extras."""
    try:
        data = config if isinstance(config, dict) else _read_opencode_config()[2]
    except Exception:
        return []
    cfg = load_config()
    providers = data.get("provider")
    provider = providers.get(cfg.get("provider_id") or find_provider_id(data)) if isinstance(providers, dict) else None
    models = provider.get("models") if isinstance(provider, dict) else None
    return [mid for mid in cfg["selected_models"] if mid in models] if isinstance(models, dict) else []


def _remove_managed_models(text: str, data: dict, cfg: dict, *, keep=()) -> str:
    """Only remove an entry that still equals what the Hub installed."""
    provider_id = cfg.get("provider_id") or find_provider_id(data)
    providers = data.get("provider")
    provider = providers.get(provider_id) if isinstance(providers, dict) else None
    models = provider.get("models") if isinstance(provider, dict) else None
    managed = cfg.get("managed_models")
    if isinstance(models, dict) and isinstance(managed, dict):
        for mid, descriptor in managed.items():
            if mid not in keep and mid in models and models[mid] == descriptor:
                text = jsonc_config.remove_property(text, ("provider", provider_id, "models", mid))
    return text


def configure_opencode_models(model_ids: Optional[List[str]] = None,
                              api_key: Optional[str] = None,
                              base_url: Optional[str] = None) -> List[str]:
    """Register the DeepSeek provider with the selected models in OpenCode."""
    key = clean_key(api_key) or load_api_key()
    if not key:
        raise ValueError("Сначала сохраните API-ключ DeepSeek")
    origin = api_origin(base_url)
    cfg = load_config()
    catalog = [model for item in (cfg.get("models") or FALLBACK_MODELS)
               if (model := _normalize_model(item))]
    if not catalog:
        catalog = [dict(model) for model in FALLBACK_MODELS]
    available = {model["id"]: model for model in catalog}
    wanted = list(available) if model_ids is None else list(dict.fromkeys(str(mid) for mid in model_ids))
    if any(mid not in available for mid in wanted):
        raise ValueError("Выберите модели из каталога DeepSeek")

    path, original, data = _read_opencode_config()
    providers = data.get("provider")
    if providers is not None and not isinstance(providers, dict):
        raise ValueError("Поле provider в конфигурации OpenCode должно быть объектом.")
    provider_id = cfg.get("provider_id")
    if not provider_id or provider_id not in (providers or {}):
        provider_id = find_provider_id(data)
    existing = (providers or {}).get(provider_id)
    if existing is not None and not isinstance(existing, dict):
        raise ValueError("Конфигурация провайдера DeepSeek имеет неподдерживаемый формат.")
    existing_models = existing.get("models") if isinstance(existing, dict) else None
    if existing_models is not None and not isinstance(existing_models, dict):
        raise ValueError("Поле models провайдера DeepSeek должно быть объектом.")
    existing_models = existing_models or {}
    previous = cfg.get("managed_models") if provider_id == cfg.get("provider_id") else {}
    previous = previous if isinstance(previous, dict) else {}
    managed = {}
    updated = _remove_managed_models(original, data, cfg, keep=wanted)
    for model_id in wanted:
        if model_id in existing_models:
            if model_id in previous and existing_models[model_id] == previous[model_id]:
                managed[model_id] = previous[model_id]
            continue
        meta = available[model_id]
        managed[model_id] = {
            "name": meta.get("name") or model_id,
            "limit": {"context": meta["context"], "output": meta["output"]},
        }
    if wanted and existing is None and not _uses_builtin_provider(provider_id):
        updated = jsonc_config.set_property(updated, ("provider", provider_id), {
            "npm": "@ai-sdk/openai-compatible", "name": PROVIDER_NAME,
            "options": {"baseURL": origin}, "models": managed,
        })
    else:
        for mid, descriptor in managed.items():
            if mid not in existing_models:
                updated = jsonc_config.set_property(updated, ("provider", provider_id, "models", mid), descriptor)
    if wanted and "$schema" not in data:
        updated = jsonc_config.set_property(updated, ("$schema",), "https://opencode.ai/config.json")
    if updated != original:
        atomic_write(path, updated, private_parent=False)

    cfg["models"] = catalog
    cfg["selected_models"] = wanted
    cfg["provider_id"] = provider_id
    cfg["managed_models"] = managed
    cfg["base_url"] = origin
    if not save_config(cfg):
        if updated != original:
            atomic_write(path, original, private_parent=False)
        raise OSError("Не удалось сохранить выбранные модели DeepSeek")
    return wanted


def sync_opencode_credential(api_key: Optional[str] = None, provider_id: Optional[str] = None) -> None:
    """Import the key through OpenCode CLI so its credential store has it."""
    key = clean_key(api_key) or load_api_key()
    if not key:
        raise ValueError("Сначала сохраните API-ключ DeepSeek")
    cli = openai_manager.find_opencode_cli()
    if not cli:
        raise ValueError("Не найден OpenCode CLI. Запустите OpenCode и повторите подключение.")
    target = provider_id or load_config().get("provider_id") or find_provider_id()
    existing_id = ""
    try:
        existing_id = opencode_credentials.credential_id(target)
    except Exception:
        pass
    credential = [{
        # Reuse the stored credential row so the import updates it in place
        # instead of leaving two keys for the same integration.
        "id": existing_id or f"cred_{target}_hub",
        "integrationID": target,
        "label": f"{PROVIDER_NAME} (AI HUB)",
        "active": True,
        "value": {"type": "key", "key": key},
    }]
    try:
        result = subprocess.run(
            [cli, "auth", "import"],
            input=json.dumps(credential), capture_output=True, text=True,
            encoding="utf-8", timeout=15,
        )
        if result.returncode != 0:
            # Never surface CLI output: it may include the credential.
            raise ValueError("OpenCode не принял API-ключ. Перезапустите OpenCode и повторите.")
        opencode_credentials.invalidate()
    except subprocess.TimeoutExpired:
        raise ValueError("OpenCode CLI не ответил вовремя при сохранении ключа.") from None
    except OSError:
        raise ValueError("Не удалось запустить OpenCode CLI для сохранения ключа.") from None


def disconnect_opencode() -> bool:
    """Remove Hub model entries and sign out the registered integration."""
    cfg = load_config()
    try:
        path, original, data = _read_opencode_config()
        target = cfg.get("provider_id") or find_provider_id(data)
        cli = openai_manager.find_opencode_cli()
        if not cli and opencode_credentials.has_credential(target):
            return False
        updated = _remove_managed_models(original, data, cfg)
        if updated != original:
            atomic_write(path, updated, private_parent=False)
        if cli:
            try:
                result = subprocess.run([cli, "auth", "logout", target], capture_output=True, timeout=15)
                if result.returncode != 0:
                    raise OSError("Ключ DeepSeek не удалён из OpenCode")
            except (OSError, subprocess.TimeoutExpired):
                if updated != original:
                    atomic_write(path, original, private_parent=False)
                return False
            finally:
                opencode_credentials.invalidate()
        cfg.update(selected_models=[], managed_models={}, provider_id="")
        return save_config(cfg)
    except Exception as exc:
        print(f"[DeepSeek API] Disconnect failed ({type(exc).__name__})")
        return False
