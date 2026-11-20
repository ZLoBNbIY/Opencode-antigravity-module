"""NVIDIA hosted NIM catalog and OpenCode Desktop configuration."""

import json
import re
import urllib.error
import urllib.request

import hub_paths
import jsonc_config
import secure_storage

BASE_URL = "https://integrate.api.nvidia.com/v1"
PROVIDER_ID = "nvidia-nim"
PROVIDER_PATH = ("providers", PROVIDER_ID)
KEY_FILE = hub_paths.HUB_ROOT / "opencode-secrets" / "nvidia-nim.key"
CONFIG_DIR = hub_paths.OPENCODE_CONFIG_DIR
MODEL_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]*/[A-Za-z0-9][A-Za-z0-9_.:/-]{0,200}")
NON_CHAT = re.compile(r"(?:^|[/._-])(?:embed\w*|rerank\w*|nemoguard|detector|whisper)(?:$|[/._-])|content-safety|safety-guard")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _validate_key(key):
    if not isinstance(key, str) or not re.fullmatch(r"nvapi-[A-Za-z0-9_.-]{1,250}", key):
        raise ValueError("Введите API-ключ NVIDIA (nvapi-…).")
    return key


def load_key():
    try:
        return _validate_key(KEY_FILE.read_text(encoding="utf-8").strip())
    except FileNotFoundError:
        return ""


def _opener():
    """Build an opener that honours the per-provider Hub route (like ChatGPT)."""
    handlers = [_NoRedirect()]
    try:
        import provider_proxy
        proxy_url = provider_proxy.proxy_url_for_hub_requests()
        handlers.append(urllib.request.ProxyHandler({"http": proxy_url, "https": proxy_url}))
    except Exception:
        # The catalog should still be reachable when the dispatcher is down.
        pass
    return urllib.request.build_opener(*handlers)


def _request(path, key, payload=None):
    request = urllib.request.Request(
        BASE_URL + path,
        data=json.dumps(payload).encode("utf-8") if payload is not None else None,
        headers={"Authorization": "Bearer " + _validate_key(key), "Content-Type": "application/json"},
    )
    try:
        with _opener().open(request, timeout=25) as response:
            return json.loads(response.read(2 * 1024 * 1024))
    except urllib.error.HTTPError as error:
        messages = {
            401: "Ключ отклонён (401). Проверьте ключ NVIDIA.",
            403: "Нет доступа (403). Проверьте ключ и доступ к выбранной модели.",
            404: "Ресурс или модель не найдены (404). Обновите каталог NVIDIA.",
            429: "NVIDIA ограничила частоту запросов (429). Попробуйте позже.",
        }
        raise ValueError(messages.get(error.code, f"Ошибка NVIDIA: HTTP {error.code}.")) from None
    except (OSError, TimeoutError):
        raise ValueError("Не удалось подключиться к API NVIDIA. Проверьте сеть.") from None
    except (ValueError, UnicodeError):
        raise ValueError("NVIDIA вернула некорректный ответ.") from None


def fetch_models(key):
    payload = _request("/models", key)
    rows = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        raise ValueError("NVIDIA вернула некорректный каталог моделей.")
    models = set()
    for row in rows:
        model_id = row.get("id") if isinstance(row, dict) else None
        if isinstance(model_id, str) and MODEL_ID.fullmatch(model_id) and not NON_CHAT.search(model_id.lower()):
            models.add(model_id)
    return sorted(models)


def probe_model(key, model_id):
    if not MODEL_ID.fullmatch(model_id):
        raise ValueError("Выберите модель NVIDIA.")
    result = _request("/chat/completions", key, {
        "model": model_id, "messages": [{"role": "user", "content": "Reply with OK."}],
        "max_tokens": 32, "stream": False,
    })
    if not isinstance(result, dict) or not result.get("choices"):
        raise ValueError("NVIDIA не вернула результат генерации.")


def _config():
    path = jsonc_config.config_path(CONFIG_DIR)
    try:
        original = path.read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        original = None
    try:
        data = jsonc_config.parse_config(original if original is not None else "{}")
    except ValueError:
        raise ValueError("Конфигурация OpenCode повреждена или содержит повторяющиеся поля.") from None
    for section in PROVIDER_PATH[0], "provider":
        if not isinstance(data.get(section, {}), dict):
            raise ValueError("Некорректный раздел провайдеров в конфигурации OpenCode.")
    return path, original, data


def _key_reference():
    return "{file:" + KEY_FILE.resolve().as_posix() + "}"


def _owns(provider):
    settings = provider.get("settings") if isinstance(provider, dict) else None
    return isinstance(settings, dict) and settings.get("apiKey") == _key_reference()


def state():
    _, _, data = _config()
    provider = data.get("providers", {}).get(PROVIDER_ID)
    has_key = KEY_FILE.is_file()
    models = provider.get("models") if _owns(provider) else None
    selected = list(models) if isinstance(models, dict) else []
    return {"hasKey": has_key, "connected": has_key and bool(selected),
            "selectedModels": selected}


def configure(key, model_ids):
    _validate_key(key)
    if not model_ids or not all(isinstance(m, str) and MODEL_ID.fullmatch(m) for m in model_ids):
        raise ValueError("Выберите модели из каталога NVIDIA.")
    path, original, data = _config()
    providers = data.get("providers", {})
    if (PROVIDER_ID in providers and not _owns(providers[PROVIDER_ID])
            or PROVIDER_ID in data.get("provider", {})):
        raise ValueError("В OpenCode уже есть другой провайдер nvidia-nim. Он оставлен без изменений.")
    updated = jsonc_config.set_property(original if original is not None else "{}\n", PROVIDER_PATH, {
        "name": "NVIDIA NIM",
        "package": "@opencode/ai/providers/openai-compatible",
        "settings": {"baseURL": BASE_URL, "apiKey": _key_reference()},
        "compatibility": {"maxTokensField": "max_tokens", "streamUsage": False},
        "models": {model_id: {"name": model_id, "capabilities": {"input": ["text"]}}
                   for model_id in model_ids},
    })
    if "$schema" not in data:
        updated = jsonc_config.set_property(updated, ("$schema",), "https://opencode.ai/config.json")

    # OpenCode reads the separate private file, not a key embedded in JSONC.
    # Restore the previous key if the config cannot be committed.
    old_key = KEY_FILE.read_text(encoding="utf-8") if KEY_FILE.exists() else None
    secure_storage.atomic_write(KEY_FILE, key)
    try:
        secure_storage.atomic_write(path, updated)
    except OSError:
        if old_key is None:
            KEY_FILE.unlink(missing_ok=True)
        else:
            secure_storage.atomic_write(KEY_FILE, old_key)
        raise


def disconnect():
    path, original, data = _config()
    provider = data.get("providers", {}).get(PROVIDER_ID)
    if original is not None and _owns(provider):
        secure_storage.atomic_write(path, jsonc_config.remove_property(original, PROVIDER_PATH))
    KEY_FILE.unlink(missing_ok=True)
