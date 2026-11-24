"""TokenLavka OpenAI-compatible API-key provider for AI HUB.

The key is an ``sk-`` token issued by tokenlavka.com.  It is stored encrypted
in the Hub's secure directory and mirrored into OpenCode's credential store.
The provider descriptor written to ``opencode.json`` follows the official
OpenCode guide: ``@ai-sdk/openai-compatible`` + ``https://tokenlavka.com/v1``.
"""
import json
import math
from pathlib import Path
import subprocess
import time
import urllib.error
import urllib.request
from typing import Any, Dict, Optional

import secure_storage
import jsonc_config
import opencode_credentials
import openai_manager


PROVIDER_ID = "tokenlavka"
OPENCODE_INTEGRATIONS = ("tokenlavka",)
BASE_URL = "https://tokenlavka.com/v1"
MODELS_URL = f"{BASE_URL}/models"
PORTAL_URL = "https://tokenlavka.com/api/portal"
SECRET_PURPOSE = "tokenlavka-api-key"
DEFAULT_MODEL = "gpt-6-luna"
try:
    import hub_paths
    SECRET_FILE = hub_paths.TOKENLAVKA_SECRET_FILE
    BALANCE_CONFIG_FILE = hub_paths.TOKENLAVKA_CONFIG_FILE
    CONFIG_DIR = hub_paths.OPENCODE_CONFIG_DIR
except Exception:
    SECRET_FILE = Path.home() / ".local" / "share" / "antigravity-hub" / "tokenlavka.json"
    BALANCE_CONFIG_FILE = Path.home() / ".local" / "share" / "antigravity-hub" / "tokenlavka-state.json"
    CONFIG_DIR = Path.home() / ".config" / "opencode"

# Exact IDs from https://tokenlavka.com/help ("Доступные модели").
# Every model on the gateway currently shares the same window and response cap.
_CONTEXT = 512000
_OUTPUT = 65536
TOKENLAVKA_MODELS = {
    "claude-opus-5-5": {"name": "Claude Opus 5.5", "context": _CONTEXT, "output": _OUTPUT},
    "claude-opus-4-8": {"name": "Claude Opus 4.8", "context": _CONTEXT, "output": _OUTPUT},
    "claude-opus-5": {"name": "Claude Opus 5", "context": _CONTEXT, "output": _OUTPUT},
    "claude-opus-4-7": {"name": "Claude Opus 4.7", "context": _CONTEXT, "output": _OUTPUT},
    "claude-opus-4-6": {"name": "Claude Opus 4.6", "context": _CONTEXT, "output": _OUTPUT},
    "claude-sonnet-5": {"name": "Claude Sonnet 5", "context": _CONTEXT, "output": _OUTPUT},
    "claude-fable-5": {"name": "Claude Fable 5", "context": _CONTEXT, "output": _OUTPUT},
    "claude-fable-5-1": {"name": "Claude Fable 5.1", "context": _CONTEXT, "output": _OUTPUT},
    "gpt-6-astra": {"name": "GPT 6 Astra", "context": _CONTEXT, "output": _OUTPUT},
    "gpt-6-luna": {"name": "GPT-6 Luna", "context": _CONTEXT, "output": _OUTPUT},
    "gpt-5-6-sol": {"name": "GPT 5.6 Sol", "context": _CONTEXT, "output": _OUTPUT},
    "gpt-5-6-terra": {"name": "GPT 5.6 Terra", "context": _CONTEXT, "output": _OUTPUT},
    "gpt-5-6-luna": {"name": "GPT 5.6 Luna", "context": _CONTEXT, "output": _OUTPUT},
    "gpt-5-5": {"name": "GPT 5.5", "context": _CONTEXT, "output": _OUTPUT},
    "gpt-5-4": {"name": "GPT 5.4", "context": _CONTEXT, "output": _OUTPUT},
    "gemini-3.1-pro-preview": {"name": "Gemini 3.1 Pro", "context": _CONTEXT, "output": _OUTPUT},
    "glm-5.3": {"name": "GLM-5.3", "context": _CONTEXT, "output": _OUTPUT},
    "glm-5.3-flash": {"name": "GLM-5.3 Flash", "context": _CONTEXT, "output": _OUTPUT},
    "grok-4.7": {"name": "Grok 4.7", "context": _CONTEXT, "output": _OUTPUT},
    "grok-4.6": {"name": "Grok 4.6", "context": _CONTEXT, "output": _OUTPUT},
    "kimi-k3": {"name": "Kimi K3", "context": _CONTEXT, "output": _OUTPUT},
    "kimi-k2.7-code": {"name": "Kimi K2.7 Code", "context": _CONTEXT, "output": _OUTPUT},
    "deepseek-v4-pro": {"name": "DeepSeek V4 Pro", "context": _CONTEXT, "output": _OUTPUT},
    "deepseek-v4.1-pro": {"name": "DeepSeek V4.1 Pro", "context": _CONTEXT, "output": _OUTPUT},
    "deepseek-v4.1-flash": {"name": "DeepSeek V4.1 Flash", "context": _CONTEXT, "output": _OUTPUT},
    "qwen-3.8-max": {"name": "Qwen 3.8 Max", "context": _CONTEXT, "output": _OUTPUT},
    "qwen-3.8-flash": {"name": "Qwen 3.8 Flash", "context": _CONTEXT, "output": _OUTPUT},
    "qwen-3.8-omni": {"name": "Qwen 3.8 Omni", "context": _CONTEXT, "output": _OUTPUT},
    "economy": {"name": "Экономичный режим · GPT-6 Luna", "context": _CONTEXT, "output": _OUTPUT},
}


