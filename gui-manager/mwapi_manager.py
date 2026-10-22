"""MWAPI (Cloud Code / CCS) integration for Antigravity Hub."""
import json
from pathlib import Path
import re
import socket
import subprocess
import urllib.error
import urllib.request

import deepseek_storage
import deepseek_config
import openai_manager


API_BASE_URL = "https://api.mwapi.dev/v1"
API_MODELS_URL = "https://api.mwapi.dev/v1/models"
PROVIDER_ID = "mwapi"
SECRET_PURPOSE = "mwapi-api-key"
SECRET_FILE = Path.home() / ".local" / "share" / "antigravity-hub" / "mwapi.json"
CONFIG_DIR = Path.home() / ".config" / "opencode"
LOCAL_PROXY = "http://127.0.0.1:51180"


def _request_with_fallback(request, timeout=20):
    """Try direct request first; fall back to local Hub tunnel if available."""
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read()
    except (urllib.error.URLError, TimeoutError, OSError) as direct_err:
        try:
            with socket.create_connection(("127.0.0.1", 51180), timeout=1):
                pass
            opener = urllib.request.build_opener(
                urllib.request.ProxyHandler({"http": LOCAL_PROXY, "https": LOCAL_PROXY})
            )
            with opener.open(request, timeout=timeout) as response:
                return response.read()
        except Exception:
            raise direct_err


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
