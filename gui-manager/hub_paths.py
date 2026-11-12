"""
Hub Paths & Centralized Storage Manager.
Consolidates all Antigravity Hub data, configs, binaries, browser profiles,
and logs into a single isolated directory: %APPDATA%/AntigravityHub (or ~/.config/AntigravityHub).
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path
from typing import Dict, Any


def get_hub_data_dir() -> Path:
    """Returns the single central root directory for all Antigravity Hub data."""
    override = os.environ.get("ANTIGRAVITY_HUB_DATA_DIR")
    if override:
        p = Path(override)
        p.mkdir(parents=True, exist_ok=True)
        return p

    appdata = os.environ.get("APPDATA")
    if appdata and sys.platform == "win32":
        base = Path(appdata) / "AntigravityHub"
    else:
        base = Path.home() / ".config" / "AntigravityHub"

    base.mkdir(parents=True, exist_ok=True)
    return base


HUB_ROOT = get_hub_data_dir()

# Subdirectories inside the single central root
CONFIG_DIR = HUB_ROOT / "config"
ACCOUNTS_DIR = HUB_ROOT / "accounts"
SECURE_DIR = HUB_ROOT / "secure"
BIN_DIR = HUB_ROOT / "bin"
VLESS_DIR = HUB_ROOT / "vless"
BROWSER_DIR = HUB_ROOT / "browser_profiles"
LOG_DIR = HUB_ROOT / "logs"

for _dir in (CONFIG_DIR, ACCOUNTS_DIR, SECURE_DIR, BIN_DIR, VLESS_DIR, BROWSER_DIR, LOG_DIR):
    _dir.mkdir(parents=True, exist_ok=True)

# Central file paths
HUB_CONFIG_FILE = CONFIG_DIR / "antigravity.json"
GEMINI_DOMAINS_FILE = CONFIG_DIR / "gemini_domains.json"

OPENAI_ACCOUNTS_FILE = ACCOUNTS_DIR / "openai-accounts.json"
XPIKI_CONFIG_FILE = ACCOUNTS_DIR / "xpiki.json"

OPENROUTER_SECRET_FILE = SECURE_DIR / "openrouter.json"

VLESS_RUNTIME_DIR = VLESS_DIR
CLAUDE_PROFILE_DIR = BROWSER_DIR / "claude_profile"

# Shared OpenCode config directory (only what OpenCode itself needs)
OPENCODE_CONFIG_DIR = Path.home() / ".config" / "opencode"
OPENCODE_CONFIG_FILE = OPENCODE_CONFIG_DIR / "opencode.json"
OPENCODE_SHARED_ANTIGRAVITY_CONFIG = OPENCODE_CONFIG_DIR / "antigravity.json"


def sync_shared_antigravity_config():
    """Keeps ~/.config/opencode/antigravity.json in sync with Hub central config."""
    try:
        if HUB_CONFIG_FILE.exists():
            OPENCODE_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            content = HUB_CONFIG_FILE.read_bytes()
            OPENCODE_SHARED_ANTIGRAVITY_CONFIG.write_bytes(content)
        elif OPENCODE_SHARED_ANTIGRAVITY_CONFIG.exists():
            content = OPENCODE_SHARED_ANTIGRAVITY_CONFIG.read_bytes()
            HUB_CONFIG_FILE.write_bytes(content)
    except Exception as e:
        print(f"[Hub Paths] Config sync notice: {e}")


def migrate_legacy_locations():
    """
    Seamlessly migrates scattered files from older versions into %APPDATA%/AntigravityHub.
    Safe and idempotent: runs once, never overwrites newer files.
    """
    legacy_opencode_dir = Path.home() / ".config" / "opencode"
    legacy_share_dir = Path.home() / ".local" / "share" / "antigravity-hub"

    # 1. Configs & Accounts
    pairs = [
        (legacy_opencode_dir / "antigravity.json", HUB_CONFIG_FILE),
        (legacy_opencode_dir / "openai-accounts.json", OPENAI_ACCOUNTS_FILE),
        (legacy_opencode_dir / "xpiki.json", XPIKI_CONFIG_FILE),
        (legacy_opencode_dir / "gemini_domains.json", GEMINI_DOMAINS_FILE),
        (legacy_share_dir / "openrouter.json", OPENROUTER_SECRET_FILE),
    ]

    for old_path, new_path in pairs:
        try:
            if old_path.exists() and not new_path.exists():
                shutil.copy2(old_path, new_path)
        except Exception:
            pass

    # 2. Browser profiles (Claude)
    legacy_claude = legacy_opencode_dir / "claude_profile"
    if legacy_claude.exists() and not CLAUDE_PROFILE_DIR.exists():
        try:
            shutil.copytree(legacy_claude, CLAUDE_PROFILE_DIR)
        except Exception:
            pass

    # 3. Binaries (sing-box, xray)
    for old_bin in (legacy_opencode_dir / "bin", Path(__file__).resolve().parent / "bin"):
        if old_bin.exists():
            for item in old_bin.glob("*"):
                target = BIN_DIR / item.name
                if not target.exists() and item.is_file():
                    try:
                        shutil.copy2(item, target)
                    except Exception:
                        pass

    # 4. Sync mirrored config for OpenCode plugin compatibility
    sync_shared_antigravity_config()


# Storage statistics & Cleanup helpers
def _dir_size(path: Path) -> int:
    if not path.exists():
        return 0
    total = 0
    try:
        if path.is_file():
            return path.stat().st_size
        for entry in path.rglob("*"):
            if entry.is_file():
                total += entry.stat().st_size
    except Exception:
        pass
    return total


def _format_size(size_bytes: int) -> str:
    if size_bytes < 1024:
        return f"{size_bytes} Б"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} КБ"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} МБ"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024):.2f} ГБ"


def get_storage_stats() -> Dict[str, Any]:
    """Returns disk usage breakdown of the central storage directory."""
    root = get_hub_data_dir()
    bin_size = _dir_size(BIN_DIR)
    browser_size = _dir_size(BROWSER_DIR)
    log_size = _dir_size(LOG_DIR) + _dir_size(VLESS_DIR / "core.log")
    config_size = _dir_size(CONFIG_DIR) + _dir_size(ACCOUNTS_DIR) + _dir_size(SECURE_DIR)
    total_size = _dir_size(root)

    return {
        "root_path": str(root),
        "bin_size_str": _format_size(bin_size),
        "browser_size_str": _format_size(browser_size),
        "log_size_str": _format_size(log_size),
        "config_size_str": _format_size(config_size),
        "total_size_str": _format_size(total_size),
        "bin_size": bin_size,
        "browser_size": browser_size,
        "log_size": log_size,
        "total_size": total_size,
    }


def clean_logs_and_cache() -> Dict[str, Any]:
    """Cleans temporary logs, VLESS log and cached rule lists."""
    deleted_bytes = 0
    try:
        core_log = VLESS_DIR / "core.log"
        if core_log.exists():
            deleted_bytes += core_log.stat().st_size
            core_log.unlink(missing_ok=True)

        for log_f in LOG_DIR.glob("*"):
            if log_f.is_file():
                deleted_bytes += log_f.stat().st_size
                log_f.unlink(missing_ok=True)

        if GEMINI_DOMAINS_FILE.exists():
            deleted_bytes += GEMINI_DOMAINS_FILE.stat().st_size
            GEMINI_DOMAINS_FILE.unlink(missing_ok=True)

        return {"ok": True, "message": f"Очищено {_format_size(deleted_bytes)} логов и кэша"}
    except Exception as e:
        return {"ok": False, "message": f"Ошибка очистки: {e}"}


def clean_browser_profiles() -> Dict[str, Any]:
    """Removes stored browser profiles (e.g. Claude browser session)."""
    deleted_bytes = _dir_size(BROWSER_DIR)
    try:
        if BROWSER_DIR.exists():
            shutil.rmtree(BROWSER_DIR, ignore_errors=True)
            BROWSER_DIR.mkdir(parents=True, exist_ok=True)
        return {"ok": True, "message": f"Профили браузера удалены (освобождено {_format_size(deleted_bytes)})"}
    except Exception as e:
        return {"ok": False, "message": f"Ошибка очистки профилей: {e}"}


def open_data_folder():
    """Opens %APPDATA%/AntigravityHub in Windows File Explorer."""
    root = get_hub_data_dir()
    if root.exists() and sys.platform == "win32":
        os.startfile(root)
        return True
    return False