def _opener():
    """Route catalog/auth requests through the per-provider dispatcher."""
    import provider_proxy
    proxy_url = provider_proxy.proxy_url_for_hub_requests()
    return urllib.request.build_opener(
        urllib.request.ProxyHandler({"http": proxy_url, "https": proxy_url})
    )


def save_api_key(api_key):
    previous, _ = _stored_key()
    record = secure_storage.protect_secret(SECRET_PURPOSE, {"apiKey": api_key})
    secure_storage.atomic_write(SECRET_FILE, json.dumps(record))
    cfg = load_config()
    if previous != api_key or cfg.get("auto_import_disabled"):
        cfg.update(cached_balance={}, auto_import_disabled=False)
        save_config(cfg)


def _stored_key():
    """Key stored by the Hub plus when it was written (ms)."""
    if not SECRET_FILE.exists():
        return "", 0
    try:
        updated = int(SECRET_FILE.stat().st_mtime_ns // 1_000_000)
        record = json.loads(SECRET_FILE.read_text(encoding="utf-8"))
        key = str(secure_storage.unprotect_secret(record, SECRET_PURPOSE).get("apiKey") or "").strip()
    except Exception:
        return "", 0
    return (key, updated) if key else ("", 0)


def _opencode_candidate():
    """Newest TokenLavka key OpenCode already has, with its timestamp."""
    try:
        config_path = jsonc_config.config_path(CONFIG_DIR)
    except Exception:
        config_path = CONFIG_DIR / "opencode.json"
    try:
        return opencode_credentials.read_key(
            OPENCODE_INTEGRATIONS, config_path=config_path, name_hint="tokenlavka", exact_config=True)
    except Exception:
        return "", 0


def load_api_key():
    """Adopt the newest key: whichever side (Hub or OpenCode) changed last wins."""
    if load_config().get("auto_import_disabled"):
        return ""
    key, updated = _stored_key()
    candidate, candidate_at = _opencode_candidate()
    if candidate and candidate != key and candidate_at > updated:
        try:
            save_api_key(candidate)
        except Exception:
            return key
        return candidate
    if key:
        return key
    if candidate:
        try:
            save_api_key(candidate)
        except Exception:
            return ""
    return candidate


# ---------------------------------------------------------------------------
# Balance (TokenLavka portal API)
# ---------------------------------------------------------------------------

def _default_config() -> Dict[str, Any]:
    return {"connected": False, "cached_balance": {}, "auto_import_disabled": False}


def load_config() -> Dict[str, Any]:
    cfg = _default_config()
    if not BALANCE_CONFIG_FILE.exists():
        return cfg
    try:
        stored = json.loads(BALANCE_CONFIG_FILE.read_text(encoding="utf-8"))
        if isinstance(stored, dict):
            cfg.update(stored)
        if not isinstance(cfg.get("cached_balance"), dict):
            cfg["cached_balance"] = {}
    except Exception:
        pass
    return cfg


def save_config(cfg: Dict[str, Any]) -> None:
    BALANCE_CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    secure_storage.atomic_write(BALANCE_CONFIG_FILE, json.dumps(cfg, indent=2, ensure_ascii=False))


def empty_balance(status: str = "no_key") -> Dict[str, Any]:
    return {
        "status": status,
        "currency": " ед.",
        "issued": None,
        "spent": None,
        "balance": None,
        "reserved": None,
        "remaining_percent": None,
        "used_percent": None,
        "checked_at": None,
        "error": None,
    }


def parse_balance_payload(payload: Any) -> Dict[str, Any]:
    """Convert POST /api/portal JSON into a stable Hub quota object."""
    if not isinstance(payload, dict):
        raise ValueError("Некорректный ответ TokenLavka")
    key = payload.get("key")
    if not isinstance(key, dict):
        raise ValueError("TokenLavka не вернула данные о ключе")

    def amount(value: Any) -> Optional[float]:
        if isinstance(value, bool):
            return None
        try:
            number = float(value)
            return round(number, 2) if math.isfinite(number) else None
        except (TypeError, ValueError, OverflowError):
            return None

    issued = amount(key.get("total_added"))
    balance = amount(key.get("balance"))
    if balance is None:
        raise ValueError("TokenLavka не вернула баланс ключа")
    spent = amount(key.get("spent"))
    if spent is None and issued is not None and balance is not None:
        spent = round(max(0.0, issued - balance), 2)
    remaining_pct = None
    used_pct = None
    if issued and issued > 0 and balance is not None:
        remaining_pct = round(max(0.0, min(100.0, balance * 100 / issued)), 1)
        used_pct = round(100.0 - remaining_pct, 1)
    return {
        "status": "ok",
        "currency": " ед.",
        "issued": issued,
        "spent": spent,
        "balance": balance,
        "reserved": amount(key.get("reserved")),
        "remaining_percent": remaining_pct,
        "used_percent": used_pct,
        "checked_at": int(time.time()),
        "error": None,
    }


def fetch_balance(api_key: Optional[str] = None, timeout: int = 15) -> Dict[str, Any]:
    """Fetch the key balance from the portal; keep last known values as stale on failure."""
    key = (api_key or load_api_key() or "").strip()
    if not key:
        result = empty_balance("no_key")
        result["error"] = "Сначала сохраните API-ключ TokenLavka"
        return result

    request = urllib.request.Request(
        PORTAL_URL,
        data=json.dumps({"key": key}).encode("utf-8"),
        headers={"Content-Type": "application/json", "User-Agent": "Antigravity-Hub",
                 "Accept": "application/json"},
        method="POST",
    )
    error = None
    try:
        with _opener().open(request, timeout=timeout) as response:
            result = parse_balance_payload(json.loads(response.read().decode("utf-8")))
        cfg = load_config()
        cfg["cached_balance"] = result
        cfg["connected"] = True
        save_config(cfg)
        return result
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            error = "TokenLavka не распознала ключ (401). Проверьте, что он скопирован целиком."
        elif exc.code == 402:
            error = "TokenLavka: баланс ключа исчерпан (402)"
        elif exc.code == 404:
            error = "TokenLavka: ключ не найден (404)"
        elif exc.code == 429:
            error = "TokenLavka вернула 429 — слишком часто обращаемся к балансу"
        else:
            error = f"TokenLavka вернула HTTP {exc.code} при запросе баланса"
    except Exception as exc:
        error = "TokenLavka вернула некорректный баланс" if isinstance(exc, ValueError) else "Не удалось обновить баланс TokenLavka"

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


def test_connection(api_key, timeout=20):
    """Validate the key against GET /v1/models. Returns (ok, message)."""
    ok, message, _status = probe_connection(api_key, timeout)
    return ok, message


def probe_connection(api_key, timeout=20):
    """Validate the catalog response and preserve the reason for health checks."""
    clean = str(api_key or "").strip()
    if not clean.startswith("sk-") or any(c in clean for c in "\r\n\x00"):
        return False, "Ключ tokenlavka должен начинаться с sk-", "invalid_key"
    request = urllib.request.Request(
        MODELS_URL,
        headers={"Authorization": f"Bearer {clean}", "User-Agent": "Antigravity-Hub"},
    )
    try:
        with _opener().open(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
            raise ValueError()
        return True, "Ключ tokenlavka принят", "active"
    except urllib.error.HTTPError as error:
        if error.code == 401:
            return False, "TokenLavka отклонила ключ (401). Проверьте, что он скопирован целиком.", "auth_failed"
        if error.code == 402:
            return False, "TokenLavka: insufficient balance (402). Пополните ключ.", "insufficient_balance"
        if error.code == 429:
            return False, "TokenLavka: слишком частые запросы (429). Повторите через несколько секунд.", "rate_limited"
        return False, f"TokenLavka вернула HTTP {error.code}", f"http_{error.code}"
    except (urllib.error.URLError, TimeoutError, OSError):
        return False, "Не удалось подключиться к TokenLavka. Проверьте интернет и маршрут.", "network_error"
    except ValueError:
        return False, "TokenLavka вернула некорректный ответ каталога моделей.", "invalid_response"


def sync_opencode_credential(api_key):
    """Import the key through OpenCode CLI so Desktop's credential store is updated."""
    cli = openai_manager.find_opencode_cli()
    if not cli:
        raise ValueError("Не найден OpenCode CLI. Запустите/установите OpenCode и повторите подключение.")
    existing_id = ""
    try:
        existing_id = opencode_credentials.credential_id(PROVIDER_ID)
    except Exception:
        pass
    credential = [{
        "id": existing_id or "cred_tokenlavka_hub",
        "integrationID": PROVIDER_ID,
        "label": "TokenLavka (AI HUB)",
        "active": True,
        "value": {"type": "key", "key": api_key},
    }]
    try:
        result = subprocess.run(
            [cli, "auth", "import"],
            input=json.dumps(credential), capture_output=True, text=True, encoding="utf-8", timeout=15,
        )
        if result.returncode != 0:
            # Never expose CLI output: it may include credential data.
            raise ValueError("OpenCode не принял API-ключ. Перезапустите OpenCode и попробуйте снова.")
        opencode_credentials.invalidate()
    except subprocess.TimeoutExpired:
        raise ValueError("OpenCode CLI не ответил вовремя при сохранении ключа.") from None
    except OSError:
        raise ValueError("Не удалось запустить OpenCode CLI для сохранения ключа.") from None


def configure_models(model_ids, api_key=None, config_dir=None):
    """Create the tokenlavka provider containing only the selected model IDs."""
    selected = [mid for mid in model_ids if mid in TOKENLAVKA_MODELS]
    if not selected:
        raise ValueError("Выберите хотя бы одну модель TokenLavka")
    if not (api_key or load_api_key()):
        raise ValueError("Сначала сохраните API-ключ TokenLavka")

    config_path = jsonc_config.config_path(Path(config_dir) if config_dir else CONFIG_DIR)
    original = config_path.read_text(encoding="utf-8-sig") if config_path.exists() else "{}\n"
    data = jsonc_config.parse_config(original)
    providers = data.get("provider", {})
    if not isinstance(providers, dict):
        raise ValueError("Поле provider в конфигурации OpenCode должно быть объектом.")
    existing = providers.get(PROVIDER_ID, {})
    if existing and not isinstance(existing, dict):
        raise ValueError("Конфигурация провайдера TokenLavka имеет неподдерживаемый формат.")

    configured_models = {}
    for model_id in selected:
        meta = TOKENLAVKA_MODELS[model_id]
        configured_models[model_id] = {
            "name": meta["name"],
            "limit": {"context": meta["context"], "output": meta["output"]},
        }
    updated = jsonc_config.set_property(original, ("provider", PROVIDER_ID), {
        "npm": "@ai-sdk/openai-compatible",
        "name": "TokenLavka",
        "options": {"baseURL": BASE_URL},
        "models": configured_models,
    })
    if "$schema" not in data:
        updated = jsonc_config.set_property(updated, ("$schema",), "https://opencode.ai/config.json")
    config_path.parent.mkdir(parents=True, exist_ok=True)
    secure_storage.atomic_write(config_path, updated, private_parent=False)
    return selected


def selected_models(config_dir=None):
    config_path = jsonc_config.config_path(Path(config_dir) if config_dir else CONFIG_DIR)
    if not config_path.exists():
        return []
    try:
        data = jsonc_config.parse_config(config_path.read_text(encoding="utf-8-sig"))
        return list(data.get("provider", {}).get(PROVIDER_ID, {}).get("models", {}))
    except Exception:
        return []


def disconnect():
    cli = openai_manager.find_opencode_cli()
    if not cli:
        raise ValueError("Не найден OpenCode CLI. Ключ Hub оставлен без изменений.")
    config_path = jsonc_config.config_path(CONFIG_DIR)
    original = updated = None
    if config_path.exists():
        original = config_path.read_text(encoding="utf-8-sig")
        updated = original
        providers = jsonc_config.parse_config(original).get("provider", {})
        if isinstance(providers, dict) and isinstance(providers.get(PROVIDER_ID), dict):
            updated = jsonc_config.set_property(original, ("provider", PROVIDER_ID, "models"), {})
    if updated != original:
        secure_storage.atomic_write(config_path, updated, private_parent=False)
    try:
        result = subprocess.run([cli, "auth", "logout", PROVIDER_ID], capture_output=True, timeout=15)
        if result.returncode != 0:
            raise OSError("OpenCode не удалил учётные данные TokenLavka")
    except (subprocess.TimeoutExpired, OSError):
        if updated != original:
            secure_storage.atomic_write(config_path, original, private_parent=False)
        raise ValueError("OpenCode не удалил учётные данные TokenLavka. Ключ Hub оставлен без изменений.") from None
    finally:
        opencode_credentials.invalidate()
    cfg = load_config()
    cfg.update(connected=False, cached_balance={}, auto_import_disabled=True)
    save_config(cfg)
    SECRET_FILE.unlink(missing_ok=True)


def provider_state():
    key = load_api_key()
    selected = selected_models()
    return {
        "hasKey": bool(key),
        "keyLabel": "••••" + key[-4:] if len(key) > 8 else "Ключ сохранён" if key else None,
        "connected": bool(key and selected),
        "selectedModels": selected,
        "models": [{"id": mid, "name": meta["name"],
                    "context": meta["context"], "output": meta["output"]}
                   for mid, meta in TOKENLAVKA_MODELS.items()],
        "baseUrl": BASE_URL,
        "balance": cached_balance(),
    }
