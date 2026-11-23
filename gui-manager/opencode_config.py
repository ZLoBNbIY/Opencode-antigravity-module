"""Read and repair the OpenCode session title model without replacing the config."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import jsonc_config
import hub_paths
from secure_storage import atomic_write_bytes


TITLE_MODEL = "opencode/big-pickle"
CONFIG_DIR = hub_paths.OPENCODE_CONFIG_DIR
NATIVE_TITLE_KEY = ("agents", "title", "model")
LEGACY_TITLE_KEY = ("agent", "title", "model")
LEGACY_SMALL_KEY = ("small_model",)


def get_opencode_config_path(config_dir: Path | None = None) -> Path:
    """Find the global config, or raise if both JSON and JSONC exist."""
    return jsonc_config.config_path(config_dir if config_dir is not None else CONFIG_DIR)


def _resolve_config_path(config_path: Path | None) -> Path:
    if config_path is None:
        return get_opencode_config_path()
    if config_path.name in ("opencode.json", "opencode.jsonc"):
        get_opencode_config_path(config_path.parent)  # Refuse the same ambiguity for explicit paths.
    return config_path


def _parse_config_text(raw: str) -> dict:
    return jsonc_config.parse_config(raw)


def _get(data: dict, keys: tuple[str, ...]):
    value = data
    for key in keys:
        if not isinstance(value, dict):
            raise ValueError(f"Поле {'.'.join(keys[:-1])} должно быть JSON-объектом")
        if key not in value:
            return None
        value = value[key]
    return value


def _title_settings(data: dict) -> tuple[tuple[str, ...], object]:
    """Choose the write key and effective model; V2 overrides legacy values."""
    native = _get(data, NATIVE_TITLE_KEY)
    if isinstance(native, str) and native:
        return NATIVE_TITLE_KEY, native
    legacy_title = _get(data, LEGACY_TITLE_KEY)
    legacy_key = LEGACY_TITLE_KEY if isinstance(legacy_title, str) and legacy_title else LEGACY_SMALL_KEY
    legacy_value = _get(data, legacy_key)
    if not any(key in data for key in ("agents", "plugins", "providers")) and any(
        key in data for key in ("agent", "plugin", "small_model")
    ):
        # Repair existing V1-style files without writing unsupported V2 keys.
        return legacy_key, legacy_value
    return NATIVE_TITLE_KEY, legacy_value if native is None else native


def check_session_title_config(config_path: Path | None = None) -> tuple[bool, str]:
    """Return (configured, message) for the effective title model."""
    try:
        path = _resolve_config_path(config_path)
        if not path.exists():
            return False, f"Файл конфигурации не найден: {path}"
        data = _parse_config_text(path.read_bytes().decode("utf-8"))
        model = _title_settings(data)[1]
        if model == TITLE_MODEL:
            return True, f"Настройка активна: {TITLE_MODEL}"
        return False, f"Некорректная настройка модели подписи сессий; требуется {TITLE_MODEL}."
    except (OSError, ValueError) as exc:
        return False, f"Ошибка проверки конфигурации: {exc}"


def _new_config() -> dict:
    root = Path(sys._MEIPASS) if getattr(sys, "frozen", False) else Path(__file__).resolve().parent.parent
    try:
        return _parse_config_text((root / "config-templates" / "opencode.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {
            "$schema": "https://opencode.ai/config.json",
            "model": "google/antigravity-gemini-3.8-flash",
            "plugins": ["@cortexkit/opencode-antigravity-auth@3.0.0"],
            "providers": {"google": {"settings": {"apiKey": "antigravity"}}},
        }


def ensure_plugin_pin(version: str, config_path: Path | None = None) -> tuple[bool, str]:
    """Pin the Antigravity auth plugin to a Hub-verified version.

    The plugin's updater rewrites ``@latest``/explicit pins in opencode.json;
    pinning the exact version keeps OpenCode loading the bundle the Hub knows
    how to patch. Only the plugin specifier is touched, so comments and other
    provider settings survive.
    """
    if not re.fullmatch(r"(?:0|[1-9][0-9]*)(?:\.(?:0|[1-9][0-9]*)){2}", version or ""):
        return False, f"Некорректная версия плагина: {version}"
    try:
        path = _resolve_config_path(config_path)
        if not path.exists():
            return False, f"Файл конфигурации не найден: {path}"
        raw = path.read_bytes().decode("utf-8")
        pinned = f"@cortexkit/opencode-antigravity-auth@{version}"
        pattern = re.compile(r'"@cortexkit/opencode-antigravity-auth(?:@[^"\s]*)?"')
        matches = list(pattern.finditer(raw))
        if not matches:
            return False, "Запись плагина Antigravity не найдена в конфиге OpenCode."
        content = pattern.sub(lambda _: json.dumps(pinned), raw)
        if content == raw:
            return False, f"Плагин уже закреплён на {version}."
        atomic_write_bytes(path, content.encode("utf-8"), private_parent=False)
        return True, f"Плагин Antigravity закреплён на версии {version}. Перезапустите OpenCode."
    except (OSError, ValueError) as exc:
        return False, f"Ошибка закрепления версии плагина: {exc}"


def ensure_session_title_config(config_path: Path | None = None) -> tuple[bool, str]:
    """Set the session title model, returning (modified, status message)."""
    try:
        path = _resolve_config_path(config_path)
        exists = path.exists()
        raw = path.read_bytes().decode("utf-8") if exists else json.dumps(
            _new_config(), indent=2, ensure_ascii=False,
        ) + "\n"
        data = _parse_config_text(raw)
        key, model = _title_settings(data)
        if exists and model == TITLE_MODEL:
            return False, f"Конфигурация уже корректна ({TITLE_MODEL})"
        crlf = "\r\n" in raw and "\n" not in raw.replace("\r\n", "")
        content = jsonc_config.set_property(raw.replace("\r\n", "\n") if crlf else raw, key, TITLE_MODEL)
        if crlf:
            content = content.replace("\n", "\r\n")
    except (OSError, ValueError) as exc:
        return False, f"Ошибка чтения конфигурации: {exc}"

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_bytes(path, content.encode("utf-8"), private_parent=False)
    except OSError as exc:
        return False, f"Ошибка записи конфигурации {path}: {exc}"
    return True, f"Успешно установлена бесплатная модель подписи сессий: {TITLE_MODEL}"
