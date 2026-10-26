"""OpenCode configuration manager for Antigravity Hub.

Ensures that critical OpenCode configuration settings (such as the free built-in
model for session titles: 'opencode/big-pickle') are always properly configured
and never reset or overwritten.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

TITLE_MODEL = "opencode/big-pickle"
CONFIG_DIR = Path.home() / ".config" / "opencode"


def get_opencode_config_path(config_dir: Optional[Path] = None) -> Path:
    """Returns the path to opencode.json or opencode.jsonc."""
    cd = config_dir or CONFIG_DIR
    jsonc_path = cd / "opencode.jsonc"
    json_path = cd / "opencode.json"
    if jsonc_path.exists() and not json_path.exists():
        return jsonc_path
    return json_path


def _parse_config_text(raw: str) -> Dict[str, Any]:
    """Parses JSON or JSONC text safely."""
    try:
        from deepseek_config import jsonc_text
        cleaned = jsonc_text(raw)
    except Exception:
        cleaned = raw
    data = json.loads(cleaned)
    if not isinstance(data, dict):
        raise ValueError("Конфигурация OpenCode должна быть JSON-объектом")
    return data


def check_session_title_config(config_path: Optional[Path] = None) -> Tuple[bool, str]:
    """Checks whether the session title model is properly set to 'opencode/big-pickle'.

    Returns (is_valid, message).
    """
    path = config_path or get_opencode_config_path()
    if not path.exists():
        return False, f"Файл конфигурации не найден: {path}"

    try:
        raw = path.read_text(encoding="utf-8-sig")
        data = _parse_config_text(raw)

        small_model = data.get("small_model")
        agent_title = data.get("agent")
        agents_title = data.get("agents")

        agent_model = agent_title.get("title", {}).get("model") if isinstance(agent_title, dict) and isinstance(agent_title.get("title"), dict) else None
        agents_model = agents_title.get("title", {}).get("model") if isinstance(agents_title, dict) and isinstance(agents_title.get("title"), dict) else None

        valid = (small_model == TITLE_MODEL) and (agent_model == TITLE_MODEL) and (agents_model == TITLE_MODEL)
        if valid:
            return True, f"Настройка активна: {TITLE_MODEL}"

        details = []
        if small_model != TITLE_MODEL:
            details.append(f"small_model={small_model}")
        if agents_model != TITLE_MODEL:
            details.append(f"agents.title={agents_model}")
        if agent_model != TITLE_MODEL:
            details.append(f"agent.title={agent_model}")

        return False, f"Некорректная настройка: {', '.join(details)}"
    except Exception as e:
        return False, f"Ошибка проверки конфигурации: {e}"


def ensure_session_title_config(config_path: Optional[Path] = None) -> Tuple[bool, str]:
    """Verifies and automatically fixes the session title model in OpenCode config.

    Sets:
      - small_model: 'opencode/big-pickle'
      - agent.title.model: 'opencode/big-pickle'
      - agents.title.model: 'opencode/big-pickle'

    Returns (modified, status_message).
    """
    path = config_path or get_opencode_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    path_existed = path.exists()
    data: Dict[str, Any] = {}
    if path_existed:
        try:
            raw = path.read_text(encoding="utf-8-sig")
            data = _parse_config_text(raw)
        except Exception as e:
            print(f"[OpenCode Config] Ошибка чтения {path}: {e}")
            data = {}
    else:
        # Load template if available
        template_file = Path(__file__).resolve().parent.parent / "config-templates" / "opencode.json"
        if template_file.exists():
            try:
                data = json.loads(template_file.read_text(encoding="utf-8"))
            except Exception:
                pass
        if not data:
            data = {
                "$schema": "https://opencode.ai/config.json",
                "model": "google/antigravity-gemini-3.8-flash",
                "plugin": ["@cortexkit/opencode-antigravity-auth@latest"],
                "provider": {"google": {"options": {"apiKey": "antigravity"}}},
            }

    # Verify if fix is needed
    small_model = data.get("small_model")
    agent_title = data.get("agent")
    agents_title = data.get("agents")

    agent_model = agent_title.get("title", {}).get("model") if isinstance(agent_title, dict) and isinstance(agent_title.get("title"), dict) else None
    agents_model = agents_title.get("title", {}).get("model") if isinstance(agents_title, dict) and isinstance(agents_title.get("title"), dict) else None

    if path_existed and small_model == TITLE_MODEL and agent_model == TITLE_MODEL and agents_model == TITLE_MODEL:
        return False, f"Конфигурация уже корректна ({TITLE_MODEL})"

    # Apply fixes
    data["small_model"] = TITLE_MODEL

    if "agent" not in data or not isinstance(data["agent"], dict):
        data["agent"] = {}
    if "title" not in data["agent"] or not isinstance(data["agent"]["title"], dict):
        data["agent"]["title"] = {}
    data["agent"]["title"]["model"] = TITLE_MODEL

    if "agents" not in data or not isinstance(data["agents"], dict):
        data["agents"] = {}
    if "title" not in data["agents"] or not isinstance(data["agents"]["title"], dict):
        data["agents"]["title"] = {}
    data["agents"]["title"]["model"] = TITLE_MODEL

    content = json.dumps(data, indent=4, ensure_ascii=False)
    try:
        try:
            import deepseek_storage
            deepseek_storage.atomic_write(path, content)
        except Exception:
            path.write_text(content, encoding="utf-8")

        msg = f"Успешно установлена бесплатная модель подписи сессий: {TITLE_MODEL}"
        print(f"[OpenCode Config] {msg}")
        return True, msg
    except Exception as e:
        err = f"Ошибка записи конфигурации {path}: {e}"
        print(f"[OpenCode Config] {err}")
        return False, err
