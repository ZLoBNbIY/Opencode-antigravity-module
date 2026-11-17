"""TokenLavka OpenAI-compatible API-key provider for Antigravity Hub.

The key is an ``sk-`` token issued by tokenlavka.com.  It is stored encrypted
in the Hub's secure directory and mirrored into OpenCode's credential store.
The provider descriptor written to ``opencode.json`` follows the official
OpenCode guide: ``@ai-sdk/openai-compatible`` + ``https://tokenlavka.com/v1``.
"""
import json
from pathlib import Path
import subprocess
import urllib.error
import urllib.request

import secure_storage
import jsonc_config
import openai_manager


PROVIDER_ID = "tokenlavka"
BASE_URL = "https://tokenlavka.com/v1"
MODELS_URL = f"{BASE_URL}/models"
SECRET_PURPOSE = "tokenlavka-api-key"
DEFAULT_MODEL = "gpt-6-luna"
try:
    import hub_paths
    SECRET_FILE = hub_paths.TOKENLAVKA_SECRET_FILE
except Exception:
    SECRET_FILE = Path.home() / ".local" / "share" / "antigravity-hub" / "tokenlavka.json"
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
    record = secure_storage.protect_secret(SECRET_PURPOSE, {"apiKey": api_key})
    secure_storage.atomic_write(SECRET_FILE, json.dumps(record))


def load_api_key():
    if not SECRET_FILE.exists():
        return ""
    try:
        record = json.loads(SECRET_FILE.read_text(encoding="utf-8"))
        return secure_storage.unprotect_secret(record, SECRET_PURPOSE)["apiKey"]
    except Exception:
        return ""


def test_connection(api_key, timeout=20):
    """Validate the key against GET /v1/models. Returns (ok, message)."""
    if not api_key or not api_key.strip().startswith("sk-"):
        return False, "Ключ tokenlavka должен начинаться с sk-"
    request = urllib.request.Request(
        MODELS_URL,
        headers={"Authorization": f"Bearer {api_key}", "User-Agent": "Antigravity-Hub"},
    )
    try:
        with _opener().open(request, timeout=timeout) as response:
            json.loads(response.read().decode("utf-8"))
        return True, "Ключ tokenlavka принят"
    except urllib.error.HTTPError as error:
        if error.code == 401:
            return False, "TokenLavka отклонила ключ (401). Проверьте, что он скопирован целиком."
        if error.code == 402:
            return False, "TokenLavka: insufficient balance (402). Пополните ключ."
        if error.code == 429:
            return False, "TokenLavka: слишком частые запросы (429). Повторите через несколько секунд."
        return False, f"TokenLavka вернула HTTP {error.code}"
    except (urllib.error.URLError, TimeoutError, OSError):
        return False, "Не удалось подключиться к TokenLavka. Проверьте интернет и маршрут."
    except (json.JSONDecodeError, UnicodeDecodeError):
        return False, "TokenLavka вернула некорректный ответ каталога моделей."


def sync_opencode_credential(api_key):
    """Import the key through OpenCode CLI so Desktop's credential store is updated."""
    cli = openai_manager.find_opencode_cli()
    if not cli:
        raise ValueError("Не найден OpenCode CLI. Запустите/установите OpenCode и повторите подключение.")
    credential = [{
        "id": "cred_tokenlavka_hub",
        "integrationID": PROVIDER_ID,
        "label": "TokenLavka (Antigravity Hub)",
        "active": True,
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
    secure_storage.atomic_write(config_path, updated)
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
    result = subprocess.run([cli, "auth", "logout", PROVIDER_ID], capture_output=True, timeout=15)
    if result.returncode != 0:
        raise ValueError("OpenCode не удалил сохранённые учётные данные. Ключ Hub оставлен без изменений.")
    config_path = jsonc_config.config_path(CONFIG_DIR)
    if config_path.exists():
        original = config_path.read_text(encoding="utf-8-sig")
        try:
            data = jsonc_config.parse_config(original)
            providers = data.get("provider", {})
            if PROVIDER_ID in providers:
                updated = jsonc_config.set_property(
                    original, ("provider", PROVIDER_ID, "models"), {}
                )
                secure_storage.atomic_write(config_path, updated)
        except Exception:
            pass
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
    }
