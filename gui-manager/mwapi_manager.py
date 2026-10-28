"""MWAPI (Cloud Code / CCS) integration for Antigravity Hub."""
import json
from pathlib import Path
import re
import subprocess
import urllib.error
import urllib.request

import deepseek_storage
import deepseek_config
import openai_manager


API_BASE_URL = "https://api.mwapi.dev/v1"
API_MODELS_URL = "https://api.mwapi.dev/v1/models"
API_USAGE_URL = "https://api.mwapi.dev/v1/usage"
PROFILE_URL = "https://api.mwapi.dev/api/v1/user/profile"
PROVIDER_ID = "mwapi"
SECRET_PURPOSE = "mwapi-api-key"
SECRET_FILE = Path.home() / ".local" / "share" / "antigravity-hub" / "mwapi.json"
TOKEN_SECRET_PURPOSE = "mwapi-dashboard-token"
TOKEN_SECRET_FILE = Path.home() / ".local" / "share" / "antigravity-hub" / "mwapi_token.json"
CONFIG_DIR = Path.home() / ".config" / "opencode"
LOCAL_PROXY = "http://127.0.0.1:51180"


def _request_with_fallback(request, timeout=20):
    """Use the same selected provider route for model and usage API calls."""
    import provider_proxy
    proxy_url = provider_proxy.proxy_url_for_hub_requests()
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({"http": proxy_url, "https": proxy_url})
    )
    with opener.open(request, timeout=timeout) as response:
        return response.read()


def _format_model_name(model_id: str) -> str:
    """Format model ID into a user-friendly display name."""
    clean = re.sub(r"[:/]", " ", model_id).strip()
    return clean.replace("-", " ").title()


def _infer_limits(model_id: str, item: dict) -> tuple[int, int]:
    """Determine context and max output limits based on model metadata and ID."""
    raw_ctx = item.get("context_length") or item.get("max_tokens")
    if isinstance(raw_ctx, int) and raw_ctx > 0:
        context = raw_ctx
    elif "gemini" in model_id.lower():
        context = 1000000
    elif any(k in model_id.lower() for k in ("claude-3-7", "claude-3.7", "claude-3-5", "claude-3.5", "claude-3-opus")):
        context = 200000
    elif any(k in model_id.lower() for k in ("o1", "o3", "deepseek")):
        context = 200000
    elif any(k in model_id.lower() for k in ("gpt-4o", "gpt-4")):
        context = 128000
    else:
        context = 128000

    if any(k in model_id.lower() for k in ("claude-3-7", "claude-3.7", "gemini", "o1", "o3")):
        output = 65536
    elif any(k in model_id.lower() for k in ("claude-3-5", "claude-3.5", "gpt-4o", "gpt-4")):
        output = 16384
    elif "opus" in model_id.lower():
        output = 4096
    else:
        output = 8192

    return context, output


def fetch_models(api_key: str, timeout: int = 20) -> list[dict]:
    """Fetch available models from MWAPI using the provided API key."""
    if not api_key or not api_key.strip():
        raise ValueError("API-ключ MWAPI не указан.")

    request = urllib.request.Request(
        API_MODELS_URL,
        headers={
            "Authorization": f"Bearer {api_key.strip()}",
            "User-Agent": "Antigravity-Hub",
            "Accept": "application/json",
        },
    )

    try:
        raw_data = _request_with_fallback(request, timeout=timeout)
        payload = json.loads(raw_data.decode("utf-8"))
    except urllib.error.HTTPError as error:
        if error.code == 401:
            raise ValueError("MWAPI отклонил API-ключ (401). Проверьте ключ в кабинете https://api.mwapi.dev/dashboard.") from None
        if error.code == 403:
            raise ValueError("MWAPI вернул 403: доступ запрещён. Проверьте права токена в MWAPI.") from None
        if error.code == 429:
            raise ValueError("MWAPI вернул 429: исчерпан лимит запросов или квота.") from None
        raise ValueError(f"MWAPI вернул HTTP {error.code} при загрузке списка моделей.") from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise ValueError("Не удалось подключиться к https://api.mwapi.dev. Проверьте подключение к интернету.") from None
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise ValueError("MWAPI вернул некорректный ответ каталога моделей.") from None

    data_list = payload.get("data", [])
    if isinstance(payload, list):
        data_list = payload

    models = []
    for item in data_list:
        if not isinstance(item, dict):
            continue
        model_id = item.get("id")
        if not isinstance(model_id, str) or not model_id.strip():
            continue
        model_id = model_id.strip()

        context, output = _infer_limits(model_id, item)
        name = item.get("name") or _format_model_name(model_id)

        models.append({
            "id": model_id,
            "name": name,
            "context": context,
            "output": output,
        })

    return sorted(models, key=lambda m: m["id"].lower())


