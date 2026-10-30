"""OpenRouter free-model integration for Antigravity Hub."""
import json
from pathlib import Path
import subprocess
import urllib.error
import urllib.request

import deepseek_storage
import deepseek_config
import openai_manager


API_MODELS_URL = "https://openrouter.ai/api/v1/models"
API_KEY_URL = "https://openrouter.ai/api/v1/key"
PROVIDER_ID = "openrouter-free"
SECRET_PURPOSE = "openrouter-api-key"
SECRET_FILE = Path.home() / ".local" / "share" / "antigravity-hub" / "openrouter.json"
CONFIG_DIR = Path.home() / ".config" / "opencode"
LOCAL_PROXY = "http://127.0.0.1:51180"


def _openrouter_opener():
    """Route model-catalog requests through the per-provider dispatcher."""
    import provider_proxy
    proxy_url = provider_proxy.proxy_url_for_hub_requests()
    return urllib.request.build_opener(urllib.request.ProxyHandler({"http": proxy_url, "https": proxy_url}))


def _is_free(value):
    try:
        return float(value) == 0
    except (TypeError, ValueError):
        return False


def fetch_free_models(api_key, timeout=20):
    """Return all zero-priced text-in/text-out models in OpenRouter's catalog."""
    key_request = urllib.request.Request(
        API_KEY_URL,
        headers={"Authorization": f"Bearer {api_key}", "User-Agent": "Antigravity-Hub"},
    )
    request = urllib.request.Request(
        API_MODELS_URL,
        headers={"Authorization": f"Bearer {api_key}", "User-Agent": "Antigravity-Hub"},
    )
    opener = _openrouter_opener()
    try:
        with opener.open(key_request, timeout=timeout) as response:
            json.loads(response.read().decode("utf-8"))
        with opener.open(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        if error.code == 401:
            raise ValueError("OpenRouter отклонил API-ключ (401). Проверьте его в настройках OpenRouter.") from None
        if error.code == 403:
            raise ValueError("OpenRouter вернул 403: проверьте доступ к сервису и разрешённость региона для этого API-ключа.") from None
        raise ValueError(f"OpenRouter вернул HTTP {error.code} при загрузке моделей.") from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise ValueError("Не удалось подключиться к OpenRouter. Проверьте интернет и прокси.") from None
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise ValueError("OpenRouter вернул некорректный ответ каталога моделей.") from None

    models = []
    for item in payload.get("data", []):
        model_id = item.get("id")
        if not isinstance(model_id, str):
            continue
        pricing = item.get("pricing") or {}
        if not (_is_free(pricing.get("prompt")) and _is_free(pricing.get("completion"))):
            continue
        modalities = (item.get("architecture") or {}).get("modality")
        if modalities:
            parts = str(modalities).lower().split("->", 1)
            if len(parts) != 2 or "text" not in parts[0] or parts[1] != "text":
                continue
        limit = item.get("context_length")
        top_provider = item.get("top_provider") or {}
        output = top_provider.get("max_completion_tokens")
        models.append({
            "id": model_id,
            "name": item.get("name") or model_id,
            "context": limit if isinstance(limit, int) and limit > 0 else 32768,
            "output": output if isinstance(output, int) and output > 0 else 8192,
        })
    return sorted(models, key=lambda model: model["id"].lower())


def save_api_key(api_key):
    record = deepseek_storage.protect_secret(SECRET_PURPOSE, {"apiKey": api_key})
    deepseek_storage.atomic_write(SECRET_FILE, json.dumps(record))


def load_api_key():
    if not SECRET_FILE.exists():
        return ""
    try:
        record = json.loads(SECRET_FILE.read_text(encoding="utf-8"))
        return deepseek_storage.unprotect_secret(record, SECRET_PURPOSE)["apiKey"]
    except Exception:
        return ""


def sync_opencode_credential(api_key):
    """Import the key through OpenCode CLI so Desktop's credential store is updated."""
    cli = openai_manager.find_opencode_cli()
    if not cli:
        raise ValueError("Не найден OpenCode CLI. Запустите/установите OpenCode и повторите подключение.")
    credential = [{
        "id": "cred_openrouter_hub",
        "integrationID": PROVIDER_ID,
        "label": "OpenRouter (Antigravity Hub)",
        "active": True,
        # OpenCode 2.x uses the "key" credential variant (not legacy "api").
        "value": {"type": "key", "key": api_key},
    }]
    try:
        result = subprocess.run(
            [cli, "auth", "import"],
            input=json.dumps(credential), capture_output=True, text=True, timeout=15,
        )
        if result.returncode != 0:
            # Never expose CLI output: it may include credential data.
            raise ValueError("OpenCode не принял API-ключ. Перезапустите OpenCode и попробуйте снова.")
    except subprocess.TimeoutExpired:
        raise ValueError("OpenCode CLI не ответил вовремя при сохранении ключа.") from None


def configure_models(models, config_dir=None):
    """Create a separate OpenRouter Free provider containing only selected IDs."""
    config_path = deepseek_config.config_path(Path(config_dir) if config_dir else CONFIG_DIR)
    original = config_path.read_text(encoding="utf-8-sig") if config_path.exists() else "{}\n"
    data = deepseek_config.parse_config(original)
    providers = data.get("provider", {})
    if not isinstance(providers, dict):
        raise ValueError("Поле provider в конфигурации OpenCode должно быть объектом.")
    existing = providers.get(PROVIDER_ID, {})
    if existing and not isinstance(existing, dict):
        raise ValueError("Конфигурация провайдера OpenRouter имеет неподдерживаемый формат.")

    updated = original
    configured_models = {}
    for model in models:
        model_config = {
            "name": model.get("name", model.get("id", "Model")),
            "limit": {
                "context": model.get("context") or model.get("limit", {}).get("context", 128000),
                "output": model.get("output") or model.get("limit", {}).get("output", 4096),
            },
        }
        configured_models[model["id"]] = model_config
    updated = deepseek_config.set_property(updated, ("provider", PROVIDER_ID), {
        "npm": "@ai-sdk/openai-compatible",
        "name": "OpenRouter Free",
        "options": {"baseURL": "https://openrouter.ai/api/v1"},
        "models": configured_models,
    })
    disabled = data.get("disabled_providers", [])
    if not isinstance(disabled, list):
        raise ValueError("Поле disabled_providers в конфигурации OpenCode должно быть списком.")
    if "openrouter" not in disabled:
        updated = deepseek_config.set_property(
            updated, ("disabled_providers",), [*disabled, "openrouter"],
        )
    if "$schema" not in data:
        updated = deepseek_config.set_property(updated, ("$schema",), "https://opencode.ai/config.json")
    config_path.parent.mkdir(parents=True, exist_ok=True)
    deepseek_storage.atomic_write(config_path, updated)


def disconnect():
    cli = openai_manager.find_opencode_cli()
    if not cli:
        raise ValueError("Не найден OpenCode CLI. Ключ Hub оставлен без изменений.")
    for provider_id in (PROVIDER_ID, "openrouter"):
        result = subprocess.run([cli, "auth", "logout", provider_id], capture_output=True, timeout=15)
        if result.returncode != 0:
            raise ValueError("OpenCode не удалил сохранённые учётные данные. Ключ Hub оставлен без изменений.")
    config_path = deepseek_config.config_path(CONFIG_DIR)
    if config_path.exists():
        original = config_path.read_text(encoding="utf-8-sig")
        data = deepseek_config.parse_config(original)
        disabled = data.get("disabled_providers", [])
        if isinstance(disabled, list) and "openrouter" in disabled:
            updated = deepseek_config.set_property(
                original, ("disabled_providers",), [item for item in disabled if item != "openrouter"],
            )
            deepseek_storage.atomic_write(config_path, updated)
    SECRET_FILE.unlink(missing_ok=True)
