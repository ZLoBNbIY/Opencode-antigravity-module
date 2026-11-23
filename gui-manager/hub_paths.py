"""
Hub Paths & Centralized Storage Manager.
Consolidates all Antigravity Hub data, configs, binaries, browser profiles,
and logs into a single isolated directory: %APPDATA%/AntigravityHub (or ~/.config/AntigravityHub).
"""

from __future__ import annotations

import os
import re
import shutil
import sys
from pathlib import Path
from typing import Dict, Any
from jsonc_config import parse_config
from secure_storage import atomic_write_bytes, regular_file_stat


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


def get_opencode_config_dir() -> Path:
    """Resolve the active directory without creating or migrating anything.

    Keep ~/.config/opencode as the default on Windows as well as POSIX.
    Roaming AppData's old plugin account storage is not a config override.
    """
    override = Path(os.environ.get("OPENCODE_CONFIG_DIR", ""))
    if override.is_absolute():
        return override
    xdg = Path(os.environ.get("XDG_CONFIG_HOME", ""))
    return (xdg if xdg.is_absolute() else Path.home() / ".config") / "opencode"


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
    _dir.mkdir(mode=0o700, parents=True, exist_ok=True)

# Central file paths
HUB_CONFIG_FILE = CONFIG_DIR / "antigravity.json"
GEMINI_DOMAINS_FILE = CONFIG_DIR / "gemini_domains.json"

OPENAI_ACCOUNTS_FILE = ACCOUNTS_DIR / "openai-accounts.json"
XPIKI_CONFIG_FILE = ACCOUNTS_DIR / "xpiki.json"

OPENROUTER_SECRET_FILE = SECURE_DIR / "openrouter.json"
TOKENLAVKA_SECRET_FILE = SECURE_DIR / "tokenlavka.json"
TOKENLAVKA_CONFIG_FILE = ACCOUNTS_DIR / "tokenlavka.json"

VLESS_RUNTIME_DIR = VLESS_DIR
CLAUDE_PROFILE_DIR = BROWSER_DIR / "claude_profile"

# Shared OpenCode config directory (only what OpenCode itself needs)
OPENCODE_CONFIG_DIR = get_opencode_config_dir()
OPENCODE_CONFIG_FILE = OPENCODE_CONFIG_DIR / "opencode.json"
OPENCODE_SHARED_ANTIGRAVITY_CONFIG = OPENCODE_CONFIG_DIR / "antigravity.json"


def _file_stamp(info):
    # On Windows stat and fstat can expose different creation/change times.
    return info.st_dev, info.st_ino, info.st_mtime_ns, info.st_ctime_ns if os.name != "nt" else None, info.st_size


def _path_stamp(path):
    try:
        regular_file_stat(path)
        return _file_stamp(path.stat())
    except FileNotFoundError:
        return None


def _read_mirror(path):
    stamp = _path_stamp(path)
    if stamp is None:
        return None
    with path.open("rb") as stream:
        if _file_stamp(os.fstat(stream.fileno())) != stamp:
            raise OSError("Config changed before it could be read")
        content = stream.read()
        if _file_stamp(os.fstat(stream.fileno())) != stamp:
            raise OSError("Config changed while it was being read")
    return stamp, content, parse_config(content.decode("utf-8-sig"), jsonc=False)


def read_mirrored_antigravity_config(central=None, mirror=None) -> dict | None:
    """Read the newest valid object, favoring Hub on ties. Never writes.

    Invalid or unavailable copies don't mask a valid peer. If neither can be
    loaded, return None so callers can distinguish that from an empty object.
    """
    central = HUB_CONFIG_FILE if central is None else central
    mirror = OPENCODE_SHARED_ANTIGRAVITY_CONFIG if mirror is None else mirror
    candidates = []
    for path in (central, mirror):
        try:
            snapshot = _read_mirror(path)
        except (OSError, ValueError, RecursionError):
            continue
        if snapshot is not None:
            candidates.append(snapshot)
    newest = max(candidates, key=lambda item: item[0][2], default=None)
    return newest[2] if newest else None