def _as_float(value, default=None):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _usage_bucket(item) -> dict:
    """Normalize one usage bucket (today/total/model/day) from the MWAPI payload."""
    if not isinstance(item, dict):
        item = {}
    return {
        "requests": _as_int(item.get("requests")),
        "input_tokens": _as_int(item.get("input_tokens")),
        "output_tokens": _as_int(item.get("output_tokens")),
        "total_tokens": _as_int(item.get("total_tokens")),
        "cache_creation_tokens": _as_int(item.get("cache_creation_tokens", item.get("cache_write_tokens"))),
        "cache_read_tokens": _as_int(item.get("cache_read_tokens")),
        "cost": _as_float(item.get("cost"), 0.0),
        "actual_cost": _as_float(item.get("actual_cost"), 0.0),
    }


def parse_usage_data(payload: dict) -> dict:
    """Parse and normalize usage and quota data from MWAPI."""
    if not isinstance(payload, dict):
        return {}

    quota = payload.get("quota") if isinstance(payload.get("quota"), dict) else {}
    usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else {}
    usage_total = usage.get("total") if isinstance(usage.get("total"), dict) else {}
    usage_today = usage.get("today") if isinstance(usage.get("today"), dict) else {}

    limit = _as_float(quota.get("limit"))
    used = _as_float(quota.get("used"))
    if used is None:
        used = _as_float(usage_total.get("actual_cost"), _as_float(usage_total.get("cost")))

    remaining = _as_float(quota.get("remaining"))
    if remaining is None:
        remaining = _as_float(payload.get("remaining"))

    if limit is not None and limit > 0:
        if used is None and remaining is not None:
            used = max(0.0, limit - remaining)
        elif remaining is None and used is not None:
            remaining = max(0.0, limit - used)

    used_pct = None
    rem_pct = None
    if limit is not None and limit > 0:
        if used is not None:
            used_pct = min(100.0, max(0.0, (used / limit) * 100.0))
        if remaining is not None:
            rem_pct = min(100.0, max(0.0, (remaining / limit) * 100.0))

    today = _usage_bucket(usage_today)
    total = _usage_bucket(usage_total)

    models = []
    for item in payload.get("model_stats") or []:
        if not isinstance(item, dict):
            continue
        model_id = item.get("model")
        if not isinstance(model_id, str) or not model_id.strip():
            continue
        bucket = _usage_bucket(item)
        bucket["model"] = model_id.strip()
        bucket["account_cost"] = _as_float(item.get("account_cost"), bucket["cost"])
        models.append(bucket)
    models.sort(key=lambda m: (m["actual_cost"], m["cost"]), reverse=True)

    daily = []
    for item in payload.get("daily_usage") or []:
        if not isinstance(item, dict):
            continue
        bucket = _usage_bucket(item)
        bucket["date"] = str(item.get("date") or "")
        daily.append(bucket)
    daily.sort(key=lambda d: d["date"], reverse=True)

    unit = quota.get("unit") or payload.get("unit") or "USD"

    return {
        "limit": limit,
        "used": used,
        "remaining": remaining,
        "used_pct": used_pct,
        "rem_pct": rem_pct,
        "unit": unit,
        "status": payload.get("status", "active"),
        "mode": payload.get("mode", ""),
        "valid": payload.get("isValid", True),
        "expires_at": payload.get("expires_at") or "",
        "today": today,
        "total": total,
        "models": models,
        "daily": daily,
        "rpm": _as_int(usage.get("rpm")),
        "tpm": _as_int(usage.get("tpm")),
        "average_duration_ms": _as_float(usage.get("average_duration_ms"), 0.0),
        # Backward-compatible flat fields.
        "total_requests": total["requests"],
        "today_requests": today["requests"],
        "total_tokens": total["total_tokens"],
        "today_tokens": today["total_tokens"],
        "today_cost": today["actual_cost"] or today["cost"],
        "total_cost": total["actual_cost"] or total["cost"],
        "raw": payload,
    }


def fetch_usage(api_key: str, timeout: int = 20) -> dict:
    """Fetch quota and usage statistics from MWAPI."""
    if not api_key or not api_key.strip():
        raise ValueError("API-ключ MWAPI не указан.")

    request = urllib.request.Request(
        API_USAGE_URL,
        headers={
            "Authorization": f"Bearer {api_key.strip()}",
            "User-Agent": "Antigravity-Hub",
            "Accept": "application/json",
        },
    )

    try:
        raw_data = _request_with_fallback(request, timeout=timeout)
        payload = json.loads(raw_data.decode("utf-8"))
    except urllib.error.HTTPError as error:
        if error.code == 401:
            raise ValueError("MWAPI отклонил API-ключ (401). Проверьте ключ в кабинете https://api.mwapi.dev/dashboard.") from None
        if error.code == 403:
            raise ValueError("MWAPI вернул 403: доступ запрещён. Проверьте права токена в MWAPI.") from None
        if error.code == 429:
            raise ValueError("MWAPI вернул 429: превышен лимит запросов.") from None
        raise ValueError(f"MWAPI вернул HTTP {error.code} при получении лимитов.") from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise ValueError("Не удалось подключиться к https://api.mwapi.dev для проверки лимитов.") from None
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise ValueError("MWAPI вернул некорректный ответ данных о лимитах.") from None

    return parse_usage_data(payload)


def save_api_key(api_key: str):
    record = deepseek_storage.protect_secret(SECRET_PURPOSE, {"apiKey": api_key.strip()})
    deepseek_storage.atomic_write(SECRET_FILE, json.dumps(record))


def load_api_key() -> str:
    if not SECRET_FILE.exists():
        return ""
    try:
        record = json.loads(SECRET_FILE.read_text(encoding="utf-8"))
        return deepseek_storage.unprotect_secret(record, SECRET_PURPOSE)["apiKey"]
    except Exception:
        return ""


def save_dashboard_token(access_token: str):
    """Store the user-supplied dashboard JWT (access_token) used only to read balance."""
    record = deepseek_storage.protect_secret(TOKEN_SECRET_PURPOSE, {"accessToken": access_token.strip()})
    deepseek_storage.atomic_write(TOKEN_SECRET_FILE, json.dumps(record))


def load_dashboard_token() -> str:
    if not TOKEN_SECRET_FILE.exists():
        return ""
    try:
        record = json.loads(TOKEN_SECRET_FILE.read_text(encoding="utf-8"))
        return deepseek_storage.unprotect_secret(record, TOKEN_SECRET_PURPOSE)["accessToken"]
    except Exception:
        return ""


def clear_dashboard_token():
    TOKEN_SECRET_FILE.unlink(missing_ok=True)