def sync_shared_antigravity_config():
    """Seed a missing mirror or sync clearly newer valid settings at startup.

    Neither corrupt nor inaccessible files are considered missing. Leave those
    and equal-timestamp conflicts for explicit repair. Only the two configured
    settings paths participate; neither is a secret store.
    """
    central, mirror = HUB_CONFIG_FILE, OPENCODE_SHARED_ANTIGRAVITY_CONFIG
    if central == mirror:
        return
    try:
        left, right = _read_mirror(central), _read_mirror(mirror)
        if left is None and right is None:
            return
        if left and right and (left[1] == right[1] or left[0][2] == right[0][2]):
            return
        if _path_stamp(central) != (left[0] if left else None):
            return
        if _path_stamp(mirror) != (right[0] if right else None):
            return
        # This recheck catches changes during the read, not all possible races
        # with external writers. Both configured parent paths must be trusted.
        if right is None or (left is not None and left[0][2] > right[0][2]):
            atomic_write_bytes(mirror, left[1], private_parent=False)
        else:
            atomic_write_bytes(central, right[1])
    except (OSError, ValueError, RecursionError) as exc:
        print(f"[Hub Paths] Config sync skipped: {type(exc).__name__}")


def ensure_auto_update_disabled(paths=None) -> dict:
    """Pin the antigravity plugin's self-updater off in every config copy.

    The plugin reads ``auto_update`` from antigravity.json (default true in
    upstream releases). An unattended plugin update replaces the bundles this
    Hub patches, so the fix silently disappears and Google requests start
    returning 429 again. Keep the setting explicit in both the central config
    and the OpenCode mirror. JSONC comments and key order are preserved: the
    value is patched textually rather than by parsing and reserializing.
    """
    targets = list(paths) if paths is not None else [HUB_CONFIG_FILE, OPENCODE_SHARED_ANTIGRAVITY_CONFIG]
    updated: list[str] = []
    unchanged: list[str] = []
    failed: list[str] = []
    for path in dict.fromkeys(targets):
        try:
            if not path.is_file() or path.is_symlink():
                continue
            raw = path.read_bytes()
            text = raw.decode("utf-8-sig")
            if re.search(r'"auto_update"\s*:\s*false\b', text):
                unchanged.append(str(path))
                continue
            if re.search(r'"auto_update"\s*:', text):
                patched = re.sub(r'("auto_update"\s*:\s*)(?:true|false)\b', r"\1false", text, count=1)
            else:
                open_brace = text.find("{")
                if open_brace < 0:
                    failed.append(str(path))
                    continue
                patched = (text[:open_brace + 1] + ' "auto_update": false,'
                           + text[open_brace + 1:])
            if patched == text:
                unchanged.append(str(path))
                continue
            content = patched.encode("utf-8")
            if raw.startswith(b"\xef\xbb\xbf"):
                content = b"\xef\xbb\xbf" + content
            atomic_write_bytes(path, content, private_parent=False)
            updated.append(str(path))
        except (OSError, UnicodeError, ValueError):
            failed.append(str(path))
    return {
        "updated": updated,
        "unchanged": unchanged,
        "failed": failed,
        "ok": not failed,
        "message": ("Автообновление плагина отключено." if updated else
                    "Автообновление плагина уже отключено." if unchanged and not failed else
                    "Не удалось зафиксировать auto_update: false в конфиге."),
    }


def migrate_legacy_locations():
    """Compatibility entry point for startup; only sync shared settings.

    Leave legacy credentials, account files and browser sessions in place for
    explicit recovery. Never copy or delete them here. The disposable Gemini
    cache can be rebuilt; legacy executables are not adopted.
    """
    sync_shared_antigravity_config()
    ensure_auto_update_disabled()


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
            shutil.rmtree(BROWSER_DIR)
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