def fetch_balance(access_token: str, timeout: int = 20) -> dict:
    """Fetch account balance/spend from the MWAPI dashboard using a user-supplied JWT.

    The gateway sk- API key cannot be used for this: MWAPI exposes balance only
    through the panel's session-authenticated profile endpoint, not the gateway
    API-key auth. The access_token must be copied manually by the user from the
    dashboard (e.g. DevTools Network tab after logging in), because the login
    endpoint itself requires solving a Cloudflare Turnstile challenge that the
    Hub cannot complete programmatically.
    """
    if not access_token or not access_token.strip():
        raise ValueError("Токен панели MWAPI не указан.")

    request = urllib.request.Request(
        PROFILE_URL,
        headers={
            "Authorization": f"Bearer {access_token.strip()}",
            "User-Agent": "Antigravity-Hub",
            "Accept": "application/json",
        },
    )

    try:
        raw_data = _request_with_fallback(request, timeout=timeout)
        payload = json.loads(raw_data.decode("utf-8"))
    except urllib.error.HTTPError as error:
        if error.code in (401, 403):
            raise ValueError("Токен панели MWAPI недействителен или истёк. Войдите в кабинет заново и скопируйте новый токен.") from None
        if error.code == 429:
            raise ValueError("MWAPI вернул 429: слишком много запросов к панели.") from None
        raise ValueError(f"MWAPI вернул HTTP {error.code} при запросе баланса.") from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise ValueError("Не удалось подключиться к https://api.mwapi.dev. Проверьте подключение к интернету.") from None
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise ValueError("MWAPI вернул некорректный ответ при запросе баланса.") from None

    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        raise ValueError("MWAPI вернул ответ без данных профиля.")

    def _as_float(value):
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0

    return {
        "balance": _as_float(data.get("balance")),
        "frozen_balance": _as_float(data.get("frozen_balance")),
        "total_recharged": _as_float(data.get("total_recharged")),
        "email": data.get("email") or "",
    }


def sync_opencode_credential(api_key: str):
    """Import the key through OpenCode CLI so OpenCode credential store is updated."""
    cli = openai_manager.find_opencode_cli()
    if not cli:
        return
    credential = [{
        "id": "cred_mwapi_hub",
        "integrationID": PROVIDER_ID,
        "label": "MWAPI (Cloud Code)",
        "active": True,
        "value": {"type": "key", "key": api_key.strip()},
    }]
    try:
        subprocess.run(
            [cli, "auth", "import"],
            input=json.dumps(credential),
            capture_output=True,
            text=True,
            timeout=15,
        )
    except Exception:
        pass


def configure_models(models: list[dict], api_key: str = "", config_dir=None):
    """Configure MWAPI provider with selected models in OpenCode."""
    config_path = deepseek_config.config_path(Path(config_dir) if config_dir else CONFIG_DIR)
    original = config_path.read_text(encoding="utf-8-sig") if config_path.exists() else "{}\n"
    data = deepseek_config.parse_config(original)

    updated = original
    configured_models = {}
    for model in models:
        configured_models[model["id"]] = {
            "name": model["name"],
            "limit": {"context": model["context"], "output": model["output"]},
        }

    provider_options = {"baseURL": API_BASE_URL}
    effective_key = api_key.strip() or load_api_key()
    if effective_key:
        provider_options["apiKey"] = effective_key

    updated = deepseek_config.set_property(updated, ("provider", PROVIDER_ID), {
        "npm": "@ai-sdk/openai-compatible",
        "name": "MWAPI (Cloud Code)",
        "options": provider_options,
        "models": configured_models,
    })

    if "$schema" not in data:
        updated = deepseek_config.set_property(updated, ("$schema",), "https://opencode.ai/config.json")

    config_path.parent.mkdir(parents=True, exist_ok=True)
    deepseek_storage.atomic_write(config_path, updated)


def disconnect(config_dir=None):
    """Remove MWAPI configuration and stored key."""
    cli = openai_manager.find_opencode_cli()
    if cli:
        try:
            subprocess.run([cli, "auth", "logout", PROVIDER_ID], capture_output=True, timeout=15)
        except Exception:
            pass

    config_path = deepseek_config.config_path(Path(config_dir) if config_dir else CONFIG_DIR)
    if config_path.exists():
        original = config_path.read_text(encoding="utf-8-sig")
        data = deepseek_config.parse_config(original)
        providers = data.get("provider", {})
        if isinstance(providers, dict) and PROVIDER_ID in providers:
            new_providers = {k: v for k, v in providers.items() if k != PROVIDER_ID}
            updated = deepseek_config.set_property(original, ("provider",), new_providers)
            deepseek_storage.atomic_write(config_path, updated)

    SECRET_FILE.unlink(missing_ok=True)
    TOKEN_SECRET_FILE.unlink(missing_ok=True)
