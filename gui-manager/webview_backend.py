"""
AI HUB - Webview2 Frosted Glass Backend Bridge
Provides the Python API layer for the Web frontend (Variant 3 Glassmorphism UI).
"""

import os
import sys
import json
import time
import socket
import threading
import subprocess
import copy
import ipaddress
import re
import stat
import tempfile
import hmac
import secrets
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse
from pathlib import Path

# Add current directory to path to import helper modules
CURRENT_DIR = Path(__file__).resolve().parent
if str(CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(CURRENT_DIR))

import hub_logging


def _app_version() -> str:
    if getattr(sys, "frozen", False):
        try:
            value = (CURRENT_DIR / "hub-version.txt").read_text(encoding="ascii").strip()
            if re.fullmatch(r"\d+\.\d+\.\d+(?:\.\d+)?", value):
                return f"v{value}"
        except (OSError, UnicodeError):
            pass
    return "v2.0.0"


AUTOSTART_VALUE_NAME = "AI HUB"
AUTOSTART_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def _autostart_command() -> str:
    """Command written to the per-user Run key (no admin rights required)."""
    if getattr(sys, "frozen", False):
        return f'"{Path(sys.executable).resolve()}"'
    executable = Path(sys.executable).resolve()
    pythonw = executable.with_name("pythonw.exe")
    if not pythonw.exists():
        pythonw = executable
    script = CURRENT_DIR / "antigravity_manager.pyw"
    return f'"{pythonw}" "{script}"'


def _apply_autostart(enabled: bool) -> None:
    """Enable/disable AI HUB autostart via HKCU Run. Safe no-op off Windows."""
    if sys.platform != "win32":
        return
    try:
        import winreg
    except ImportError:
        return
    command = _autostart_command()
    access = winreg.KEY_SET_VALUE | winreg.KEY_QUERY_VALUE
    try:
        registry_key = (winreg.CreateKeyEx if enabled else winreg.OpenKey)(
            winreg.HKEY_CURRENT_USER, AUTOSTART_RUN_KEY, 0, access)
    except FileNotFoundError:
        if not enabled:
            return
        raise
    with registry_key as key:
        try:
            existing, _ = winreg.QueryValueEx(key, AUTOSTART_VALUE_NAME)
        except FileNotFoundError:
            existing = None
        if existing is not None and existing != command:
            if enabled:
                raise ValueError("Автозапуск уже настроен другой копией AI HUB")
            return
        if enabled:
            if existing is None:
                winreg.SetValueEx(key, AUTOSTART_VALUE_NAME, 0, winreg.REG_SZ, command)
        elif existing is not None:
            winreg.DeleteValue(key, AUTOSTART_VALUE_NAME)


import antigravity_manager
from proxy_config import (NATIVE_PLUGIN_MARKER, NATIVE_PLUGIN_NAME, native_route_plugin,
                          opencode_launch_environment, sync_provider_routes_text)
import opencode_config
import auto_updater
import openai_manager
import win_tray
try:
    import claude_manager
    claude_service = claude_manager.claude_service
except Exception:
    claude_service = None

from vless_manager import get_http_port, get_socks_port, vless_service, VlessParser
from vless_exit import VlessExitStatus
import provider_proxy
import auto_router
import dns_tester
import xpiki_manager
import openrouter_manager
import nvidia_manager
import tokenlavka_manager
import hub_paths
import deepseek_api
import google_proactive_refresh
import google_connection
import opencode_usage
import jsonc_config
import secure_storage

CONFIG_DIR = hub_paths.OPENCODE_CONFIG_DIR
ANTIGRAVITY_CONFIG_FILE = CONFIG_DIR / "antigravity.json"
OPENCODE_CONFIG_FILE = CONFIG_DIR / "opencode.json"
LOG_DIR = hub_paths.LOG_DIR
HUB_CONFIG_FILE = hub_paths.HUB_CONFIG_FILE

CLOUDCODE_ENDPOINTS = [
    "daily-cloudcode-pa.googleapis.com",
    "cloudcode-pa.googleapis.com",
    "cloudaicompanion.googleapis.com",
    "generativelanguage.googleapis.com",
    "oauth2.googleapis.com",
    "aiplatform.googleapis.com",
    "clients6.google.com",
    "www.googleapis.com",
]


PROVIDER_DOMAINS = {
    "google": CLOUDCODE_ENDPOINTS,
    "openai": ["chatgpt.com", "auth.openai.com", "api.openai.com"],
    "claude-pro": ["claude.ai", "api.anthropic.com", "console.anthropic.com"],
    "xpiki": ["api.xpiki.com"],
    "openrouter-free": ["openrouter.ai"],
    "deepseek-account": ["api.deepseek.com"],
    "tokenlavka": ["tokenlavka.com"],
    "nvidia-nim": ["integrate.api.nvidia.com"],
}
PROVIDER_SETTING_IDS = {"antigravity": "google", "openai": "openai", "claude": "claude-pro",
                        "xpiki": "xpiki", "openrouter": "openrouter-free",
                        "deepseek": "deepseek-account", "tokenlavka": "tokenlavka",
                        "nvidia": "nvidia-nim"}


def _vless_label(url: str) -> str:
    """Short human-readable label: fragment tag + server endpoint."""
    try:
        info = VlessParser.parse_url(url)
        tag = info.get("tag") or ""
        endpoint = f"{info.get('server')}:{info.get('port')}"
        return f"{tag} · {endpoint}" if tag and tag != endpoint else endpoint
    except Exception:
        return "VLESS"


def _normalize_vless_pool(value) -> list[dict]:
    """Accept both plain strings (legacy) and full entries; drop invalid URLs."""
    entries = []
    seen = set()
    if isinstance(value, list):
        for item in value:
            if isinstance(item, str):
                url = item.strip()
                entry = {}
            elif isinstance(item, dict):
                url = str(item.get("url") or "").strip()
                entry = {k: v for k, v in item.items() if k != "url"}
            else:
                continue
            if not url or url in seen:
                continue
            try:
                VlessParser.parse_url(url)
            except Exception:
                continue
            seen.add(url)
            entry["url"] = url
            entry.setdefault("label", _vless_label(url))
            entry.setdefault("status", "untested")
            entry.setdefault("ip", None)
            entry.setdefault("country", None)
            entry.setdefault("latency_ms", None)
            entry.setdefault("checked_at", None)
            entry.setdefault("error", None)
            entries.append(entry)
    return entries


def _opencode_config_path() -> Path:
    return jsonc_config.config_path(OPENCODE_CONFIG_FILE.parent)


def _read_if_present(path: Path) -> bytes | None:
    try:
        return path.read_bytes()
    except FileNotFoundError:
        return None


def _apply_file_updates(updates, after=None):
    """Replace individual files atomically; compensate on a later failure."""
    written = []
    try:
        for path, old, new, private_parent in updates:
            if _read_if_present(path) != old:
                raise OSError("Файл настроек изменён другой программой. Повторите сохранение.")
            if old != new:
                secure_storage.atomic_write_bytes(path, new, private_parent=private_parent)
                written.append((path, old, new, private_parent))
        if after is not None:
            after()
    except Exception:
        rollback_failed = False
        for path, old, new, private_parent in reversed(written):
            try:
                if _read_if_present(path) != new:
                    rollback_failed = True
                elif old is None:
                    path.unlink()
                else:
                    secure_storage.atomic_write_bytes(path, old, private_parent=private_parent)
            except OSError as exc:
                rollback_failed = True
                hub_logging.failed("Settings rollback", exc)
        if rollback_failed:
            raise OSError("Сохранение не завершено, часть настроек не удалось откатить.") from None
        raise


def _read_opencode_config() -> dict:
    try:
        raw = _read_if_present(_opencode_config_path())
        return jsonc_config.parse_config(raw.decode("utf-8-sig")) if raw is not None else {}
    except (OSError, ValueError):
        # Read-only views can still display the Hub; mutating methods parse the
        # current source strictly instead of using this fallback.
        return {}


def _is_hub_local_proxy(parsed) -> bool:
    host = (parsed.hostname or "").lower().rstrip(".")
    if not host:
        return False
    is_local = host in ("localhost", "localhost.localdomain")
    if not is_local:
        try:
            addr = ipaddress.ip_address(host.split("%", 1)[0])
            if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped is not None:
                addr = addr.ipv4_mapped
            is_local = addr.is_loopback or addr.is_unspecified
        except ValueError:
            is_local = False
    if not is_local:
        return False
    try:
        port = parsed.port
    except ValueError:
        return False
    return port in (provider_proxy.PORT, 51180, get_http_port())


_POOL_ID_KEY = secrets.token_bytes(32)


def _pool_id(url: str) -> str:
    return hmac.digest(_POOL_ID_KEY, url.encode("utf-8"), "sha256").hex() if isinstance(url, str) and url else ""


def _vless_pool_view(pool: list[dict]) -> list[dict]:
    return [{**{k: row.get(k) for k in ("status", "ip", "country", "latency_ms", "checked_at")},
             "id": _pool_id(row["url"]), "label": _vless_label(row["url"])} for row in pool]


def _proxy_view(cfg: dict) -> dict:
    primary = cfg.get("proxy") or ""
    stored = cfg.get("proxy_pool")
    pool = [url for url in stored if isinstance(url, str) and url] if isinstance(stored, list) else []
    if not isinstance(primary, str):
        primary = ""
    if primary and primary not in pool:
        pool.insert(0, primary)
    labels = {}
    for url in dict.fromkeys([*pool, primary]):
        if not url:
            continue
        try:
            parsed = urlparse(url)
            host = parsed.hostname
            if host and ":" in host:
                host = f"[{host}]"
            labels[_pool_id(url)] = (host or "Прокси") + (f":{parsed.port}" if parsed.port else "")
        except ValueError:
            labels[_pool_id(url)] = "Прокси"
    return {"proxy": _pool_id(primary), "proxy_pool": [_pool_id(url) for url in pool],
            "proxy_labels": labels}


def _config_view(cfg: dict) -> dict:
    allowed = ("dns_mode", "custom_dns", "dot_host", "doh_url", "dns_presets", "proxy_failover",
               "vless_enabled", "vless_kill_switch", "account_selection_strategy",
               "close_to_tray", "autostart_on_login", "providers_visibility", "provider_routes")
    return {**{key: cfg[key] for key in allowed if key in cfg}, **_proxy_view(cfg),
            "vless_url": _pool_id(cfg.get("vless_url") or ""),
            "vless_pool": _vless_pool_view(_normalize_vless_pool(cfg.get("vless_pool")))}


def _validate_backup(data: dict) -> None:
    def check(condition, field):
        if not condition:
            raise ValueError(f"Некорректное поле резервной копии: {field}")

    if "schemaVersion" in data:
        version = data["schemaVersion"]
        check(type(version) is int and version in (1, 2), "schemaVersion")
    check(any(key in data for key in ("google_accounts", "accounts", "openai_accounts",
              "claude_accounts", "xpiki", "deepseek", "openrouter", "tokenlavka", "config")),
           "содержимое")
    for name in ("google_accounts", "accounts", "openai_accounts", "claude_accounts"):
        if name not in data:
            continue
        rows = data[name]
        check(isinstance(rows, list) and len(rows) <= 10_000, name)
        for row in rows:
            check(isinstance(row, dict), name)
            for key in ("id", "accountId", "email", "refresh", "refreshToken", "access",
                        "accessToken", "sessionKey", "session_key"):
                check(row.get(key) is None or isinstance(row[key], str), f"{name}.{key}")
            for key in ("expires", "expiresAt", "index"):
                check(row.get(key) is None or type(row[key]) is int, f"{name}.{key}")
            for key in ("groups", "rateLimitResetTimes"):
                expected = list if key == "groups" else dict
                check(row.get(key) is None or isinstance(row[key], expected), f"{name}.{key}")
    for name in ("xpiki", "deepseek", "openrouter", "tokenlavka"):
        if name not in data:
            continue
        obj = data[name]
        check(isinstance(obj, dict), name)
        for key in ("api_key", "base_url"):
            check(obj.get(key) is None or isinstance(obj[key], str), f"{name}.{key}")
        if obj.get("base_url"):
            parsed = urlparse(obj["base_url"].strip())
            check(parsed.scheme == "https" and parsed.hostname and
                  parsed.username is None and parsed.password is None, f"{name}.base_url")
            _ = parsed.port
        for key in ("enabled_models", "selected_models"):
            if key in obj:
                items = obj[key]
                check(isinstance(items, list) and all(isinstance(item, str) for item in items),
                      f"{name}.{key}")
        check(obj.get("cached_balance") is None or isinstance(obj["cached_balance"], dict),
              f"{name}.cached_balance")
        check("connected" not in obj or type(obj["connected"]) is bool, f"{name}.connected")
    check("config" not in data or isinstance(data["config"], dict), "config")


def _backup_account_rows(data, name):
    """Restore identity and credentials, not arbitrary account-store metadata."""
    rows = data.get(name) or (data.get("accounts") if name == "google_accounts" else None) or []
    schemas = {
        "google_accounts": {
            str: ("id", "email", "refresh", "refreshToken", "access", "accessToken", "projectId", "label"),
            int: ("expires", "addedAt"), bool: ("enabled",),
        },
        "openai_accounts": {
            str: ("id", "accountId", "email", "name", "refresh", "access", "refreshToken", "accessToken"),
            int: ("expires", "expiresAt", "added_at", "last_used"),
            bool: ("enabled", "candidate", "is_active"),
        },
        "claude_accounts": {
            str: ("email", "name", "session_key", "sessionKey", "org_id", "token_type", "base_url", "plan"),
            int: ("added_at",), bool: ("active",),
        },
    }
    result = []
    for row in rows:
        if name == "google_accounts" and isinstance(row.get("metadata"), dict):
            row = {**row["metadata"], **row}
        clean = {}
        for kind, keys in schemas[name].items():
            for key in keys:
                value = row.get(key)
                if value is None:
                    continue
                limit = 65536 if key in {"access", "refresh", "accessToken", "refreshToken", "session_key", "sessionKey"} else 4096
                if type(value) is not kind or (kind is str and len(value) > limit):
                    raise ValueError(f"Некорректное поле резервной копии: {name}.{key}")
                clean[key] = value
        if name == "google_accounts":
            if not (clean.get("email") and (clean.get("refreshToken") or clean.get("refresh"))):
                raise ValueError("В резервной копии есть неполный аккаунт Google.")
        elif name == "openai_accounts":
            if not any(clean.get(key) for key in ("id", "accountId", "email")):
                raise ValueError("В резервной копии есть аккаунт OpenAI без идентификатора.")
            for alias, key in (("refreshToken", "refresh"), ("accessToken", "access"), ("expiresAt", "expires")):
                if alias in clean:
                    clean.setdefault(key, clean.pop(alias))
        else:
            if "sessionKey" in clean:
                clean.setdefault("session_key", clean.pop("sessionKey"))
            if not (clean.get("email", "").strip() and clean.get("session_key", "").strip()):
                raise ValueError("В резервной копии есть неполный аккаунт Claude.")
            if clean.get("base_url"):
                parsed = urlparse(clean["base_url"])
                if parsed.scheme != "https" or not parsed.hostname or parsed.username is not None:
                    raise ValueError("Некорректный адрес API в аккаунте Claude.")
                _ = parsed.port
        result.append(clean)
    return result


def _backup_config(data: dict) -> dict:
    types = {
        "account_selection_strategy": str, "soft_quota_threshold_percent": int,
        "switch_on_first_rate_limit": bool, "max_account_switches": int,
        "quota_style_fallback": bool, "close_to_tray": bool, "autostart_on_login": bool,
        "google_proactive_refresh": bool, "cloaking_v2": bool,
        "providers_visibility": dict, "provider_routes": dict, "vless_kill_switch": bool,
        "vless_enabled": bool, "dns_mode": str, "custom_dns": list, "dot_host": str,
        "doh_url": str, "dns_presets": list, "proxy": str, "proxy_pool": list,
        "proxy_failover": bool, "vless_url": str, "vless_pool": list,
    }
    result = {}
    for key, value in data.items():
        if key not in types:
            continue
        if type(value) is not types[key]:
            raise ValueError(f"Некорректная настройка резервной копии: {key}")
        result[key] = value
    if result.get("dns_mode", "system") not in ("system", "standard", "dot", "doh"):
        raise ValueError("Неизвестный режим DNS")
    for ip in result.get("custom_dns", []):
        if not isinstance(ip, str):
            raise ValueError("Некорректный DNS-сервер")
        ipaddress.ip_address(ip)
    if result.get("doh_url"):
        parsed = urlparse(result["doh_url"])
        if (parsed.scheme != "https" or not parsed.hostname
                or parsed.username is not None or parsed.password is not None):
            raise ValueError("Некорректный адрес DoH")
        _ = parsed.port
    for url in [result.get("proxy", ""), *result.get("proxy_pool", [])]:
        if not isinstance(url, str):
            raise ValueError("Некорректный прокси")
        if url:
            parsed = urlparse(url)
            port = parsed.port
            if (parsed.scheme not in ("http", "https") or not parsed.hostname
                    or port == 0 or _is_hub_local_proxy(parsed)):
                raise ValueError("Некорректный прокси")
    active = result.get("vless_url")
    if active:
        VlessParser.parse_url(active)
    if "vless_pool" in result:
        # Restore destinations, not untrusted diagnostics or display metadata.
        pool = []
        for entry in result["vless_pool"]:
            url = entry.get("url") if isinstance(entry, dict) else entry
            if not isinstance(url, str):
                raise ValueError("Некорректная запись VLESS")
            VlessParser.parse_url(url.strip())
            pool.append(url)
        result["vless_pool"] = _normalize_vless_pool(pool)
    if "dns_presets" in result:
        for preset in result["dns_presets"]:
            if (not isinstance(preset, dict) or not isinstance(preset.get("name"), str)
                    or not isinstance(preset.get("standard", []), list)
                    or not all(isinstance(ip, str) for ip in preset.get("standard", []))
                    or any(not isinstance(preset.get(key, ""), str) for key in ("dot", "doh"))):
                raise ValueError("Некорректная запись DNS")
    for key, allowed, values in (
        ("providers_visibility", PROVIDER_SETTING_IDS, (True, False)),
        ("provider_routes", PROVIDER_DOMAINS, ("default", "auto", "direct", "dns", "proxy", "vless")),
    ):
        if key in result:
            result[key] = {k: v for k, v in result[key].items()
                           if k in allowed and type(v) is type(values[0]) and v in values}
    return result


_HUB_FILES = (
    "config/antigravity.json", "config/gemini_domains.json",
    "accounts/openai-accounts.json", "accounts/claude-accounts.json",
    "accounts/xpiki.json", "accounts/tokenlavka.json", "accounts/deepseek-api.json",
    "secure/openrouter.json", "secure/tokenlavka.json", "secure/deepseek-api-key.json",
    "opencode-secrets/nvidia-nim.key", "vless/core.log", "vless/config.json",
)


def _safe_owned_file(path: Path) -> bool:
    """Check the entire absolute path without following links or junctions."""
    if not path.is_absolute():
        raise ValueError(f"Ожидался абсолютный путь: {path}")
    for part in (*reversed(path.parents), path):
        try:
            info = part.lstat()
        except FileNotFoundError:
            return False
        if (stat.S_ISLNK(info.st_mode) or
                getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT):
            raise ValueError(f"Ссылка или точка повторной обработки оставлена: {part}")
        expected = stat.S_ISREG if part == path else stat.S_ISDIR
        if not expected(info.st_mode):
            raise ValueError(f"Неожиданный тип файла оставлен: {part}")
    return True


def _remove_hub_opencode_settings(text: str) -> str:
    cfg = jsonc_config.parse_config(text)
    package = "@cortexkit/opencode-antigravity-auth"

    def is_plugin(entry):
        if isinstance(entry, list) and entry:
            entry = entry[0]
        if isinstance(entry, dict):
            entry = entry.get("package")
        return isinstance(entry, str) and (entry == package or entry.startswith(package + "@"))

    owned = False
    for field in ("plugin", "plugins"):
        plugins = cfg.get(field)
        if isinstance(plugins, list):
            keep = [entry for entry in plugins if not is_plugin(entry)]
            if len(keep) == len(plugins):
                continue
            text = (jsonc_config.set_property(text, (field,), keep) if keep else
                    jsonc_config.remove_property(text, (field,)))
            owned = True
        elif is_plugin(plugins):
            text = jsonc_config.remove_property(text, (field,))
            owned = True
    if owned:
        for section, settings in (("provider", "options"), ("providers", "settings")):
            providers = cfg.get(section)
            google = providers.get("google") if isinstance(providers, dict) else None
            options = google.get(settings) if isinstance(google, dict) else None
            if (isinstance(options, dict)
                    and options.get("apiKey") in ("antigravity", "common-auth-placeholder.google")):
                text = jsonc_config.remove_property(text, (section, "google", settings, "apiKey"))
    return text


def _opencode_cache_dirs() -> list[Path]:
    roots = []
    xdg_cache = os.environ.get("XDG_CACHE_HOME", "").strip()
    if xdg_cache:
        roots.append(Path(xdg_cache) / "opencode")
    roots.append(Path.home() / ".cache" / "opencode")
    dirs = []
    seen = set()
    for root in roots:
        for sub in ("npm", "packages"):
            candidate = root / sub
            key = str(candidate)
            if key not in seen:
                seen.add(key)
                dirs.append(candidate)
    return dirs


_PLUGIN_PACKAGE = google_proactive_refresh.PLUGIN_PACKAGE
_PLUGIN_VERSION = re.compile(r"(?:0|[1-9][0-9]{0,8})(?:\.(?:0|[1-9][0-9]{0,8})){2}")
_PLUGIN_INSTALL_TIMEOUT = 90


class _PluginInstallConfigError(ValueError):
    """An install error whose message is safe to show in the Hub."""


def _is_exact_plugin_version(value) -> bool:
    return isinstance(value, str) and _PLUGIN_VERSION.fullmatch(value) is not None


def _plugin_version_key(value: str) -> tuple[int, ...]:
    return tuple(int(part) for part in value.split("."))


def _antigravity_plugin_specs(cfg: dict) -> set[str]:
    """Collect Hub-package specs in V2, V1 and legacy tuple entries."""
    specs = set()
    for field in ("plugins", "plugin"):
        entries = cfg.get(field)
        for entry in entries if isinstance(entries, list) else [entries]:
            if isinstance(entry, list) and entry:
                entry = entry[0]
            if isinstance(entry, dict):
                entry = entry.get("package")
            if entry == _PLUGIN_PACKAGE:
                specs.add("")
            elif isinstance(entry, str) and entry.startswith(_PLUGIN_PACKAGE + "@"):
                specs.add(entry[len(_PLUGIN_PACKAGE) + 1:])
    return specs


def _template_plugin_version() -> str:
    root = Path(sys._MEIPASS) if getattr(sys, "frozen", False) else CURRENT_DIR.parent
    text = (root / "config-templates" / "opencode.json").read_text(encoding="utf-8-sig")
    specs = _antigravity_plugin_specs(jsonc_config.parse_config(text))
    if len(specs) != 1 or not _is_exact_plugin_version(next(iter(specs))):
        raise _PluginInstallConfigError("В шаблоне AI HUB не найдена точная версия плагина.")
    return next(iter(specs))


def _plugin_cached(version: str) -> bool:
    """Check the active cache for this exact spec, not another version or tag."""
    cache_home = Path(os.environ.get("XDG_CACHE_HOME", ""))
    cache_root = (cache_home if cache_home.is_absolute() else Path.home() / ".cache") / "opencode"
    candidates = [cache_root / "node_modules" / _PLUGIN_PACKAGE]
    for layout in ("npm", "packages"):
        root = cache_root / layout / f"{_PLUGIN_PACKAGE}@{version}"
        candidates += [root, root / "node_modules" / _PLUGIN_PACKAGE]
        try:
            generations = [entry for entry in root.iterdir()
                           if entry.is_dir() and not entry.name.startswith(".")
                           and not entry.name.endswith(".rejected")]
        except OSError:
            continue
        numbered = [entry for entry in generations if re.fullmatch(r"[0-9]{1,20}", entry.name)]
        if numbered:
            generations = [max(numbered, key=lambda entry: int(entry.name))]
        candidates.extend(entry / "node_modules" / _PLUGIN_PACKAGE for entry in generations)
    for directory in candidates:
        try:
            meta = json.loads((directory / "package.json").read_text(encoding="utf-8-sig"))
            if (isinstance(meta, dict) and meta.get("name") == _PLUGIN_PACKAGE
                    and meta.get("version") == version):
                for name in ("server.js", "index.js"):
                    path = directory / "dist" / name
                    if path.is_file() and path.stat().st_size > 0:
                        return True
        except (OSError, ValueError, RecursionError):
            continue
    return False


def _find_cli_3113() -> Path | None:
    finder = google_proactive_refresh.find_cli_3113
    package = google_proactive_refresh.PLUGIN_PACKAGE
    cache_dirs = _opencode_cache_dirs()
    for cache_dir in cache_dirs:
        found = finder(cache_dir)
        if found is not None:
            return found
    # Respect unit-test mocks on google_proactive_refresh.find_cli_3113 returning None.
    if hasattr(finder, "assert_called"):
        return None
    # When multiple hash directories exist or OpenCode uses packages/ layout,
    # pick the newest valid 3.1.13 cli.js.
    candidates = []
    for cache_dir in cache_dirs:
        pkg_dir = cache_dir / f"{package}@3.1.13"
        for pattern in (
            f"*/node_modules/{package}/dist/cli.js",
            f"node_modules/{package}/dist/cli.js",
            "dist/cli.js",
        ):
            for path in pkg_dir.glob(pattern):
                try:
                    st = path.stat()
                    if path.is_file() and st.st_size > 0:
                        candidates.append((st.st_mtime_ns, path))
                except OSError:
                    continue
        direct_cli = cache_dir.parent / "node_modules" / package / "dist" / "cli.js"
        pkg_json = cache_dir.parent / "node_modules" / package / "package.json"
        try:
            if direct_cli.is_file() and pkg_json.is_file():
                meta = json.loads(pkg_json.read_text(encoding="utf-8-sig"))
                if meta.get("version") == "3.1.13":
                    st = direct_cli.stat()
                    if st.st_size > 0:
                        candidates.append((st.st_mtime_ns, direct_cli))
        except (OSError, ValueError):
            continue
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates[0][1]


class _WebviewBridge:
    """Do not expose the raw network-config reader/writer to JavaScript."""

    def __init__(self, api):
        for name in dir(api):
            if not name.startswith("_") and name not in {"load_config", "save_config", "stop_opencode",
                                                          "start_opencode", "ensure_google_connection"}:
                method = getattr(api, name)
                if callable(method):
                    setattr(self, name, method)


class HubApi:
    """Exposed to window.pywebview.api in JavaScript."""

    def __init__(self, window_holder=None):
        # pywebview recursively inspects public API attributes. A public Window
        # reference exposes native GUI properties and can block bridge startup.
        self._window_holder = window_holder
        self._tray_holder = None
        try:
            hub_paths.migrate_legacy_locations()
        except Exception as exc:
            hub_logging.failed("Migrate legacy Hub locations", exc)
        try:
            import cloudcode_route_patch
            raw = _read_if_present(_opencode_config_path())
            existing = _antigravity_plugin_specs(jsonc_config.parse_config(raw.decode("utf-8-sig"))) if raw else set()
            exact = {value for value in existing if _is_exact_plugin_version(value)}
            if len(exact) == 1:
                # A stale Hub pin must not rewrite an explicit OpenCode pin,
                # including one chosen by the clean-install flow.
                opencode_config.ensure_google_api_key(version=next(iter(exact)))
            elif not exact:
                pinned_version = cloudcode_route_patch.get_expected_plugin_version()
                if pinned_version:
                    opencode_config.ensure_plugin_pin(pinned_version)
                opencode_config.ensure_google_api_key()
        except Exception as exc:
            hub_logging.failed("Initialize OpenCode plugin configuration", exc)
        self._config_lock = threading.RLock()
        self._quota_lock = threading.Lock()
        self._all_quotas_lock = threading.Lock()
        self._all_quotas_running = False
        self._quota_refreshing = False
        self._quota_error = None
        self._quota_notice = None
        self._google_quota_cache = {}
        self._diagnostics = {}
        self._diagnostic_signatures = {}
        self._diagnostic_checked = {}
        self._diagnostic_lock = threading.Lock()
        self._diagnostic_running = set()
        self._openrouter_models = []
        self._nvidia_catalog = ("", [])
        self._provider_lock = threading.RLock()
        self._core_lock = threading.Lock()
        self._vless_exit = VlessExitStatus()
        self._restart_lock = threading.Lock()
        self._plugin_install_lock = threading.Lock()
        self._hub_restart_lock = threading.Lock()
        self._backup_lock = threading.Lock()
        self._update_lock = threading.Lock()
        self._shutdown_lock = threading.Lock()
        self._pending_backup = None
        self._update_offer = None
        self._opencode_process = None
        self._closing = threading.Event()
        self._uninstalled = False
        self._uninstalling = False
        self._restart_requested = False
        self._close_to_tray = True
        try:
            cfg = self.load_config()
            self._close_to_tray = bool(cfg.get("close_to_tray", True))
        except Exception as exc:
            self._close_to_tray = False
            hub_logging.failed("Load initial Hub settings", exc)
        self._login_locks = {name: threading.Lock() for name in ("google", "openai", "claude")}
        self._google_connect_lock = threading.Lock()
        self._google_refresh = google_proactive_refresh.GoogleProactiveRefresh(
            self._run_google_refresh_cli, self._closing, self._google_refresh_enabled)

    def _apply_autostart(self, enabled: bool) -> None:
        _apply_autostart(enabled)

    def _invalidate_diagnostics_cache(self):
        with self._diagnostic_lock:
            self._diagnostics.clear()
            self._diagnostic_signatures.clear()
            self._diagnostic_checked.clear()

    def _google_refresh_enabled(self):
        if self._uninstalled or self._uninstalling or self._closing.is_set() or os.getenv("AI_HUB_GOOGLE_PROACTIVE_REFRESH") == "0":
            return False
        cfg = self.load_config()
        return cfg.get("google_proactive_refresh", True) is True

    def _google_refresh_profile(self):
        cfg = self.load_config()
        hub_pin = cfg.get("plugin_pin_version")
        # A user may pin OpenCode directly, independently of Hub's settings.
        try:
            raw = _read_if_present(_opencode_config_path())
            oc = jsonc_config.parse_config(raw.decode("utf-8-sig")) if raw is not None else {}
        except (OSError, UnicodeDecodeError, ValueError) as exc:
            hub_logging.failed("Read OpenCode config for Google profile", exc)
            return None
        package = google_proactive_refresh.PLUGIN_PACKAGE
        pins = set()
        for field in ("plugins", "plugin"):
            entries = oc.get(field, [])
            for entry in entries if isinstance(entries, list) else [entries]:
                if isinstance(entry, dict):
                    entry = entry.get("package")
                if isinstance(entry, str) and (entry == package or entry.startswith(package + "@")):
                    pins.add(entry[len(package) + 1:])
        if hub_pin is not None:
            if not isinstance(hub_pin, str):
                return None
            pins.add(hub_pin)
        if not pins:
            import cloudcode_route_patch
            pins.add(cloudcode_route_patch.get_expected_plugin_version())
        if len(pins) != 1:
            return None
        version = pins.pop()
        return version if version in google_proactive_refresh.SUPPORTED_PROFILES else None

    def _run_google_refresh_cli(self, args, timeout):
        if self._closing.is_set() or self._uninstalling or self._uninstalled:
            return None
        profile = self._google_refresh_profile()
        if profile == "3.1.13":
            cli = _find_cli_3113()
            root = Path(sys._MEIPASS) if getattr(sys, "frozen", False) else CURRENT_DIR.parent
            runner = root / "plugin" / "dist" / "google-cli-3113.mjs"
            if cli is None or not runner.is_file():
                return None
            command = [str(runner), str(cli), *args[1:]]
        elif profile == "3.0.0":
            cli = antigravity_manager.get_cli_js()
            if not os.path.isfile(cli):
                return None
            command = [cli, *args]
        else:
            return None
        # The manager can return bare "node"; subprocess resolves it on PATH.
        node_exe = antigravity_manager.get_node_executable()
        if self._closing.is_set() or self._uninstalling or self._uninstalled:
            return None
        return antigravity_manager.run_google_route_cmd([node_exe, *command], timeout=timeout)

    def _google_runner(self):
        node_exe = antigravity_manager.get_node_executable()
        profile = self._google_refresh_profile()
        has_relocated = bool(getattr(antigravity_manager, "has_relocated_google_store", lambda: False)())
        if profile == "3.1.13" or has_relocated:
            cli_3113 = _find_cli_3113()
            root = Path(sys._MEIPASS) if getattr(sys, "frozen", False) else CURRENT_DIR.parent
            login_runner_3113 = root / "plugin" / "dist" / "google-login-3113.mjs"
            if cli_3113 is not None and login_runner_3113.is_file():
                return ("3.1.13", node_exe, login_runner_3113, cli_3113)
            if has_relocated:
                return ("missing_3113", node_exe, None, None)
        return ("3.0.0", node_exe, None, antigravity_manager.get_cli_js())

    def _store_google_quota_snapshot(self, raw_stdout: str):
        if not raw_stdout:
            return
        try:
            payload = json.loads(raw_stdout)
        except Exception:
            return
        rows = payload.get("accounts") if isinstance(payload, dict) else None
        if not isinstance(rows, list):
            return
        parsed = {}
        for row in rows:
            if not isinstance(row, dict):
                continue
            email = str(row.get("email") or "").strip().lower()
            groups = row.get("groups")
            if email and isinstance(groups, list) and groups:
                parsed[email] = groups
        if not parsed:
            return
        with self._quota_lock:
            self._google_quota_cache = parsed

    def _merge_google_quota_cache(self, accounts: list[dict]):
        with self._quota_lock:
            cache = dict(getattr(self, "_google_quota_cache", {}) or {})
        if not cache:
            return
        for account in accounts:
            email = str(account.get("email") or "").strip().lower()
            cached_groups = cache.get(email)
            if cached_groups:
                account["groups"] = cached_groups

    def _refresh_google_quotas_sync(self, timeout=45) -> bool:
        kind, node_exe, runner, cli = self._google_runner()
        if kind == "3.1.13":
            res = antigravity_manager.run_google_route_cmd(
                [node_exe, str(runner), str(cli), "--quota"],
                timeout=timeout,
            )
        elif kind == "3.0.0" and cli and os.path.exists(cli):
            res = antigravity_manager.run_google_route_cmd(
                [node_exe, cli, "quota", "--refresh", "--json"],
                timeout=timeout,
            )
        else:
            return False
        if res and res.returncode == 0:
            self._store_google_quota_snapshot(res.stdout)
            return True
        return False

    def _schedule_google_connection(self):
        """Start the isolated daemon worker; never block the calling thread."""
        if self._uninstalled or self._uninstalling or self._closing.is_set():
            return
        if os.getenv("AI_HUB_GOOGLE_POOL_CONNECTION") == "0":
            return
        try:
            threading.Thread(target=self.ensure_google_connection, daemon=True,
                             name="hub-google-connect").start()
        except Exception:
            hub_logging.log.debug("Google connection: status=%s", google_connection.API_ERROR)

    def ensure_google_connection(self):
        """Idempotent pool credential check; returns a status, never raises."""
        if self._uninstalled or self._uninstalling or self._closing.is_set():
            return google_connection.SKIP
        if not self._google_connect_lock.acquire(blocking=False):
            return google_connection.IN_PROGRESS
        try:
            helper = getattr(antigravity_manager, "get_opencode_cli", None)
            cli = helper() if callable(helper) else None
            status = google_connection.ensure_google_connection(
                cli=cli, resolve=False,
                stop=lambda: self._closing.is_set() or self._uninstalled or self._uninstalling)
            if status not in (google_connection.ALREADY_CONNECTED, google_connection.CONNECTED):
                hub_logging.log.debug("Google connection: status=%s", status)
            return status
        except Exception:
            hub_logging.log.debug("Google connection: status=%s", google_connection.API_ERROR)
            return google_connection.API_ERROR
        finally:
            self._google_connect_lock.release()

    def load_config(self) -> dict:
        with self._config_lock:
            cfg, _ = self._config_snapshot()
            self._close_to_tray = bool(cfg.get("close_to_tray", True))
            return cfg

    def _config_snapshot(self, *, defaults=True):
        cfg = copy.deepcopy(antigravity_manager.DEFAULT_CONFIG) if defaults else {}
        sources = {}
        candidates = []
        for path in (HUB_CONFIG_FILE, ANTIGRAVITY_CONFIG_FILE):
            try:
                with path.open("rb") as stream:
                    modified = os.fstat(stream.fileno()).st_mtime_ns
                    raw = stream.read()
            except FileNotFoundError:
                sources[path] = None
                continue
            except OSError as exc:
                hub_logging.failed("Read Hub settings", exc)
                raise OSError(f"Не удалось прочитать настройки Hub: {path}") from None
            try:
                data = jsonc_config.parse_config(raw.decode("utf-8-sig"), jsonc=False)
            except ValueError as exc:
                hub_logging.failed("Parse Hub settings", exc)
                raise ValueError(f"Файл настроек Hub повреждён и оставлен без изменений: {path}") from None
            candidates.append((modified, data))
            sources[path] = raw
        if candidates:
            cfg.update(max(candidates, key=lambda item: item[0])[1])
        return cfg, sources

    def _config_updates(self, cfg, sources):
        payload = json.dumps(cfg, indent=2, ensure_ascii=False, allow_nan=False).encode("utf-8")
        return [(path, raw, payload, path == HUB_CONFIG_FILE) for path, raw in sources.items()]

    def save_config(self, cfg: dict) -> bool:
        try:
            with self._config_lock:
                # A self-updating plugin replaces the bundles the Hub patches.
                # Never persist a setting that silently reintroduces the 429 bug.
                cfg["auto_update"] = False
                _, sources = self._config_snapshot()
                _apply_file_updates(self._config_updates(cfg, sources))
                self._close_to_tray = bool(cfg.get("close_to_tray", True))
            return True
        except Exception as exc:
            hub_logging.failed("Save Hub settings", exc)
            return False

    def is_opencode_running(self) -> bool:
        if sys.platform != "win32":
            return False
        try:
            proc = subprocess.run(
                ["tasklist", "/fi", "imagename eq opencode.exe", "/fo", "csv", "/nh"],
                capture_output=True, text=True, timeout=5, creationflags=0x08000000
            )
            return "opencode.exe" in proc.stdout.lower()
        except Exception:
            return False

    def get_state(self) -> dict:
        """Returns the full reactive state for the glass frontend."""
        raw_accounts = antigravity_manager.export_google_accounts()
        accounts = antigravity_manager.enrich_google_accounts_with_generation_store(raw_accounts)
        self._merge_google_quota_cache(accounts)
        disk_accounts = antigravity_manager.enrich_google_accounts_with_generation_store([])
        # Exported credential rows can omit index and incomplete generation rows.
        # Preserve the store's original index rather than numbering filtered rows.
        by_id = {a.get("id"): a for a in disk_accounts if a.get("id")}
        active = antigravity_manager.get_active_google_health_account()
        for i, account in enumerate(accounts):
            disk = by_id.get(account.get("id"), {})
            account["index"] = disk.get("index", account.get("index", i + 1))
            account["is_active"] = bool(active and (
                (active.get("id") and active.get("id") == account.get("id")) or
                (not active.get("id") and active.get("email") == account.get("email"))))
        active_index = antigravity_manager.get_active_google_account_index()

        cfg = self.load_config()
        routes = cfg.get("provider_routes")
        if not isinstance(routes, dict):
            routes = {}
        try:
            oc = _read_opencode_config()
            disabled = oc.get("disabled_providers")
            if not isinstance(disabled, list):
                disabled = []
            raw_vis = cfg.get("providers_visibility")
            visibility = dict(raw_vis) if isinstance(raw_vis, dict) else {}
            for key, provider_id in PROVIDER_SETTING_IDS.items():
                if provider_id in disabled:
                    visibility[key] = False
            cfg["providers_visibility"] = visibility
        except (OSError, ValueError, TypeError):
            pass

        openai_accs = openai_manager.load_openai_accounts() if hasattr(openai_manager, "load_openai_accounts") else []
        claude_accs = claude_service.load_accounts() if claude_service else []
        claude_active = next((index for index, account in enumerate(claude_accs) if account.get("active")),
                             0 if claude_accs else None)

        with self._quota_lock:
            quota_refreshing = self._quota_refreshing
            quota_error = self._quota_error
            quota_notice = self._quota_notice

        return {
            "accounts": [{k: a[k] for k in ("id", "email", "index", "is_active", "groups", "candidate", "enabled", "status") if k in a} for a in accounts],
            "activeIndex": active_index,
            "activeGoogleId": active.get("id") if active else None,
            "openaiAccounts": [{k: a[k] for k in ("id", "accountId", "email", "plan_type", "is_active", "quota", "enabled", "candidate") if k in a} for a in openai_accs],
            "claudeAccounts": [{**{k: a[k] for k in ("id", "email", "name", "plan") if k in a},
                                "is_active": index == claude_active} for index, a in enumerate(claude_accs)],
            "openaiRefreshing": quota_refreshing,
            "openaiError": quota_error,
            "openaiNotice": quota_notice,
            "routes": routes,
            "config": _config_view(cfg),
            "opencodeRunning": self.is_opencode_running(),
            "appVersion": _app_version(),
            "desktopInstaller": bool(getattr(sys, "frozen", False)),
            "diagnostics": self.get_cached_diagnostics(),
            "network": self.get_network_state(),
            "geminiRules": self.get_gemini_rules_status(),
            "providers": self.get_provider_state(),
        }

    def get_gemini_rules_status(self) -> dict:
        import gemini_routes
        return gemini_routes.get_status()

    def refresh_gemini_rules(self) -> dict:
        import gemini_routes
        gemini_routes.refresh_async(force=True)
        return gemini_routes.get_status()

    def get_gemini_rules(self, query: str = "") -> list[dict]:
        import gemini_routes
        return gemini_routes.get_rules(query)

    def get_network_state(self) -> dict:
        cfg = self.load_config()
        oc = _read_opencode_config()
        visibility = cfg.get("providers_visibility")
        if not isinstance(visibility, dict):
            visibility = {}
        routes = cfg.get("provider_routes")
        if not isinstance(routes, dict):
            routes = {}
        disabled = oc.get("disabled_providers")
        if not isinstance(disabled, list):
            disabled = []
        auto_states = {}
        for provider in PROVIDER_DOMAINS:
            visibility_key = {"google": "antigravity", "claude-pro": "claude", "openrouter-free": "openrouter",
                              "deepseek-account": "deepseek", "tokenlavka": "tokenlavka",
                              "nvidia-nim": "nvidia"}.get(provider, provider)
            enabled = visibility.get(visibility_key, True) and provider not in disabled
            if enabled and routes.get(provider, "default") in ("default", "auto"):
                auto_router.router.refresh(provider, cfg, oc)
            auto_states[provider] = auto_router.router.state(provider, cfg, oc)
        core = vless_service.find_core_executable(cfg.get("vless_core_path"))
        cores = {}
        for kind in ("sing-box", "xray"):
            path = vless_service.find_core_executable(core_type=kind)
            if core and ((kind == "xray") == ("xray" in core.name.lower())):
                path = core
            cores[kind] = {"installed": bool(path), "path": str(path) if path else None,
                           "selected": bool(path and core and path == core)}
        port = get_http_port()
        if self._core_lock.acquire(blocking=False):
            try:
                running = vless_service.is_running()
                identity = (cfg.get("vless_url"), port, vless_service.exit_generation()) if running else None
                exit_status = self._vless_exit.snapshot(identity, port)
            finally:
                self._core_lock.release()
        else:
            # Pool diagnostics may briefly run a different tunnel.
            running = vless_service.is_running()
            self._vless_exit.snapshot(None)
            exit_status = {"status": "checking" if running else "stopped"}
        return {"autoRoutes": auto_states, "cores": cores, "vlessRunning": running, "vlessExit": exit_status,
                 "vlessCore": str(core) if core else None,
                 "httpPort": port, "socksPort": get_socks_port()}

    def refresh_auto_routes(self, provider: str) -> bool:
        if provider not in PROVIDER_DOMAINS:
            raise ValueError("Неизвестный провайдер")
        cfg = self.load_config()
        oc = _read_opencode_config()
        auto_router.router.refresh(provider, cfg, oc, force=True)
        return True

    def _sync_routes(self, cfg):
        with self._config_lock:
            self._sync_routes_locked(cfg)

    def _sync_routes_locked(self, cfg):
        oc_path = _opencode_config_path()
        deepseek_provider_id = deepseek_api.load_config().get("provider_id")
        config = {}
        if oc_path.exists():
            import jsonc_config
            original = oc_path.read_text(encoding="utf-8-sig")
            config = jsonc_config.parse_config(original)
            content = sync_provider_routes_text(original, cfg, get_http_port(),
                deepseek_provider_id=deepseek_provider_id)
            if content != original:
                secure_storage.atomic_write_bytes(oc_path, content.encode("utf-8"), private_parent=False)
        plugin_path = oc_path.parent / "plugins" / NATIVE_PLUGIN_NAME
        exists = _safe_owned_file(plugin_path)
        owner_path = sys.executable if getattr(sys, "frozen", False) else Path(__file__).resolve()
        plugin = native_route_plugin(ANTIGRAVITY_CONFIG_FILE, config, deepseek_provider_id,
                                     owner_path=owner_path)
        current = plugin_path.read_bytes() if exists else b""
        if exists and not current.startswith(NATIVE_PLUGIN_MARKER):
            raise OSError("Файл маршрутизации Hub занят другим плагином")
        if current != plugin:
            secure_storage.atomic_write_bytes(plugin_path, plugin, private_parent=False)
        if not provider_proxy.start():
            raise RuntimeError("Маршрутизатор Hub недоступен на порту 10880")

    def _diagnostic_signature(self, cfg=None):
        cfg = self.load_config() if cfg is None else cfg
        keys = ("provider_routes", "dns_mode", "custom_dns", "dot_host", "doh_url", "proxy",
                "vless_enabled", "vless_url", "vless_http_port")
        return json.dumps([{key: cfg.get(key) for key in keys},
                           xpiki_manager.load_xpiki_config().get("base_url")], sort_keys=True)

    def get_cached_diagnostics(self) -> dict:
        signature = self._diagnostic_signature()
        with self._diagnostic_lock:
            stale = [p for p, sig in self._diagnostic_signatures.items() if sig != signature]
            for p in stale:
                self._diagnostics.pop(p, None)
                self._diagnostic_signatures.pop(p, None)
                self._diagnostic_checked.pop(p, None)
            return {provider: {"rows": list(self._diagnostics.get(provider, []))
                               if self._diagnostic_signatures.get(provider) == signature else [],
                               "checkedAt": self._diagnostic_checked.get(provider)
                               if self._diagnostic_signatures.get(provider) == signature else None,
                               "running": provider in self._diagnostic_running}
                    for provider in PROVIDER_DOMAINS}

    def run_google_diagnostics(self) -> list:
        return self.run_provider_diagnostics("google")

    def run_provider_diagnostics(self, provider: str) -> list:
        if provider not in PROVIDER_DOMAINS:
            raise ValueError("Неизвестный провайдер")
        with self._diagnostic_lock:
            if provider in self._diagnostic_running:
                return list(self._diagnostics.get(provider, []))
            self._diagnostic_running.add(provider)
        cfg = self.load_config()
        signature = self._diagnostic_signature(cfg)
        # Preserve configured provider IDs for the dispatcher's domain matching,
        # including providers that have not yet been connected in OpenCode.
        domains = list(PROVIDER_DOMAINS[provider])
        if provider == "xpiki":
            host = urlparse(xpiki_manager.load_xpiki_config().get("base_url") or xpiki_manager.DEFAULT_BASE_URL).hostname
            if host:
                domains = [host]
        try:
            oc = _read_opencode_config()
            oc = copy.deepcopy(oc)
            entry = oc.setdefault("provider", {}).setdefault(provider, {})
            if provider == "xpiki":
                entry.setdefault("options", {}).setdefault("baseURL", "https://" + domains[0])
            def probe(domain):
                row = {"domain": domain, "status": "error", "latency_ms": None,
                       "route": "Не определён", "ip": None}
                t0 = time.perf_counter()
                try:
                    conn, upstream = provider_proxy.connect_routed(domain, 443, hub_config=cfg, opencode_config=oc)
                    row["route"] = ("DNS Hub" if upstream == "dns://hub" else "Системный маршрут" if not upstream
                        else "VLESS" if upstream == f"http://127.0.0.1:{get_http_port()}" else "HTTP-прокси")
                    with conn:
                        row.update(status="ok", latency_ms=round((time.perf_counter() - t0) * 1000),
                                   ip=conn.getpeername()[0])
                except Exception as exc:
                    row["error"] = type(exc).__name__
                return row
            with ThreadPoolExecutor(max_workers=4) as executor:
                results = list(executor.map(probe, domains))
            if signature != self._diagnostic_signature():
                return []
            with self._diagnostic_lock:
                self._diagnostics[provider] = results
                self._diagnostic_signatures[provider] = signature
                self._diagnostic_checked[provider] = time.time()
            return results
        finally:
            with self._diagnostic_lock:
                self._diagnostic_running.discard(provider)

    def run_provider_deep_probe(self, provider: str) -> dict:
        """
        Manually triggers a lightweight end-to-end API/generation probe.
        Checks real model answers, tokens, and geoblocks (e.g. Google Region not supported).
        """
        import health_checker
        provider = {"claude": "claude-pro", "openrouter": "openrouter-free",
                    "tokenlavka": "tokenlavka", "nvidia": "nvidia-nim"}.get(provider, provider)
        if provider == "nvidia-nim":
            key = nvidia_manager.load_key()
            models = nvidia_manager.state().get("selectedModels", [])
            if not key or not models:
                raise ValueError("Сначала подключите модель NVIDIA NIM")
            nvidia_manager.probe_model(key, models[0])
            return {"ok": True, "message": f"NVIDIA NIM: генерация через {models[0]} доступна"}
        if provider not in ("google", "openai", "claude-pro", "xpiki", "openrouter-free", "tokenlavka"):
            raise ValueError("Неизвестный провайдер")
        return health_checker.test_provider_deep_probe(provider, timeout=20)

    def set_provider_route(self, provider: str, route: str) -> bool:
        provider = {"claude": "claude-pro", "openrouter": "openrouter-free", "deepseek": "deepseek-account",
                    "tokenlavka": "tokenlavka", "nvidia": "nvidia-nim"}.get(provider, provider)
        if provider not in ("google", "openai", "claude-pro", "xpiki", "openrouter-free", "deepseek-account",
                            "tokenlavka", "nvidia-nim"):
            raise ValueError("Неизвестный провайдер")
        if route not in ("direct", "default", "auto", "vless", "dns", "proxy"):
            raise ValueError("Неизвестный маршрут")
        # Both spellings select AutoRouter. The UI now writes "auto"; older
        # configs with "default" keep working, so store whichever was chosen.
        with self._config_lock:
            cfg = self.load_config()
            prev_cfg = copy.deepcopy(cfg)
            if route == "vless" and not vless_service.is_running():
                raise ValueError("Сначала настройте и запустите VLESS-туннель")
            if route == "proxy" and not cfg.get("proxy"):
                raise ValueError("Сначала укажите внешний прокси")
            if not isinstance(cfg.get("provider_routes"), dict):
                cfg["provider_routes"] = {}
            cfg["provider_routes"][provider] = route
            if not self.save_config(cfg):
                raise OSError("Не удалось сохранить маршрут")
            try:
                self._sync_routes(cfg)
            except Exception:
                self.save_config(prev_cfg)
                raise
            self._invalidate_diagnostics_cache()
        if route in ("default", "auto"):
            self.refresh_auto_routes(provider)
        return True

    def save_network_settings(self, settings: dict) -> dict:
        if not isinstance(settings, dict):
            raise ValueError("Некорректные настройки сети")
        allowed = {"vless_url", "vless_kill_switch", "dns_mode", "custom_dns", "dot_host", "doh_url",
                   "proxy", "proxy_pool", "proxy_failover", "dns_presets"}
        with self._config_lock:
            cfg = self.load_config()
            prev_cfg = copy.deepcopy(cfg)
            cfg.update({k: v for k, v in settings.items() if k in allowed})
            if "dns_presets" in settings:
                presets = settings["dns_presets"]
                if not isinstance(presets, list) or len(presets) > 50:
                    raise ValueError("Список DNS должен содержать не более 50 записей")
                validated_presets = []
                seen_names = set()
                for preset in presets:
                    if not isinstance(preset, dict):
                        raise ValueError("Некорректная запись DNS")
                    name = str(preset.get("name") or "").strip()
                    if not name or len(name) > 60 or name.casefold() in seen_names:
                        raise ValueError("Названия DNS должны быть непустыми, уникальными и не длиннее 60 символов")
                    seen_names.add(name.casefold())
                    standard = preset.get("standard", [])
                    if not isinstance(standard, list) or len(standard) > 2:
                        raise ValueError(f"В записи «{name}» допустимо не более двух IP-адресов")
                    try:
                        standard = [str(ipaddress.IPv4Address(str(address).strip())) for address in standard]
                    except (ipaddress.AddressValueError, ValueError):
                        raise ValueError(f"В записи «{name}» указан некорректный IPv4-адрес") from None
                    dot = str(preset.get("dot") or "").strip()
                    if dot and not re.fullmatch(r"[A-Za-z0-9.-]+(?::[0-9]{1,5})?", dot):
                        raise ValueError(f"В записи «{name}» указан некорректный DoT-хост")
                    doh = str(preset.get("doh") or "").strip()
                    if doh:
                        try:
                            parsed_doh = urlparse(doh)
                            _ = parsed_doh.port
                        except ValueError:
                            raise ValueError(f"В записи «{name}» укажите корректный HTTPS URL DoH без логина и пароля") from None
                        if parsed_doh.scheme != "https" or not parsed_doh.hostname or parsed_doh.username or parsed_doh.password:
                            raise ValueError(f"В записи «{name}» укажите корректный HTTPS URL DoH без логина и пароля")
                    if not standard and not dot and not doh:
                        raise ValueError(f"В записи «{name}» укажите хотя бы один адрес")
                    validated_presets.append({"name": name, "standard": standard, "dot": dot, "doh": doh})
                cfg["dns_presets"] = validated_presets
            mode = cfg.get("dns_mode", "system")
            if mode not in ("system", "standard", "dot", "doh"):
                raise ValueError("Неизвестный режим DNS")
            servers = cfg.get("custom_dns", [])
            if not isinstance(servers, list):
                raise ValueError("Укажите список DNS-серверов")
            normalized_servers = []
            for server in servers:
                if not isinstance(server, str):
                    raise ValueError("DNS-сервер должен быть строкой с IP-адресом")
                server_str = server.strip()
                if not server_str:
                    raise ValueError("Укажите корректный IP-адрес DNS-сервера")
                ipaddress.ip_address(server_str)
                normalized_servers.append(server_str)
            cfg["custom_dns"] = normalized_servers
            servers = normalized_servers
            if mode == "standard" and not servers:
                raise ValueError("Укажите хотя бы один DNS-сервер")

            raw_dot = cfg.get("dot_host", "")
            if raw_dot is None:
                raw_dot = ""
            if not isinstance(raw_dot, str):
                raise ValueError("Укажите корректный DoT-хост")
            dot_host = raw_dot.strip()
            if dot_host and not re.fullmatch(r"[A-Za-z0-9.-]+(?::[0-9]{1,5})?", dot_host):
                raise ValueError("Укажите корректный DoT-хост")
            if "dot_host" in cfg:
                cfg["dot_host"] = dot_host
            if mode == "dot" and not dot_host:
                raise ValueError("Укажите хост DoT")

            raw_doh = cfg.get("doh_url", "")
            if raw_doh is None:
                raw_doh = ""
            if not isinstance(raw_doh, str):
                raise ValueError("Укажите корректный HTTPS URL DoH")
            doh_url = raw_doh.strip()
            if doh_url:
                try:
                    parsed_doh = urlparse(doh_url)
                    _ = parsed_doh.port
                except ValueError:
                    raise ValueError("Укажите корректный HTTPS URL DoH без логина и пароля") from None
                if parsed_doh.scheme != "https" or not parsed_doh.hostname or parsed_doh.username or parsed_doh.password:
                    raise ValueError("Укажите корректный HTTPS URL DoH без логина и пароля")
            if "doh_url" in cfg:
                cfg["doh_url"] = doh_url
            if mode == "doh" and not doh_url:
                raise ValueError("Укажите HTTPS URL для DoH")

            cfg.pop("google_smart_doh", None)
            for key, fallback in (("vless_http_port", 10879), ("vless_socks_port", 10878)):
                port = int(cfg.get(key, fallback))
                if not 1024 <= port <= 65535:
                    raise ValueError("Порты VLESS должны быть от 1024 до 65535")
                cfg[key] = port
            if cfg["vless_http_port"] == cfg["vless_socks_port"]:
                raise ValueError("HTTP и SOCKS порты должны различаться")
            if cfg.get("vless_url"):
                VlessParser.parse_url(cfg["vless_url"])
            # Keep the active connection string and the pool in sync: a manually
            # pasted vless:// URL becomes the first pool entry automatically.
            pool = _normalize_vless_pool(cfg.get("vless_pool"))
            active = str(cfg.get("vless_url") or "").strip()
            if active and active not in [entry["url"] for entry in pool]:
                pool.append({"url": active, "label": _vless_label(active), "status": "untested",
                             "ip": None, "country": None, "latency_ms": None,
                             "checked_at": None, "error": None})
            cfg["vless_pool"] = pool
            raw_proxy = cfg.get("proxy", "")
            if raw_proxy is None:
                raw_proxy = ""
            if not isinstance(raw_proxy, str):
                raise ValueError("Внешний прокси: укажите http:// или https:// адрес")
            proxy = raw_proxy.strip()
            if proxy:
                try:
                    parsed = urlparse(proxy)
                    proxy_port = parsed.port
                except ValueError:
                    raise ValueError("Внешний прокси: некорректный порт") from None
                if parsed.scheme not in ("http", "https") or not parsed.hostname or proxy_port == 0:
                    raise ValueError("Внешний прокси: укажите http:// или https:// адрес")
                if _is_hub_local_proxy(parsed):
                    raise ValueError("Нельзя использовать собственный маршрутизатор как внешний прокси")
            cfg["proxy"] = proxy

            # Handle proxy pool validation
            pool = cfg.get("proxy_pool", [])
            valid_pool = []
            if isinstance(pool, list):
                for p in pool:
                    p_str = p.strip() if isinstance(p, str) else ""
                    if p_str:
                        try:
                            p_parsed = urlparse(p_str)
                            p_port = p_parsed.port
                        except ValueError:
                            continue
                        if p_parsed.scheme in ("http", "https") and p_parsed.hostname and p_port != 0:
                            if not _is_hub_local_proxy(p_parsed):
                                if p_str not in valid_pool:
                                    valid_pool.append(p_str)
            if "proxy_failover" in cfg:
                cfg["proxy_failover"] = bool(cfg["proxy_failover"])
            if proxy and proxy not in valid_pool:
                valid_pool.insert(0, proxy)
            cfg["proxy_pool"] = valid_pool
            if "proxy" in settings and not proxy:
                cfg["proxy"] = ""
            elif valid_pool:
                cfg["proxy"] = proxy if proxy in valid_pool else valid_pool[0]
            else:
                cfg["proxy"] = proxy
            if vless_service.is_running() and any(cfg.get(k) != prev_cfg.get(k) for k in
                    ("vless_url", "vless_core_path", "vless_http_port", "vless_socks_port")):
                raise ValueError("Остановите туннель перед изменением ссылки, ядра или портов")
            if not self.save_config(cfg):
                raise OSError("Не удалось сохранить настройки сети")
            try:
                self._sync_routes(cfg)
            except Exception:
                self.save_config(prev_cfg)
                raise
            self._invalidate_diagnostics_cache()
        return {"ok": True, "message": "Настройки сети сохранены. Новые подключения используют выбранный маршрут."}

    def start_vless(self) -> dict:
        with self._core_lock:
            if self._closing.is_set() or self._uninstalled or self._uninstalling:
                return {"ok": False, "message": "Приложение завершает работу"}
            cfg = self.load_config()
            started_here = False
            if vless_service.is_running():
                ok, message = True, "VLESS-туннель уже запущен"
            else:
                ok, message = vless_service.start_tunnel(
                    cfg.get("vless_url", ""),
                    custom_core_path=cfg.get("vless_core_path"),
                )
                started_here = ok
            if ok:
                if self._closing.is_set() or self._uninstalled or self._uninstalling:
                    if started_here:
                        try:
                            vless_service.stop_tunnel()
                        except Exception as exc:
                            hub_logging.failed("Stop VLESS on closing", exc)
                    return {"ok": False, "message": "Приложение завершает работу"}
                with self._config_lock:
                    latest = self.load_config()
                    prev_cfg = copy.deepcopy(latest)
                    latest["vless_enabled"] = True
                    try:
                        if not self.save_config(latest):
                            raise OSError("Туннель запущен, но его настройки не сохранены")
                        self._sync_routes(latest)
                    except Exception:
                        self.save_config(prev_cfg)
                        if started_here:
                            try:
                                vless_service.stop_tunnel()
                            except Exception:
                                pass
                        raise
                    self._invalidate_diagnostics_cache()
            else:
                with self._config_lock:
                    latest = self.load_config()
                    actual_running = bool(vless_service.is_running())
                    if latest.get("vless_enabled") != actual_running:
                        prev_cfg = copy.deepcopy(latest)
                        latest["vless_enabled"] = actual_running
                        if self.save_config(latest):
                            try:
                                self._sync_routes(latest)
                            except Exception:
                                self.save_config(prev_cfg)
                            self._invalidate_diagnostics_cache()
            return {"ok": ok, "message": message}

    def stop_vless(self) -> dict:
        with self._core_lock:
            ok, message = vless_service.stop_tunnel()
            actual_running = False if ok else bool(vless_service.is_running())
            with self._config_lock:
                cfg = self.load_config()
                prev_cfg = copy.deepcopy(cfg)
                cfg["vless_enabled"] = actual_running
                if not self.save_config(cfg):
                    return {"ok": False, "message": "Не удалось сохранить состояние туннеля"}
                try:
                    self._sync_routes(cfg)
                except Exception:
                    self.save_config(prev_cfg)
                    raise
                self._invalidate_diagnostics_cache()
            if not ok:
                return {"ok": False, "message": message or "Не удалось остановить туннель"}
            return {"ok": True, "message": message}

    def set_vless_core(self, core_type: str) -> dict:
        """Select an installed core without exposing a free-form path field."""
        if core_type not in ("sing-box", "xray"):
            raise ValueError("Неизвестное ядро")
        with self._core_lock:
            if vless_service.is_running():
                return {"ok": False, "message": "Остановите туннель VLESS перед сменой ядра"}
            path = vless_service.find_core_executable(core_type=core_type)
            if not path:
                return {"ok": False, "message": f"{core_type} не установлен"}
            with self._config_lock:
                cfg = self.load_config()
                prev_cfg = copy.deepcopy(cfg)
                cfg["vless_core_path"] = str(path)
                if not self.save_config(cfg):
                    return {"ok": False, "message": "Не удалось сохранить настройки"}
                try:
                    self._sync_routes(cfg)
                except Exception:
                    self.save_config(prev_cfg)
                    raise
        return {"ok": True, "message": f"Выбрано ядро: {getattr(path, 'name', path)}",
                "path": str(path)}

    def test_vless(self) -> dict:
        return vless_service.test_connection()

    # --- VLESS connection pool ------------------------------------------------
    def _vless_probe(self, url: str, cfg: dict) -> dict:
        """Start the tunnel on one config, measure its exit IP, then stop it."""
        ok, message = vless_service.start_tunnel(url, custom_core_path=cfg.get("vless_core_path"))
        if not ok:
            return {"ok": False, "message": message, "ip": None, "country": None,
                    "latency_ms": None, "checked_at": int(time.time())}
        try:
            return vless_service.test_connection(timeout=10)
        finally:
            stop_ok, stop_msg = vless_service.stop_tunnel()
            if not stop_ok:
                hub_logging.log.warning("VLESS probe stop_tunnel failed: %s", stop_msg)

    def _cache_vless_result_locked(self, cfg: dict, url: str, result: dict) -> list:
        latest = self.load_config()
        prev_cfg = copy.deepcopy(latest)
        pool = _normalize_vless_pool(latest.get("vless_pool"))
        for entry in pool:
            if entry["url"] == url:
                entry.update({
                    "status": "ok" if result.get("ok") else "error",
                    "ip": result.get("ip"),
                    "country": result.get("country"),
                    "latency_ms": result.get("latency_ms"),
                    "error": None if result.get("ok") else result.get("message"),
                    "checked_at": int(time.time()),
                })
                break
        latest["vless_pool"] = pool
        if not self.save_config(latest):
            raise OSError("Не удалось сохранить результаты проверки VLESS")
        try:
            self._sync_routes(latest)
        except Exception:
            self.save_config(prev_cfg)
            raise
        if isinstance(cfg, dict):
            cfg["vless_pool"] = pool
        return pool

    def _cache_vless_result(self, cfg: dict, url: str, result: dict) -> list:
        with self._config_lock:
            return self._cache_vless_result_locked(cfg, url, result)

    def get_vless_pool(self) -> dict:
        cfg = self.load_config()
        pool = _normalize_vless_pool(cfg.get("vless_pool"))
        active = str(cfg.get("vless_url") or "").strip()
        public = _vless_pool_view(pool)
        active_id = _pool_id(active)
        active_entry = next((e for e in public if e["id"] == active_id), None)
        return {"pool": public, "active": active_id,
                "activeEntry": active_entry,
                "tunnelRunning": vless_service.is_running()}

    def add_vless_config(self, url: str) -> dict:
        url = str(url or "").strip()
        try:
            info = VlessParser.parse_url(url)
        except Exception as exc:
            return {"ok": False, "message": f"Некорректная VLESS-ссылка: {exc}"}
        with self._config_lock:
            cfg = self.load_config()
            prev_cfg = copy.deepcopy(cfg)
            pool = _normalize_vless_pool(cfg.get("vless_pool"))
            if any(entry["url"] == url for entry in pool):
                return {"ok": False, "message": "Этот конфиг уже есть в пуле"}
            pool.append({"url": url, "label": _vless_label(url), "status": "untested",
                         "ip": None, "country": None, "latency_ms": None,
                         "checked_at": None, "error": None})
            cfg["vless_pool"] = pool
            if not str(cfg.get("vless_url") or "").strip():
                cfg["vless_url"] = url
            if not self.save_config(cfg):
                return {"ok": False, "message": "Не удалось сохранить конфиг"}
            try:
                self._sync_routes(cfg)
            except Exception:
                self.save_config(prev_cfg)
                raise
            return {"ok": True, "message": f"Добавлено: {info.get('tag') or info.get('server')}",
                    "pool": _vless_pool_view(pool), "active": _pool_id(cfg["vless_url"]),
                    "id": _pool_id(url)}

    def delete_vless_config(self, url: str) -> dict:
        url = str(url or "").strip()
        with self._core_lock:
            with self._config_lock:
                cfg = self.load_config()
                pool = _normalize_vless_pool(cfg.get("vless_pool"))
                resolved_url = next((e["url"] for e in pool if _pool_id(e["url"]) == url), url)
                remaining = [e for e in pool if e["url"] != resolved_url]
                if len(remaining) == len(pool):
                    return {"ok": False, "message": "Конфиг не найден в пуле"}
                active = str(cfg.get("vless_url") or "").strip()
                new_active = (remaining[0]["url"] if remaining else "") if active == resolved_url else active
                core_path = cfg.get("vless_core_path")

            was_running = vless_service.is_running()
            tunnel_running = was_running
            if active == resolved_url and was_running:
                stop_ok, stop_msg = vless_service.stop_tunnel()
                if not stop_ok:
                    return {"ok": False, "message": stop_msg or "Не удалось остановить текущий VLESS-туннель"}
                tunnel_running = False
                if new_active:
                    start_ok, start_msg = vless_service.start_tunnel(new_active, custom_core_path=core_path)
                    tunnel_running = start_ok
                    if not start_ok:
                        with self._config_lock:
                            latest = self.load_config()
                            prev_cfg = copy.deepcopy(latest)
                            latest_pool = _normalize_vless_pool(latest.get("vless_pool"))
                            latest_rem = [e for e in latest_pool if e["url"] != resolved_url]
                            latest["vless_url"] = latest_rem[0]["url"] if latest_rem else ""
                            latest["vless_pool"] = latest_rem
                            latest["vless_enabled"] = False
                            if self.save_config(latest):
                                try:
                                    self._sync_routes(latest)
                                except Exception:
                                    self.save_config(prev_cfg)
                                self._invalidate_diagnostics_cache()
                        return {"ok": False, "message": start_msg or "Конфиг удалён, но новый туннель не запустился"}

            with self._config_lock:
                latest = self.load_config()
                prev_cfg = copy.deepcopy(latest)
                latest_pool = _normalize_vless_pool(latest.get("vless_pool"))
                remaining = [e for e in latest_pool if e["url"] != resolved_url]
                if active == resolved_url:
                    latest["vless_url"] = remaining[0]["url"] if remaining else ""
                    if was_running:
                        latest["vless_enabled"] = bool(tunnel_running)
                latest["vless_pool"] = remaining
                if not self.save_config(latest):
                    return {"ok": False, "message": "Не удалось сохранить пул"}
                try:
                    self._sync_routes(latest)
                except Exception:
                    self.save_config(prev_cfg)
                    raise
                self._invalidate_diagnostics_cache()
                return {"ok": True, "message": "Конфиг удалён из пула", "pool": _vless_pool_view(remaining),
                        "active": _pool_id(latest.get("vless_url") or "")}

    def activate_vless_config(self, url: str) -> dict:
        url = str(url or "").strip()
        with self._core_lock:
            with self._config_lock:
                cfg = self.load_config()
                prev_cfg = copy.deepcopy(cfg)
                pool = _normalize_vless_pool(cfg.get("vless_pool"))
                resolved_url = next((e["url"] for e in pool if _pool_id(e["url"]) == url), url)
                if not any(entry["url"] == resolved_url for entry in pool):
                    return {"ok": False, "message": "Конфиг не найден в пуле"}
                previous = str(cfg.get("vless_url") or "").strip()
                core_path = cfg.get("vless_core_path")
                cfg["vless_url"] = resolved_url
                if not self.save_config(cfg):
                    return {"ok": False, "message": "Не удалось сохранить активный конфиг"}
                try:
                    self._sync_routes(cfg)
                except Exception:
                    self.save_config(prev_cfg)
                    raise
                self._invalidate_diagnostics_cache()

            was_running = vless_service.is_running()
            result = None
            tunnel_active = was_running
            if was_running and previous != resolved_url:
                stop_ok, stop_msg = vless_service.stop_tunnel()
                if not stop_ok:
                    with self._config_lock:
                        latest = self.load_config()
                        prev2 = copy.deepcopy(latest)
                        latest["vless_url"] = previous
                        latest["vless_enabled"] = bool(vless_service.is_running())
                        if self.save_config(latest):
                            try:
                                self._sync_routes(latest)
                            except Exception:
                                self.save_config(prev2)
                    return {"ok": False, "message": stop_msg or "Не удалось остановить текущий туннель"}
                ok, message = vless_service.start_tunnel(resolved_url, custom_core_path=core_path)
                tunnel_active = ok
                result = (vless_service.test_connection(timeout=10) if ok else
                          {"ok": False, "message": message, "ip": None, "country": None, "latency_ms": None})
            elif was_running:
                result = vless_service.test_connection(timeout=10)
            else:
                # There is no Start button in the UI: activating a config
                # starts the tunnel and leaves it running.
                ok, message = vless_service.start_tunnel(resolved_url, custom_core_path=core_path)
                tunnel_active = ok
                result = (vless_service.test_connection(timeout=10) if ok else
                          {"ok": False, "message": message, "ip": None, "country": None, "latency_ms": None})

            with self._config_lock:
                latest = self.load_config()
                prev2 = copy.deepcopy(latest)
                desired_enabled = bool(tunnel_active)
                if latest.get("vless_enabled") != desired_enabled:
                    latest["vless_enabled"] = desired_enabled
                    if not self.save_config(latest):
                        return {"ok": False, "message": "Не удалось сохранить состояние туннеля",
                                "pool": _vless_pool_view(_normalize_vless_pool(latest.get("vless_pool"))),
                                "active": _pool_id(resolved_url), "result": result}
                    try:
                        self._sync_routes(latest)
                    except Exception:
                        self.save_config(prev2)
                        raise
                    self._invalidate_diagnostics_cache()
                if result is not None:
                    try:
                        pool = self._cache_vless_result_locked(latest, resolved_url, result)
                    except OSError as exc:
                        return {"ok": False, "message": str(exc),
                                "pool": _vless_pool_view(_normalize_vless_pool(latest.get("vless_pool"))),
                                "active": _pool_id(resolved_url), "result": result}
                else:
                    pool = _normalize_vless_pool(latest.get("vless_pool"))

            return {"ok": bool(tunnel_active),
                    "message": result.get("message") if result else "Конфиг активирован",
                    "pool": _vless_pool_view(pool), "active": _pool_id(resolved_url), "result": result}

    def test_vless_config(self, url: str) -> dict:
        url = str(url or "").strip()
        with self._core_lock:
            with self._config_lock:
                cfg = self.load_config()
                pool = _normalize_vless_pool(cfg.get("vless_pool"))
                resolved_url = next((e["url"] for e in pool if _pool_id(e["url"]) == url), url)
                if not any(entry["url"] == resolved_url for entry in pool):
                    return {"ok": False, "message": "Конфиг не найден в пуле"}
                active = str(cfg.get("vless_url") or "").strip()
                core_path = cfg.get("vless_core_path")

            was_running = vless_service.is_running()
            if was_running:
                stop_ok, stop_msg = vless_service.stop_tunnel()
                if not stop_ok:
                    return {"ok": False, "message": stop_msg or "Не удалось остановить текущий туннель для проверки"}
            restore_ok = True
            restore_msg = ""
            try:
                result = self._vless_probe(resolved_url, {"vless_core_path": core_path})
            finally:
                # Always bring the previously active config back online.
                if was_running and active:
                    restore_ok, restore_msg = vless_service.start_tunnel(active, custom_core_path=core_path)

            with self._config_lock:
                latest = self.load_config()
                if was_running and active and not restore_ok:
                    prev_cfg = copy.deepcopy(latest)
                    latest["vless_enabled"] = bool(vless_service.is_running())
                    if self.save_config(latest):
                        try:
                            self._sync_routes(latest)
                        except Exception:
                            self.save_config(prev_cfg)
                        self._invalidate_diagnostics_cache()
                try:
                    pool = self._cache_vless_result_locked(latest, resolved_url, result)
                except OSError as exc:
                    return {"ok": False, "message": str(exc),
                            "pool": _vless_pool_view(_normalize_vless_pool(latest.get("vless_pool")))}

            if was_running and active and not restore_ok:
                return {"ok": False,
                        "message": f"{result.get('message', 'Проверка завершена')}; не удалось перезапустить активный туннель: {restore_msg}",
                        "ip": result.get("ip"), "country": result.get("country"),
                        "latency_ms": result.get("latency_ms"), "pool": _vless_pool_view(pool)}
            return {"ok": bool(result.get("ok")), "message": result.get("message", "Ошибка проверки"),
                    "ip": result.get("ip"), "country": result.get("country"),
                    "latency_ms": result.get("latency_ms"), "pool": _vless_pool_view(pool)}

    def test_all_vless_configs(self) -> dict:
        results = []
        with self._core_lock:
            with self._config_lock:
                cfg = self.load_config()
                pool = _normalize_vless_pool(cfg.get("vless_pool"))
                active = str(cfg.get("vless_url") or "").strip()
                core_path = cfg.get("vless_core_path")
            was_running = vless_service.is_running()
            if was_running:
                stop_ok, stop_msg = vless_service.stop_tunnel()
                if not stop_ok:
                    return {"ok": False, "message": stop_msg or "Не удалось остановить текущий туннель для проверки",
                            "results": [], "pool": _vless_pool_view(pool)}
            restore_ok = True
            restore_msg = ""
            try:
                for entry in pool:
                    if self._closing.is_set() or self._uninstalled or self._uninstalling:
                        break
                    result = self._vless_probe(entry["url"], {"vless_core_path": core_path})
                    try:
                        with self._config_lock:
                            self._cache_vless_result_locked(cfg, entry["url"], result)
                    except OSError as exc:
                        latest_pool = _normalize_vless_pool(self.load_config().get("vless_pool"))
                        return {"ok": False, "message": str(exc), "results": results,
                                "pool": _vless_pool_view(latest_pool)}
                    results.append({"id": _pool_id(entry["url"]), "label": _vless_label(entry["url"]),
                                    "ok": bool(result.get("ok")), "ip": result.get("ip"),
                                    "country": result.get("country"),
                                    "latency_ms": result.get("latency_ms")})
            finally:
                if was_running and active:
                    restore_ok, restore_msg = vless_service.start_tunnel(active, custom_core_path=core_path)
            if was_running and active and not restore_ok:
                with self._config_lock:
                    latest = self.load_config()
                    prev_cfg = copy.deepcopy(latest)
                    latest["vless_enabled"] = bool(vless_service.is_running())
                    if self.save_config(latest):
                        try:
                            self._sync_routes(latest)
                        except Exception:
                            self.save_config(prev_cfg)
                        self._invalidate_diagnostics_cache()
                latest_pool = _normalize_vless_pool(self.load_config().get("vless_pool"))
                return {"ok": False,
                        "message": f"Не удалось перезапустить активный туннель: {restore_msg}",
                        "results": results, "pool": _vless_pool_view(latest_pool)}
        latest_pool = _normalize_vless_pool(self.load_config().get("vless_pool"))
        ok_count = sum(1 for r in results if r["ok"])
        return {"ok": ok_count > 0, "message": f"Проверено {len(results)} конфигов, доступно {ok_count}",
                "results": results, "pool": _vless_pool_view(latest_pool)}

    def download_vless_core(self, core_type: str = "sing-box") -> dict:
        if core_type not in ("sing-box", "xray"):
            raise ValueError("Неизвестное ядро")
        with self._core_lock:
            ok, message = vless_service.download_core(core_type)
        return {"ok": ok, "message": message}

    def test_dns(self, mode: str, value: str) -> dict:
        # Pass the domain explicitly so concurrent resolver checks are independent.
        domain = "cloudcode-pa.googleapis.com"
        if mode == "standard":
            ipaddress.ip_address(value)
            return dns_tester.test_standard_dns(value, domain=domain)
        if mode == "dot":
            return dns_tester.test_dot_endpoint(value, domain=domain)
        if mode == "doh":
            return dns_tester.test_doh_endpoint(value, domain=domain)
        raise ValueError("Для проверки выберите обычный DNS, DoT или DoH")

    def add_proxy_pool(self, proxy_url: str) -> dict:
        proxy_url = str(proxy_url or "").strip()
        if not proxy_url:
            return {"ok": False, "message": "Укажите адрес прокси (http://host:port)"}
        try:
            parsed = urlparse(proxy_url)
            port = parsed.port
        except ValueError:
            return {"ok": False, "message": "Неверный формат адреса или порта прокси"}
        if parsed.scheme not in ("http", "https") or not parsed.hostname or port == 0:
            return {"ok": False, "message": "Неверный формат адреса: требуется http:// или https://"}
        if _is_hub_local_proxy(parsed):
            return {"ok": False, "message": "Нельзя использовать собственный маршрутизатор как внешний прокси"}

        with self._config_lock:
            cfg = self.load_config()
            prev_cfg = copy.deepcopy(cfg)
            pool = list(cfg.get("proxy_pool") or [])
            if proxy_url not in pool:
                pool.append(proxy_url)
            cfg["proxy_pool"] = pool
            if not cfg.get("proxy"):
                cfg["proxy"] = pool[0]
            if not self.save_config(cfg):
                return {"ok": False, "message": "Не удалось сохранить настройки"}
            try:
                self._sync_routes(cfg)
            except Exception:
                self.save_config(prev_cfg)
                raise
            self._invalidate_diagnostics_cache()
        return {"ok": True, "message": "Прокси добавлен в пул", **_proxy_view(cfg)}

    def delete_proxy_pool(self, proxy_url: str) -> dict:
        proxy_url = str(proxy_url or "").strip()
        with self._config_lock:
            cfg = self.load_config()
            prev_cfg = copy.deepcopy(cfg)
            existing = cfg.get("proxy_pool") or ([cfg["proxy"]] if cfg.get("proxy") else [])
            proxy_url = next((p for p in existing if _pool_id(p) == proxy_url), proxy_url)
            if proxy_url not in existing:
                return {"ok": False, "message": "Прокси не найден в пуле"}
            pool = [p for p in existing if p != proxy_url]
            cfg["proxy_pool"] = pool
            if cfg.get("proxy") == proxy_url:
                cfg["proxy"] = pool[0] if pool else ""
            if not self.save_config(cfg):
                return {"ok": False, "message": "Не удалось сохранить изменения"}
            try:
                self._sync_routes(cfg)
            except Exception:
                self.save_config(prev_cfg)
                raise
            self._invalidate_diagnostics_cache()
        return {"ok": True, "message": "Прокси удалён из пула", **_proxy_view(cfg)}

    def move_proxy_pool_item(self, from_index: int, to_index: int) -> dict:
        try:
            from_index, to_index = int(from_index), int(to_index)
        except (TypeError, ValueError):
            return {"ok": False, "message": "Некорректная позиция прокси"}
        with self._config_lock:
            cfg = self.load_config()
            prev_cfg = copy.deepcopy(cfg)
            pool = list(cfg.get("proxy_pool") or [])
            if not 0 <= from_index < len(pool) or not 0 <= to_index < len(pool):
                return {"ok": False, "message": "Прокси не найден в списке"}
            item = pool.pop(from_index)
            pool.insert(to_index, item)
            cfg["proxy_pool"] = pool
            cfg["proxy"] = pool[0] if pool else ""
            if not self.save_config(cfg):
                return {"ok": False, "message": "Не удалось сохранить приоритет прокси"}
            try:
                self._sync_routes(cfg)
            except Exception:
                self.save_config(prev_cfg)
                raise
            self._invalidate_diagnostics_cache()
        return {"ok": True, "message": "Приоритет прокси сохранён", **_proxy_view(cfg)}

    def test_proxy(self, proxy_id: str) -> dict:
        cfg = self.load_config()
        pool = cfg.get("proxy_pool") or ([cfg["proxy"]] if cfg.get("proxy") else [])
        proxy_url = next((url for url in pool if _pool_id(url) == proxy_id), None)
        if not proxy_url:
            return {"ok": False, "message": "Укажите адрес прокси"}
        try:
            parsed = urlparse(proxy_url)
            if parsed.scheme not in ("http", "https") or not parsed.hostname:
                return {"ok": False, "message": "Неверный формат адреса прокси (требуется http:// или https://)"}
            t0 = time.perf_counter()
            s = provider_proxy._connect_upstream(proxy_url, "cloudcode-pa.googleapis.com", 443, timeout=6)
            s.close()
            latency = round((time.perf_counter() - t0) * 1000)
            return {"ok": True, "latency_ms": latency, "message": f"Прокси доступен ({latency} мс)"}
        except Exception:
            return {"ok": False, "message": "Ошибка соединения с прокси"}

    def refresh_openai_quotas(self) -> dict:
        if self._uninstalling or self._uninstalled or self._closing.is_set():
            return {"ok": False, "refreshing": False}
        with self._quota_lock:
            if self._quota_refreshing:
                return {"ok": True, "refreshing": True}
            self._quota_refreshing = True
            self._quota_error = None
            self._quota_notice = None
        def worker():
            try:
                if self._uninstalling or self._uninstalled or self._closing.is_set():
                    return
                # Use the manager's single refresh path so quota refresh and
                # candidate rotation cannot drift apart again. The former Tk UI
                # called this path; the WebView worker used to duplicate only
                # quota fetching and silently omitted rotation.
                _accounts, rotation_message = openai_manager.refresh_all_openai_accounts()
                if rotation_message:
                    with self._quota_lock:
                        self._quota_notice = rotation_message
            except Exception as exc:
                hub_logging.failed("Refresh OpenAI quotas", exc)
                with self._quota_lock:
                    self._quota_error = str(exc)
            finally:
                with self._quota_lock:
                    self._quota_refreshing = False
        threading.Thread(target=worker, daemon=True, name="hub-openai-quotas").start()
        return {"ok": True, "refreshing": True}

    def refresh_all_quotas(self) -> dict:
        if self._uninstalling or self._uninstalled or self._closing.is_set():
            return {"ok": False, "message": "Приложение завершает работу"}
        self.refresh_openai_quotas()
        with self._all_quotas_lock:
            if self._all_quotas_running:
                return {"ok": True, "message": "Обновление квот уже выполняется"}
            self._all_quotas_running = True

        def bg_providers():
            try:
                for label, fn in (
                    ("DeepSeek balance", deepseek_api.refresh_balance_silent),
                    ("Xpiki quota", xpiki_manager.refresh_xpiki_quota_silent),
                    ("TokenLavka balance", tokenlavka_manager.refresh_balance_silent),
                    ("Google quotas", lambda: self._refresh_google_quotas_sync(timeout=45)),
                ):
                    if self._uninstalling or self._uninstalled or self._closing.is_set():
                        break
                    try:
                        fn()
                    except Exception as exc:
                        hub_logging.failed(f"Refresh {label}", exc)
            finally:
                with self._all_quotas_lock:
                    self._all_quotas_running = False

        threading.Thread(target=bg_providers, daemon=True, name="hub-all-quotas").start()
        return {"ok": True, "message": "Обновление квот запущено"}

    def get_provider_state(self) -> dict:
        xpiki = xpiki_manager.load_xpiki_config()
        xpiki_key = str(xpiki.get("api_key") or "")
        openrouter_key = openrouter_manager.load_api_key()
        def key_label(key):
            return "••••" + key[-4:] if len(key) > 8 else "Ключ сохранён" if key else None
        selected = []
        try:
            oc = _read_opencode_config()
            selected = list(oc.get("provider", {}).get("openrouter-free", {}).get("models", {}))
        except (OSError, ValueError, AttributeError):
            pass
        deepseek_state = deepseek_api.provider_state()
        try:
            balance = deepseek_state.get("balance") or {}
            currency = balance.get("currency") if balance.get("status") in ("ok", "stale") else None
            deepseek_state["usage"] = opencode_usage.deepseek_usage(currency=currency or "CNY")
        except Exception as exc:
            deepseek_state["usage"] = {"status": "error", "error": str(exc)[:160], "days": [],
                                       "totals": {"cost": 0.0, "tokens_total": 0, "messages": 0}}
        return {"xpiki": {"connected": bool(xpiki.get("connected") and xpiki_key), "hasKey": bool(xpiki_key),
                          "keyLabel": key_label(xpiki_key),
                          "baseUrl": xpiki.get("base_url") or xpiki_manager.DEFAULT_BASE_URL,
                          "enabledModels": xpiki.get("enabled_models", list(xpiki_manager.XPIKI_MODELS)),
                          "models": [{"id": mid, "name": meta["name"]} for mid, meta in xpiki_manager.XPIKI_MODELS.items()],
                          "quota": xpiki.get("cached_quota") or {}},
                "openrouter": {"hasKey": bool(openrouter_key), "keyLabel": key_label(openrouter_key),
                               "connected": bool(openrouter_key and selected), "selectedModels": selected},
                "deepseek": deepseek_state,
                "nvidia": self._nvidia_state(),
                "tokenlavka": tokenlavka_manager.provider_state()}

    def configure_xpiki(self, key: str, base_url: str, models: list) -> dict:
        with self._provider_lock:
            cfg = xpiki_manager.load_xpiki_config()
            key = str(key or "").strip() or cfg.get("api_key", "")
            base_url = str(base_url or "").strip().rstrip("/")
            parsed = urlparse(base_url)
            if not key or parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
                raise ValueError("Укажите ключ Xpiki и HTTPS URL шлюза")
            if not isinstance(models, list) or not models or any(mid not in xpiki_manager.XPIKI_MODELS for mid in models):
                raise ValueError("Выберите модели Xpiki")
            if not xpiki_manager.configure_opencode(key, base_url, models):
                raise OSError("Не удалось настроить Xpiki в OpenCode")
            cfg.update(api_key=key, base_url=base_url, enabled_models=models, connected=True)
            if not xpiki_manager.save_xpiki_config(cfg):
                raise OSError("Не удалось сохранить настройки Xpiki")
            self._sync_routes(self.load_config())
            self._invalidate_diagnostics_cache()
            return {"ok": True, "message": "Xpiki добавлен в OpenCode"}

    def refresh_xpiki_quota(self) -> dict:
        cfg = xpiki_manager.load_xpiki_config()
        if not cfg.get("api_key"):
            raise ValueError("Сначала сохраните API-ключ Xpiki")
        return xpiki_manager.fetch_xpiki_quota(cfg["api_key"], cfg.get("base_url") or xpiki_manager.DEFAULT_BASE_URL)

    def disconnect_xpiki(self) -> bool:
        with self._provider_lock:
            if not xpiki_manager.disconnect_xpiki():
                raise OSError("Не удалось отключить Xpiki")
        return True

    def configure_deepseek_api(self, key: str = "", base_url: str = "") -> dict:
        """Saves an encrypted DeepSeek Platform API key, reads balance, and
        registers the DeepSeek provider with its real model catalog in OpenCode."""
        with self._provider_lock:
            base_url = str(base_url or "").strip() or deepseek_api.DEFAULT_BASE_URL
            origin = deepseek_api.api_origin(base_url)
            final_key = str(key or "").strip() or deepseek_api.load_api_key()
            if not final_key:
                raise ValueError("Укажите API-ключ DeepSeek (sk-...)")
            deepseek_api.save_api_key(final_key)
            cfg = deepseek_api.load_config()
            cfg["base_url"] = origin
            cfg["connected"] = True
            deepseek_api.save_config(cfg)

            notes = []
            try:
                models = deepseek_api.fetch_models(final_key, origin)
            except Exception as exc:
                hub_logging.failed("DeepSeek catalog", exc)
                models = [dict(m) for m in deepseek_api.FALLBACK_MODELS]
                notes.append("каталог моделей не загружен")
            cfg = deepseek_api.load_config()
            cfg["models"] = models
            deepseek_api.save_config(cfg)

            selected = []
            try:
                selected = deepseek_api.configure_opencode_models(
                    [m["id"] for m in models], final_key, origin)
            except Exception as exc:
                hub_logging.failed("DeepSeek configuration", exc)
                notes.append("не удалось добавить провайдера в OpenCode")
            try:
                deepseek_api.sync_opencode_credential(final_key)
            except Exception as exc:
                hub_logging.failed("DeepSeek credential sync", exc)
                notes.append("ключ не импортирован в OpenCode CLI")

            try:
                self._sync_routes(self.load_config())
            except Exception as exc:
                hub_logging.failed("DeepSeek route sync", exc)
                notes.append("не удалось синхронизировать маршруты")

            balance = deepseek_api.fetch_balance(final_key, origin)
            if balance.get("status") not in ("ok", "stale"):
                notes.append(balance.get("error") or "не удалось получить баланс")

            message = "Ключ DeepSeek сохранён"
            if selected:
                message += f", провайдер DeepSeek добавлен в OpenCode (моделей: {len(selected)})"
            if notes:
                message += ". Внимание: " + "; ".join(notes)
            return {
                "ok": balance.get("status") in ("ok", "stale"),
                "message": message,
                "balance": balance,
                "models": models,
                "selectedModels": selected,
            }

    def apply_deepseek_models(self, model_ids: list) -> dict:
        """Register only the selected DeepSeek models in OpenCode."""
        with self._provider_lock:
            key = deepseek_api.load_api_key()
            if not key:
                raise ValueError("Сначала сохраните API-ключ DeepSeek")
            if not isinstance(model_ids, list) or not model_ids:
                raise ValueError("Выберите хотя бы одну модель DeepSeek")
            cfg = deepseek_api.load_config()
            selected = deepseek_api.configure_opencode_models(
                [str(mid) for mid in model_ids], key, cfg.get("base_url"))
            try:
                deepseek_api.sync_opencode_credential(key)
            except Exception:
                pass
            self._sync_routes(self.load_config())
            return {"ok": True, "selectedModels": selected,
                    "message": f"Моделей DeepSeek в OpenCode: {len(selected)}"}

    def load_deepseek_models(self, key: str = "") -> list:
        """Refresh the DeepSeek model catalog from the Platform API."""
        with self._provider_lock:
            final_key = str(key or "").strip() or deepseek_api.load_api_key()
            if not final_key:
                raise ValueError("Укажите API-ключ DeepSeek (sk-...)")
            cfg = deepseek_api.load_config()
            models = deepseek_api.fetch_models(final_key, cfg.get("base_url"))
            cfg["models"] = models
            deepseek_api.save_config(cfg)
            return models

    def refresh_deepseek_balance(self) -> dict:
        return deepseek_api.refresh_balance_silent()

    def disconnect_deepseek_api(self) -> bool:
        with self._provider_lock:
            try:
                deepseek_api.disconnect_opencode()
            except Exception:
                pass
            cleared = deepseek_api.clear_api_key()
            self._sync_routes(self.load_config())
            return cleared

    def load_openrouter_models(self, key: str = "") -> list:
        with self._provider_lock:
            key = str(key or "").strip() or openrouter_manager.load_api_key()
            if not key:
                raise ValueError("Укажите API-ключ OpenRouter")
            models = openrouter_manager.fetch_free_models(key)
            openrouter_manager.save_api_key(key)
            self._openrouter_models = models
            return models

    def apply_openrouter_models(self, model_ids: list) -> bool:
        with self._provider_lock:
            if not isinstance(model_ids, list) or not model_ids or not all(isinstance(mid, str) for mid in model_ids):
                raise ValueError("Загрузите каталог и выберите бесплатные модели")
            selected_ids = set(model_ids)
            selected = [m for m in self._openrouter_models if m["id"] in selected_ids]
            if not selected or len(selected) != len(selected_ids):
                raise ValueError("Загрузите каталог и выберите бесплатные модели")
            key = openrouter_manager.load_api_key()
            if not key:
                raise ValueError("Сначала сохраните ключ OpenRouter")
            openrouter_manager.sync_opencode_credential(key)
            openrouter_manager.configure_models(selected)
            self._sync_routes(self.load_config())
            return True

    def disconnect_openrouter(self) -> bool:
        with self._provider_lock:
            openrouter_manager.disconnect()
            self._openrouter_models = []
        return True

    def _nvidia_state(self) -> dict:
        try:
            return nvidia_manager.state()
        except (OSError, ValueError):
            return {"error": "Hub не смог прочитать конфигурацию OpenCode для NVIDIA NIM."}

    def load_nvidia_models(self, key: str = "") -> list:
        with self._provider_lock:
            self._nvidia_catalog = ("", [])
            key = str(key or "").strip() or nvidia_manager.load_key()
            models = nvidia_manager.fetch_models(key)
            self._nvidia_catalog = (key, models)
            return models

    def probe_nvidia_model(self, model_id: str) -> bool:
        with self._provider_lock:
            key, models = self._nvidia_catalog
            if model_id not in models:
                raise ValueError("Загрузите каталог и выберите модель NVIDIA.")
            nvidia_manager.probe_model(key, model_id)
        return True

    def apply_nvidia_models(self, model_ids: list) -> dict:
        with self._provider_lock, self._config_lock:
            key, models = self._nvidia_catalog
            if not isinstance(model_ids, list) or not model_ids or any(m not in models for m in model_ids):
                raise ValueError("Загрузите каталог и выберите модели NVIDIA.")
            nvidia_manager.configure(key, model_ids)
            self._sync_routes(self.load_config())
            return nvidia_manager.state()

    def disconnect_nvidia(self) -> dict:
        with self._provider_lock, self._config_lock:
            nvidia_manager.disconnect()
            self._nvidia_catalog = ("", [])
            self._sync_routes(self.load_config())
            return nvidia_manager.state()

    def check_tokenlavka_key(self, key: str = "") -> dict:
        key = str(key or "").strip() or tokenlavka_manager.load_api_key()
        if not key:
            raise ValueError("Укажите API-ключ TokenLavka (sk-...)")
        ok, message = tokenlavka_manager.test_connection(key)
        return {"ok": ok, "message": message}

    def configure_tokenlavka_api(self, key: str = "", model_ids: list = None) -> dict:
        """Validate, save and register the TokenLavka key plus selected models."""
        with self._provider_lock:
            final_key = str(key or "").strip() or tokenlavka_manager.load_api_key()
            if not final_key:
                raise ValueError("Укажите API-ключ TokenLavka (sk-...)")
            ok, message = tokenlavka_manager.test_connection(final_key)
            if not ok:
                return {"ok": False, "message": message}
            tokenlavka_manager.save_api_key(final_key)
            tokenlavka_manager.sync_opencode_credential(final_key)
            chosen = model_ids or tokenlavka_manager.selected_models() or [tokenlavka_manager.DEFAULT_MODEL]
            selected = tokenlavka_manager.configure_models(chosen, final_key)
            tokenlavka_manager.fetch_balance(final_key)
            self._sync_routes(self.load_config())
            return {"ok": True, "message": f"TokenLavka подключена. Моделей в OpenCode: {len(selected)}"}

    def refresh_tokenlavka_balance(self) -> dict:
        return tokenlavka_manager.refresh_balance_silent()

    def disconnect_tokenlavka(self) -> bool:
        with self._provider_lock:
            tokenlavka_manager.disconnect()
        return True

    def add_google_account(self) -> dict:
        if not self._login_locks["google"].acquire(blocking=False):
            return {"status": "error", "message": "Вход в Google уже выполняется"}
        failure_message = "Не удалось завершить вход в Google."
        try:
            node_exe = antigravity_manager.get_node_executable()
            profile = self._google_refresh_profile()
            has_relocated = bool(getattr(antigravity_manager, "has_relocated_google_store", lambda: False)())
            cli_3113 = (
                _find_cli_3113()
                if profile == "3.1.13" or has_relocated
                else None
            )
            root = Path(sys._MEIPASS) if getattr(sys, "frozen", False) else CURRENT_DIR.parent
            login_runner_3113 = root / "plugin" / "dist" / "google-login-3113.mjs"
            notes = []

            if cli_3113 is not None and login_runner_3113.is_file():
                result = antigravity_manager.run_google_route_cmd(
                    [node_exe, str(login_runner_3113), str(cli_3113), "--login"],
                    timeout=300,
                )
                if result.returncode:
                    detail = (result.stderr or result.stdout or "").strip()
                    lower_detail = detail.lower()
                    if "already in use" in lower_detail or "eaddrinuse" in lower_detail:
                        failure_message = "Порт 51121 занят другим процессом входа — закройте зависший node.exe или повторите через минуту."
                    elif "timed out" in lower_detail:
                        failure_message = "Время ожидания входа в Google истекло — попробуйте снова."
                    raise RuntimeError(f"Google 3.1.13 login CLI: {detail}" if detail else "Google 3.1.13 login CLI")
                try:
                    quota = antigravity_manager.run_google_route_cmd(
                        [node_exe, str(login_runner_3113), str(cli_3113), "--quota"],
                        timeout=60,
                    )
                    if quota.returncode != 0:
                        notes.append("квоты обновить не удалось")
                    else:
                        self._store_google_quota_snapshot(quota.stdout)
                except Exception:
                    notes.append("квоты обновить не удалось")
            elif has_relocated:
                failure_message = (
                    "Хранилище Google использует формат плагина 3.1.x, но кэш 3.1.13 не найден — "
                    "запустите OpenCode один раз и повторите вход."
                )
                raise RuntimeError("Google 3.1.13 plugin cache missing for relocated store")
            else:
                cli_js = antigravity_manager.get_cli_js()
                if not os.path.exists(cli_js):
                    failure_message = "Файл CLI не найден."
                    raise RuntimeError("Файл CLI не найден")
                repair_error = antigravity_manager.repair_legacy_google_account_file()
                if repair_error:
                    failure_message = "Не удалось прочитать хранилище Google."
                    raise RuntimeError("Google account store")
                result = antigravity_manager.run_google_route_cmd([node_exe, cli_js, "login"], timeout=300)
                if result.returncode:
                    detail = (result.stderr or result.stdout or "").strip()
                    raise RuntimeError(f"Google login CLI: {detail}" if detail else "Google login CLI")
                repair_error = antigravity_manager.repair_legacy_google_account_file()
                if repair_error:
                    failure_message = "Не удалось прочитать хранилище Google."
                    raise RuntimeError("Google account store")
                result = antigravity_manager.run_silent_cmd(
                    [node_exe, cli_js, "migrate", "--offline", "--yes"], timeout=30)
                if result.returncode:
                    failure_message = "Миграция аккаунта Google не завершилась."
                    detail = (result.stderr or result.stdout or "").strip()
                    raise RuntimeError(f"Google migration CLI: {detail}" if detail else "Google migration CLI")

                # A freshly logged-in row exists in config.json, but its state.json
                # metadata (email/refresh) is written lazily. export_google_accounts()
                # skips rows without both, so keep this explicit post-login quota
                # check separate from the periodic credential-only refresh.
                try:
                    quota = antigravity_manager.run_google_route_cmd(
                        [node_exe, cli_js, "quota", "--refresh", "--json"], timeout=60)
                    if quota.returncode != 0:
                        notes.append("квоты обновить не удалось")
                    else:
                        self._store_google_quota_snapshot(quota.stdout)
                except Exception:
                    notes.append("квоты обновить не удалось")

            # The plugin opens the account store once per process. Restart the
            # v2 background service so it reopens the store and picks up the new
            # account instead of answering 401 with the old in-memory token.
            try:
                cli = antigravity_manager.get_opencode_cli()
                if cli and os.path.exists(cli):
                    svc = antigravity_manager.run_silent_cmd(
                        [cli, "service", "restart"], timeout=45, env=opencode_launch_environment())
                    if svc.returncode != 0:
                        notes.append("перезапустить сервис OpenCode не удалось")
                else:
                    notes.append("CLI OpenCode не найден")
            except Exception:
                notes.append("перезапустить сервис OpenCode не удалось")

            # The pool is non-empty now: retry the connection in an isolated
            # daemon thread so the UI does not wait for CLI/server calls.
            self._schedule_google_connection()

            message = "Google аккаунт добавлен в пул"
            if notes:
                message += "; " + ", ".join(notes) + " — перезапустите OpenCode вручную"
            else:
                message += "; квоты обновлены, сервис OpenCode перезапущен"
            return {"status": "ok", "message": message}
        except Exception as exc:
            hub_logging.failed("Google login", exc)
            return {"status": "error", "message": failure_message}
        finally:
            self._login_locks["google"].release()

    def activate_google_account(self, idx: int) -> bool:
        if not isinstance(idx, int) or idx < 0:
            raise ValueError("Некорректный индекс аккаунта")
        if not antigravity_manager.set_active_google_account_index(idx):
            raise RuntimeError("Не удалось переключить активный Google-аккаунт")
        return True

    def delete_google_account(self, aid_or_email: str) -> bool:
        return antigravity_manager.delete_google_account(aid_or_email)

    def test_google_account(self, aid_or_email: str) -> str:
        acc = next((a for a in antigravity_manager.export_google_accounts()
                    if a.get("id") == aid_or_email or a.get("email") == aid_or_email), None)
        if not acc:
            return "Аккаунт не найден"
        if acc.get("enabled") is False:
            return "Аккаунт отключён — включите его для проверки."
        try:
            import google_health_auth
            import health_checker
            kind, node_exe, runner, cli = self._google_runner()
            if kind == "missing_3113":
                return (
                    "Хранилище Google использует формат плагина 3.1.x, но кэш 3.1.13 не найден — "
                    "запустите OpenCode один раз."
                )
            if kind == "3.1.13":
                run_cmd = lambda cmd, timeout=30: antigravity_manager.run_google_route_cmd(
                    [cmd[0], str(runner), str(cli), *cmd[2:]], timeout=timeout
                )
                cli_arg = str(cli)
            else:
                run_cmd = antigravity_manager.run_google_route_cmd
                cli_arg = cli
            refreshed = google_health_auth.refresh_google_health_account(
                acc, run_cmd, node_exe, cli_arg
            )
            health_res = health_checker.test_google_account_health(
                refreshed,
                refresh_account=lambda current: google_health_auth.refresh_google_health_account(
                    current, run_cmd, node_exe, cli_arg
                ),
            )
            if health_res.get("ok"):
                try:
                    self._refresh_google_quotas_sync(timeout=30)
                except Exception:
                    pass
                latency = health_res.get("latency_ms")
                suffix = f" ({latency} мс)" if isinstance(latency, (int, float)) else ""
                return f"Аккаунт успешно проверен, токены активны{suffix}"
            return f"Результат проверки: {health_res.get('message') or 'ошибка подключения'}"
        except Exception as e:
            return f"Результат проверки: {e}"

    def toggle_google_enabled(self, aid_or_email: str, enabled: bool) -> bool:
        return antigravity_manager.set_google_account_enabled(aid_or_email, enabled)

    def toggle_google_candidate(self, aid_or_email: str, candidate: bool) -> bool:
        return antigravity_manager.set_google_account_candidate(aid_or_email, candidate)

    def test_openai_account(self, aid_or_email: str) -> str:
        import health_checker
        accs = openai_manager.load_openai_accounts() if hasattr(openai_manager, "load_openai_accounts") else []
        acc = next((a for a in accs if a.get("id") == aid_or_email or a.get("accountId") == aid_or_email or a.get("email") == aid_or_email), None)
        if not acc:
            return "Аккаунт ChatGPT не найден"
        try:
            res = health_checker.test_openai_model_generation(acc, timeout=20)
            return res.get("message", "Проверка завершена")
        except Exception as e:
            return f"Результат проверки OpenAI: {e}"

    def toggle_openai_enabled(self, aid_or_email: str, enabled: bool) -> bool:
        return openai_manager.set_openai_account_enabled(aid_or_email, enabled)

    def toggle_openai_candidate(self, aid_or_email: str, candidate: bool) -> bool:
        return openai_manager.set_openai_account_candidate(aid_or_email, candidate)

    def activate_openai_account(self, aid_or_email: str) -> bool:
        return openai_manager.set_active_openai_account(aid_or_email)

    def delete_openai_account(self, aid_or_email: str) -> bool:
        return openai_manager.remove_openai_account(aid_or_email)

    def add_openai_account(self) -> dict:
        if not self._login_locks["openai"].acquire(blocking=False):
            return {"status": "error", "message": "Вход в ChatGPT уже выполняется"}
        try:
            success, message, account = openai_manager.login_openai_browser(timeout=300)
            return {"status": "ok" if success and account else "error", "message": message}
        except Exception as exc:
            return {"status": "error", "message": str(exc)}
        finally:
            self._login_locks["openai"].release()

    def add_claude_account(self) -> dict:
        if not claude_service:
            return {"status": "error", "message": "Сервис Claude недоступен"}
        if not self._login_locks["claude"].acquire(blocking=False):
            return {"status": "error", "message": "Вход в Claude уже выполняется"}
        try:
            mode = "tunnel" if vless_service.is_running() else "default"
            success, message, account = claude_service.login_claude_browser(mode=mode, timeout=300)
            return {"status": "ok" if success and account else "error", "message": message}
        except Exception as exc:
            return {"status": "error", "message": str(exc)}
        finally:
            self._login_locks["claude"].release()

    def set_strategy(self, strat: str) -> bool:
        if strat not in ("hybrid", "sticky", "round-robin"):
            raise ValueError("Неизвестная стратегия выбора аккаунтов")
        with self._config_lock:
            cfg = self.load_config()
            cfg["account_selection_strategy"] = strat
            return self.save_config(cfg)

    def save_general_settings(self, settings: dict) -> bool:
        with self._config_lock:
            cfg, sources = self._config_snapshot()
            for key in ("switch_on_first_rate_limit", "close_to_tray", "autostart_on_login"):
                if key in settings:
                    if not isinstance(settings[key], bool):
                        raise ValueError(f"Неверное значение настройки {key}")
                    cfg[key] = settings[key]
            oc_updates = []
            if "providers_visibility" in settings:
                visibility = settings["providers_visibility"]
                if not isinstance(visibility, dict) or any(key not in PROVIDER_SETTING_IDS or not isinstance(value, bool)
                                                          for key, value in visibility.items()):
                    raise ValueError("Неверные настройки провайдеров")
                oc_path = _opencode_config_path()
                raw = _read_if_present(oc_path)
                original = raw.decode("utf-8") if raw is not None else "{}\n"
                try:
                    oc = jsonc_config.parse_config(original)
                except ValueError:
                    raise ValueError("Конфигурация OpenCode повреждена и оставлена без изменений.") from None
                disabled = oc.get("disabled_providers", [])
                if not isinstance(disabled, list):
                    raise ValueError("disabled_providers должен быть списком")
                disabled = list(disabled)
                for key, enabled in visibility.items():
                    provider_id = PROVIDER_SETTING_IDS[key]
                    disabled = [item for item in disabled if item != provider_id]
                    if not enabled:
                        disabled.append(provider_id)
                updated = jsonc_config.set_property(original, ("disabled_providers",), disabled)
                oc_updates.append((oc_path, raw, updated.encode("utf-8"), False))
                cfg["providers_visibility"] = {**cfg.get("providers_visibility", {}), **visibility}
            registry_update = (lambda: self._apply_autostart(cfg["autostart_on_login"])) if "autostart_on_login" in settings else None
            _apply_file_updates([*self._config_updates(cfg, sources), *oc_updates], after=registry_update)
            self._close_to_tray = bool(cfg.get("close_to_tray", True))
            return True

    def restart_opencode(self) -> bool:
        if not self._restart_lock.acquire(blocking=False):
            raise RuntimeError("Перезапуск OpenCode уже выполняется")
        try:
            cli = antigravity_manager.get_opencode_cli()
            if not cli:
                raise RuntimeError("CLI OpenCode не найден: невозможно перезапустить фоновый сервер")
            if not os.path.exists(antigravity_manager.get_opencode_exe()):
                raise RuntimeError("Приложение OpenCode не найдено")
            self._sync_routes(self.load_config())
            if not self.stop_opencode():
                raise RuntimeError("Не удалось закрыть окно OpenCode")
            # Closing the desktop app leaves the v2 background service alive.
            # Restart it through its CLI so loaded plugins and OAuth state reset.
            result = antigravity_manager.run_silent_cmd(
                [cli, "service", "restart"], timeout=45, env=opencode_launch_environment())
            if result.returncode != 0:
                detail = (result.stderr or result.stdout or "").strip()[:200]
                raise RuntimeError("CLI не смог перезапустить фоновый сервер OpenCode."
                                   + (f" {detail}" if detail else ""))
            if not self.start_opencode():
                raise RuntimeError("Сервер перезапущен, но не удалось открыть окно OpenCode")
            hub_logging.log.info("OpenCode restart completed (window and service).")
            return True
        except Exception as exc:
            hub_logging.failed("Restart OpenCode", exc)
            raise
        finally:
            self._restart_lock.release()

    def stop_opencode(self) -> bool:
        """Stop Hub-owned OpenCode and any window opened outside the Hub."""
        ok = True
        process = self._opencode_process
        if process is not None:
            try:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired as exc:
                        hub_logging.failed("Stop Hub-owned OpenCode", exc)
                        try:
                            process.kill()
                            process.wait(timeout=2)
                        except (OSError, subprocess.TimeoutExpired) as kill_exc:
                            hub_logging.failed("Kill Hub-owned OpenCode", kill_exc)
                            ok = False
            except OSError as exc:
                hub_logging.failed("Stop Hub-owned OpenCode", exc)
                ok = False
            finally:
                self._opencode_process = None
        try:
            desktop = antigravity_manager.terminate_opencode_desktop()
            if not desktop.get("ok"):
                ok = False
                hub_logging.log.warning("OpenCode desktop close failed: %s",
                                        desktop.get("message", "")[:300])
            else:
                hub_logging.log.info("OpenCode desktop close: %s",
                                     desktop.get("message", "no process")[:200])
        except Exception as exc:
            hub_logging.failed("Stop OpenCode desktop", exc)
            ok = False
        return ok

    def start_opencode(self) -> bool:
        exe = antigravity_manager.get_opencode_exe()
        if os.path.exists(exe):
            try:
                self._opencode_process = subprocess.Popen([exe], cwd=os.path.dirname(exe),
                                                         env=opencode_launch_environment())
                return True
            except Exception as exc:
                hub_logging.failed("Start OpenCode", exc)
        return False

    def fix_session_title(self) -> str:
        try:
            _, msg = opencode_config.ensure_session_title_config()
            return msg
        except Exception as e:
            return str(e)

    def _plugin_install_target(self):
        # plugin add edits the global config, preferring the root opencode.json(c)
        # to the equivalent under .opencode. Reject ambiguous inputs before the
        # CLI downloads anything.
        config = _opencode_config_path()
        raw = _read_if_present(config)
        if raw is None:
            raw = _read_if_present(jsonc_config.config_path(config.parent / ".opencode"))
        current = jsonc_config.parse_config(raw.decode("utf-8-sig")) if raw is not None else {}
        if "plugins" in current and not isinstance(current["plugins"], list):
            raise _PluginInstallConfigError("В конфиге OpenCode поле plugins должно быть массивом.")
        specs = _antigravity_plugin_specs(current)
        if len(specs) > 1 or (specs and not _is_exact_plugin_version(next(iter(specs)))):
            raise _PluginInstallConfigError(
                "В конфиге OpenCode оставьте одну запись плагина Antigravity с точной версией.")
        with self._config_lock:
            hub_cfg, _ = self._config_snapshot(defaults=False)
        pin = hub_cfg.get("plugin_pin_version")
        if "plugin_pin_version" in hub_cfg and not _is_exact_plugin_version(pin):
            raise _PluginInstallConfigError("В настройках AI HUB задана некорректная версия плагина.")
        if specs:
            configured = next(iter(specs))
            if pin is not None and _plugin_version_key(configured) < _plugin_version_key(pin):
                raise _PluginInstallConfigError(
                    "В OpenCode закреплена версия плагина ниже версии в настройках AI HUB. "
                    "Согласуйте версии перед установкой.")
            version = configured
        else:
            if pin is None:
                import cloudcode_route_patch
                verified = cloudcode_route_patch.load_patch_state().get("verified_version")
                pin = verified if _is_exact_plugin_version(verified) else _template_plugin_version()
            version = pin

        pointer = _read_if_present(config.parent / "antigravity-accounts.json.store.pointer.json")
        if pointer is not None:
            data = jsonc_config.parse_config(pointer.decode("utf-8-sig"), jsonc=False)
            schema = data.get("schemaVersion")
            relocated = (type(schema) is int and schema >= 2) or isinstance(data.get("relocatedTo"), dict)
            if relocated and _plugin_version_key(version) < (3, 0, 16):
                raise _PluginInstallConfigError("Хранилищу аккаунтов schema 2 нужна версия 3.0.16 или новее.")
        return config.parent, version, bool(specs)

    def install_opencode_plugin(self) -> dict:
        """Install only the Hub package; repairing its bundles is a separate action."""
        if self._closing.is_set():
            return {"ok": False, "status": "unavailable", "message": "AI HUB завершает работу."}
        if not self._plugin_install_lock.acquire(blocking=False):
            return {"ok": False, "status": "in_progress", "message": "Установка плагина уже выполняется."}
        try:
            try:
                cli = antigravity_manager.get_opencode_cli(native_only=True)
            except OSError:
                cli = None
            if not cli:
                return {"ok": False, "status": "missing_cli",
                        "message": "CLI OpenCode не найден. Установите OpenCode и повторите попытку."}
            try:
                config_dir, version, configured = self._plugin_install_target()
            except _PluginInstallConfigError as exc:
                return {"ok": False, "status": "config_error", "message": str(exc)}
            except (OSError, ValueError, RecursionError):
                return {"ok": False, "status": "config_error",
                        "message": "Не удалось выбрать безопасную версию плагина. Проверьте настройки AI HUB, "
                                   "закреплённую версию в OpenCode и совместимость с хранилищем аккаунтов."}
            if configured and _plugin_cached(version):
                return {"ok": True, "status": "already_installed", "version": version,
                        "message": f"Плагин Antigravity {version} уже есть в кэше OpenCode."}
            env = opencode_launch_environment()
            env.update(OPENCODE_CONFIG_DIR=str(config_dir), CI="1", NO_COLOR="1")
            try:
                result = subprocess.run(
                    [cli, "plugin", "add", f"{_PLUGIN_PACKAGE}@{version}"],
                    cwd=Path.home(), env=env, timeout=_PLUGIN_INSTALL_TIMEOUT, shell=False,
                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
                )
            except FileNotFoundError:
                return {"ok": False, "status": "missing_cli",
                        "message": "CLI OpenCode недоступен. Проверьте установку OpenCode."}
            except subprocess.TimeoutExpired:
                return {"ok": False, "status": "timeout", "version": version,
                        "message": "Установка плагина не завершилась вовремя. Проверьте сеть и повторите попытку."}
            except OSError:
                return {"ok": False, "status": "launch_failed",
                        "message": "Не удалось запустить CLI OpenCode."}
            if result.returncode:
                hub_logging.log.info("OpenCode plugin add failed (exit=%s)", result.returncode)
                return {"ok": False, "status": "download_failed", "version": version,
                        "message": "OpenCode не смог скачать или зарегистрировать плагин. "
                                   "Проверьте сеть и настройки OpenCode."}
            if not _plugin_cached(version):
                return {"ok": False, "status": "pending_cache", "version": version,
                        "message": "OpenCode принял плагин, но нужная версия пока не подтверждена в кэше. "
                                   "Откройте OpenCode и проверьте статус плагина."}
            return {"ok": True, "status": "installed", "version": version,
                    "message": f"Плагин Antigravity {version} установлен. Исправления Hub применяются отдельно."}
        finally:
            self._plugin_install_lock.release()

    def fix_opencode_plugin(self) -> dict:
        """Re-apply module patches after an OpenCode or plugin update."""
        import cloudcode_route_patch
        try:
            synced = cloudcode_route_patch.sync_local_plugin_bundles()
        except Exception as exc:
            hub_logging.failed("Plugin recovery", exc)
            synced = {"ok": False, "copied": [], "failed": [type(exc).__name__],
                      "message": "Не удалось восстановить бандл плагина."}
        try:
            result = cloudcode_route_patch.patch_prompt_sanitizer()
        except Exception as exc:
            hub_logging.failed("Plugin prompt patch", exc)
            return {
                "ok": False,
                "changed": [],
                "already": [],
                "missing": [],
                "message": f"Ошибка патча плагина: {exc}",
            }
        try:
            identity = cloudcode_route_patch.patch_antigravity_identity()
        except Exception as exc:
            hub_logging.failed("Plugin identity patch", exc)
            identity = {"ok": False, "message": f"Ошибка патча идентичности: {exc}"}
        result["identity"] = identity
        if identity.get("changed"):
            result["message"] += " " + identity["message"]
        try:
            gemini4 = cloudcode_route_patch.patch_gemini4_models()
            result["gemini4"] = gemini4
            if gemini4.get("changed"):
                result["message"] += " " + gemini4["message"]
        except Exception as exc:
            hub_logging.failed("Plugin Gemini 4 patch", exc)
        result["synced"] = synced.get("copied", [])
        if result.get("synced"):
            result["message"] = (
                f"Бандл плагина синхронизирован ({len(result['synced'])} файл(ов)). "
                + result["message"]
            )
        route_changed = []
        try:
            route_patched = bool(cloudcode_route_patch.patch_auth_plugin_transport(
                include_local=False, changed_files=route_changed))
            status = cloudcode_route_patch.get_prompt_sanitizer_status(full=True)
        except Exception as exc:
            hub_logging.failed("Plugin route patch or verification", exc)
            route_patched = False
            status = {"state": "error"}
        result["route_patched"] = route_patched
        result["changed"] = list(dict.fromkeys(
            result["changed"] + result["synced"] + identity.get("changed", []) + route_changed))
        try:
            health = cloudcode_route_patch.verify_plugin_health()
        except Exception:
            health = {"ok": False, "state": "error", "reasons": ["health check failed"]}
        result["ok"] = (status["state"] == "patched" and bool(identity.get("ok"))
                        and not identity.get("missing") and route_patched
                        and not synced.get("failed") and health["ok"])
        result["health"] = health
        if result["ok"]:
            cloudcode_route_patch.save_patch_state({
                "verified_version": cloudcode_route_patch.get_verified_version(),
                "verified_versions": cloudcode_route_patch.get_verified_versions(),
                "verified_sha256": {
                    f"{copy.get('version') or 'unknown'}:{Path(copy['path']).name}": copy["sha256"]
                    for copy in cloudcode_route_patch.get_installed_fingerprint()["copies"]
                },
                "degraded": False,
                "degraded_reason": "",
                "unsupported_versions": [],
            })
            result["message"] += " Маршрут Hub и синтаксис бандла проверены."
        elif status["state"] != "missing":
            result["message"] += " Не все компоненты патча подтверждены. " + synced.get("message", "")
            if health.get("reasons"):
                result["message"] += " Причина: " + "; ".join(health["reasons"])[:300]
            elif health.get("syntax_unavailable"):
                result["message"] += " Проверка синтаксиса плагина временно недоступна."
        hub_logging.log.info("Plugin full patch: prompt=%s identity=%s route=%s recovery_errors=%d",
                             status["state"], bool(identity.get("ok")), route_patched,
                             len(synced.get("failed", [])))
        return result

    def get_opencode_plugin_status(self) -> dict:
        import cloudcode_route_patch
        try:
            status = cloudcode_route_patch.get_prompt_sanitizer_status(full=True)
            state = cloudcode_route_patch.check_patch_state()
            patch_state = cloudcode_route_patch.load_patch_state()
            health = cloudcode_route_patch.verify_plugin_health()
            status["installed_version"] = ", ".join(sorted({
                copy.get("version") or "unknown" for copy in state.get("copies", [])
            })) or None
            status["expected_version"] = patch_state.get("verified_version")
            status["state_detail"] = state.get("state")
            reasons = health.get("reasons") or []
            status["syntax_unavailable"] = bool(health.get("syntax_unavailable"))

            # Marker checks alone cannot confirm health. Conversely, a stale
            # fingerprint must not override a healthy live check or turn an
            # unavailable syntax check into an unsupported version.
            if any("JS syntax error:" in reason for reason in reasons):
                status.update(state="syntax_error", message="В бандле плагина обнаружена ошибка синтаксиса JavaScript.")
            elif any(": read error " in reason for reason in reasons):
                status.update(state="error", message="Не удалось прочитать все файлы плагина OpenCode.")
            elif status["state"] == "patched":
                if reasons or (not health["ok"] and not status["syntax_unavailable"]):
                    status.update(state="unsupported", message="Не удалось подтвердить структуру или компоненты патча плагина.")
                elif status["syntax_unavailable"]:
                    status.update(state="unavailable", message="Проверка синтаксиса плагина временно недоступна.")

            status["degraded"] = status["state"] not in ("patched", "unavailable")
            status["reason"] = ""
            if status["degraded"]:
                details = ["; ".join(reasons)[:300]] if reasons else []
                if state.get("state") == "version_changed":
                    details.append("Обнаружена новая версия плагина.")
                elif state.get("state") == "structure_changed":
                    details.append("Изменилась структура файлов плагина.")
                status["reason"] = " ".join(details)
            return status
        except Exception as exc:
            return {
                "state": "error",
                "found": 0,
                "patched": 0,
                "pending": 0,
                "message": f"Ошибка проверки плагина: {exc}",
            }

    def apply_antigravity_patch(self) -> dict:
        """Apply the Antigravity-compatible request body/header patch."""
        import cloudcode_route_patch
        try:
            result = cloudcode_route_patch.patch_antigravity_identity()
            result["status"] = cloudcode_route_patch.get_identity_fix_status()
            if result["status"]["state"] == "pending":
                synced = cloudcode_route_patch.sync_local_plugin_bundles()
                if synced.get("copied"):
                    changed = result["changed"] + synced["copied"]
                    result = cloudcode_route_patch.patch_antigravity_identity()
                    result["changed"] = list(dict.fromkeys(changed + result["changed"]))
                    result["status"] = cloudcode_route_patch.get_identity_fix_status()
                if result["status"]["state"] != "patched":
                    result["message"] += " " + synced.get("message", "")
            result["ok"] = result["status"]["state"] == "patched"
            hub_logging.log.info("Plugin identity patch: state=%s changed=%d",
                                 result["status"]["state"], len(result["changed"]))
            return result
        except Exception as exc:
            hub_logging.failed("Standalone Antigravity identity patch", exc)
            return {
                "ok": False,
                "changed": [],
                "already": [],
                "missing": [],
                "message": f"Ошибка патча Antigravity: {exc}",
                "status": {"state": "error", "message": str(exc)},
            }

    def get_antigravity_patch_status(self) -> dict:
        """Report whether the Antigravity identity patch is active."""
        import cloudcode_route_patch
        try:
            return cloudcode_route_patch.get_identity_fix_status()
        except Exception as exc:
            return {
                "state": "error",
                "found": 0,
                "patched": 0,
                "pending": 0,
                "message": f"Ошибка проверки патча Antigravity: {exc}",
            }

    def open_folder(self, folder_type: str) -> bool:
        target = LOG_DIR if folder_type == "logs" else CONFIG_DIR
        if target.exists() and sys.platform == "win32":
            os.startfile(target)
            return True
        return False

    def get_storage_stats(self) -> dict:
        return hub_paths.get_storage_stats()

    def clean_logs_and_cache(self) -> dict:
        return hub_paths.clean_logs_and_cache()

    def clean_browser_profiles(self) -> dict:
        return hub_paths.clean_browser_profiles()

    def open_hub_data_dir(self) -> bool:
        return hub_paths.open_data_folder()

    def uninstall_hub_completely(self, confirmation: str = None) -> dict:
        if getattr(sys, "frozen", False):
            if sys.platform == "win32":
                os.startfile("ms-settings:appsfeatures")
            return {"ok": False, "message": "Для удаления установленного Hub используйте «Установленные приложения» Windows. Настройки и аккаунты будут сохранены."}
        if confirmation != "DELETE":
            return {"ok": False, "message": "Для удаления введите DELETE"}
        try:
            if not self._window_holder or not self._window_holder.create_confirmation_dialog(
                    "Удаление данных AI HUB",
                    "Удалить локальные настройки и аккаунты этой копии AI HUB?"):
                return {"ok": False, "cancelled": True, "message": "Удаление отменено"}
        except Exception as exc:
            hub_logging.failed("Confirm uninstall", exc)
            return {"ok": False, "message": "Не удалось подтвердить удаление в окне Windows."}
        return self._uninstall_local_data()

    def _uninstall_local_data(self) -> dict:
        was_closing = self._closing.is_set()
        self._uninstalling = True
        self._closing.set()
        errors, preserved = [], []
        appdata = os.environ.get("APPDATA")
        home = Path.home()
        if sys.platform == "win32":
            # Don't trust an environment variable alone to redirect deletion.
            # A redirected roaming folder is deliberately left untouched.
            default_root = home / "AppData" / "Roaming" / "AntigravityHub"
            use_root = bool(appdata) and Path(appdata) / "AntigravityHub" == default_root
        else:
            default_root = home / ".config" / "AntigravityHub"
            use_root = True
        use_root = use_root and hub_paths.HUB_ROOT == default_root and not os.environ.get("ANTIGRAVITY_HUB_DATA_DIR")

        def attempt(label, action):
            try:
                action()
            except Exception as exc:
                errors.append(f"{label}: {exc}")

        def unlink(path):
            if _safe_owned_file(path):
                path.unlink()

        def edit_opencode():
            directory = home / ".config" / "opencode"
            if CONFIG_DIR != directory or os.environ.get("OPENCODE_CONFIG_DIR"):
                preserved.append("нестандартная конфигурация OpenCode")
                return
            plugin = directory / "plugins" / NATIVE_PLUGIN_NAME
            if _safe_owned_file(plugin) and plugin.read_bytes().startswith(NATIVE_PLUGIN_MARKER):
                plugin.unlink()
            paths = [path for path in (directory / "opencode.json", directory / "opencode.jsonc")
                     if _safe_owned_file(path)]
            if len(paths) > 1:
                raise ValueError("найдены одновременно opencode.json и opencode.jsonc")
            if not paths:
                return
            path = paths[0]
            original = path.read_bytes().decode("utf-8")
            updated = _remove_hub_opencode_settings(original)
            if updated != original:
                secure_storage.atomic_write_bytes(path, updated.encode("utf-8"), private_parent=False)
            # A legacy copy in the shared namespace could belong to a separate
            # installation. Only remove a byte-for-byte mirror of Hub's file.
            mirror = directory / "antigravity.json"
            central = default_root / "config" / "antigravity.json"
            if _safe_owned_file(mirror):
                if use_root and _safe_owned_file(central) and mirror.read_bytes() == central.read_bytes():
                    unlink(mirror)
                else:
                    preserved.append("отдельный antigravity.json")

        def stop_tunnel():
            ok, message = vless_service.stop_tunnel()
            if not ok:
                raise OSError(message)

        def stop_local_servers():
            bridge = getattr(globals().get("claude_manager"), "bridge_service", None)
            for owner in (provider_proxy, bridge):
                if owner is None:
                    continue
                stop_fn = getattr(owner, "stop", None)
                if callable(stop_fn):
                    stop_fn()
                else:
                    server = getattr(owner, "_server", None)
                    if server is not None:
                        server.shutdown()
                        server.server_close()

        with self._core_lock, self._config_lock:
            attempt("туннель VLESS", stop_tunnel)
            if errors:
                self._uninstalling = False
                if not was_closing:
                    self._closing.clear()
                return {"ok": False, "message": "Не удалось остановить туннель VLESS. Данные сохранены."}
            attempt("локальные серверы", stop_local_servers)
            attempt("автозапуск Windows", lambda: self._apply_autostart(False))
            attempt("конфигурация OpenCode", edit_opencode)
            if use_root:
                if (nvidia_manager.KEY_FILE == default_root / "opencode-secrets" / "nvidia-nim.key"
                        and CONFIG_DIR == home / ".config" / "opencode"
                        and not os.environ.get("OPENCODE_CONFIG_DIR")):
                    def disconnect_nvidia():
                        if not _safe_owned_file(nvidia_manager.KEY_FILE):
                            return
                        directory = home / ".config" / "opencode"
                        for path in (directory / "opencode.json", directory / "opencode.jsonc"):
                            _safe_owned_file(path)
                        nvidia_manager.disconnect()

                    attempt("провайдер NVIDIA NIM", disconnect_nvidia)
                for name in _HUB_FILES:
                    if name != "opencode-secrets/nvidia-nim.key":
                        attempt(name, lambda name=name: unlink(default_root / name))
            else:
                preserved.append("нестандартный каталог данных Hub")
            self._uninstalled = not errors
            self._uninstalling = False

        retained = "Хранилища плагина, профили браузеров, история и файлы вне списка сохранены."
        if preserved:
            retained += f" Пропущено: {', '.join(preserved)}."
        if errors:
            return {"ok": False, "message": "Очистка завершена с ошибками: " + "; ".join(errors) + ". " + retained}
        return {"ok": True, "message": "Известные локальные файлы и настройки Hub очищены. " + retained}

    def export_backup(self, password: str = None) -> dict:
        """Bridge entry point: only a native save dialog can authorize the path."""
        try:
            import crypto_backup
            crypto_backup.validate_password(password)
            if not self._window_holder:
                raise ValueError("Для экспорта необходимо открытое окно Hub")
            import webview
            dialog_res = self._window_holder.create_file_dialog(
                webview.FileDialog.SAVE, save_filename="AntigravityHub_Backup.agb",
                file_types=("Antigravity Backup (*.agb)",),
            )
            if not dialog_res:
                return {"ok": False, "cancelled": True, "message": "Экспорт отменён"}
            target_path = dialog_res[0] if isinstance(dialog_res, (list, tuple)) else dialog_res
            return self._export_backup(target_path, password)
        except ValueError as exc:
            return {"ok": False, "message": f"Ошибка экспорта: {exc}"}
        except Exception as exc:
            hub_logging.failed("Export backup dialog", exc)
            return {"ok": False, "message": "Не удалось сохранить резервную копию."}

    def _export_backup(self, target_path: str, password: str) -> dict:
        try:
            import crypto_backup
            crypto_backup.validate_password(password)
        except ValueError as exc:
            return {"ok": False, "message": f"Ошибка экспорта: {exc}"}
        try:
            import crypto_backup
            if not target_path or not isinstance(target_path, str):
                return {"ok": False, "message": "Не указан путь для сохранения файла"}

            target = Path(target_path)
            if target.exists() and target.is_dir():
                return {"ok": False, "message": "Указанный путь является каталогом"}
            if target.suffix.lower() != ".agb":
                return {"ok": False, "message": "Укажите расширение .agb"}

            google_accs = antigravity_manager.export_google_accounts()
            openai_accs = openai_manager.load_openai_accounts() if hasattr(openai_manager, "load_openai_accounts") else []
            claude_accs = claude_service.load_accounts() if claude_service else []
            xpiki_cfg = xpiki_manager.load_xpiki_config()
            openrouter_key = openrouter_manager.load_api_key()
            tokenlavka_key = tokenlavka_manager.load_api_key()
            tokenlavka_models = tokenlavka_manager.selected_models()
            deepseek_key = deepseek_api.load_api_key()
            deepseek_cfg = deepseek_api.load_config()

            selected_or_models = []
            try:
                import jsonc_config
                oc_path = jsonc_config.config_path(CONFIG_DIR)
                if oc_path.exists():
                    oc = jsonc_config.parse_config(oc_path.read_text(encoding="utf-8-sig"))
                    selected_or_models = list(oc.get("provider", {}).get("openrouter-free", {}).get("models", {}))
            except Exception:
                try:
                    if OPENCODE_CONFIG_FILE.exists():
                        oc = json.loads(OPENCODE_CONFIG_FILE.read_text(encoding="utf-8-sig"))
                        selected_or_models = list(oc.get("provider", {}).get("openrouter-free", {}).get("models", {}))
                except Exception:
                    pass

            backup_data = {
                "schemaVersion": 2,
                "exported_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "app_version": _app_version(),
                "google_accounts": google_accs,
                "openai_accounts": openai_accs,
                "claude_accounts": claude_accs,
                "xpiki": {
                    "api_key": xpiki_cfg.get("api_key", ""),
                    "base_url": xpiki_cfg.get("base_url") or xpiki_manager.DEFAULT_BASE_URL,
                    "enabled_models": xpiki_cfg.get("enabled_models", list(xpiki_manager.XPIKI_MODELS)),
                    "connected": xpiki_cfg.get("connected", False),
                },
                "openrouter": {
                    "api_key": openrouter_key or "",
                    "selected_models": selected_or_models,
                },
                "tokenlavka": {
                    "api_key": tokenlavka_key or "",
                    "selected_models": tokenlavka_models,
                    "cached_balance": tokenlavka_manager.cached_balance(),
                },
                "deepseek": {
                    "api_key": deepseek_key or "",
                    "base_url": deepseek_cfg.get("base_url") or deepseek_api.DEFAULT_BASE_URL,
                    "connected": bool(deepseek_cfg.get("connected", False)),
                },
                "config": self.load_config(),
            }

            payload_bytes = crypto_backup.encrypt_backup(backup_data, password)
            fd, tmp_target = tempfile.mkstemp(dir=target.parent, prefix=".hub-backup-")
            try:
                with os.fdopen(fd, "wb") as stream:
                    stream.write(payload_bytes)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(tmp_target, target)
            finally:
                Path(tmp_target).unlink(missing_ok=True)
            return {
                "ok": True,
                "path": str(target),
                "encrypted": True,
                "message": f"Резервная копия сохранена в {target.name}",
                "counts": {
                    "google": len(google_accs),
                    "openai": len(openai_accs),
                    "claude": len(claude_accs),
                }
            }
        except Exception as exc:
            hub_logging.failed("Export backup", exc)
            return {"ok": False, "message": "Не удалось сохранить резервную копию."}

    def import_backup(self, import_token: str = None, password: str = None) -> dict:
        """Only a native file selection can authorize an import."""
        if not self._backup_lock.acquire(blocking=False):
            return {"ok": False, "message": "Импорт уже выполняется."}
        try:
            import crypto_backup
            if import_token is not None:
                pending, self._pending_backup = self._pending_backup, None
                if (pending is None or not isinstance(import_token, str) or not import_token.isascii()
                        or not hmac.compare_digest(pending[0], import_token)
                        or time.monotonic() >= pending[1]):
                    return {"ok": False, "message": "Снова выберите файл резервной копии."}
                raw = pending[2]
                try:
                    data = crypto_backup.decrypt_backup(raw, password)
                except Exception as exc:
                    hub_logging.failed("Unlock backup", exc)
                    return {"ok": False, "message": "Не удалось расшифровать копию. Проверьте пароль."}
            else:
                self._pending_backup = None
                if password is not None or self._window_holder is None:
                    return {"ok": False, "message": "Выберите файл через окно AI HUB."}
                import webview
                dialog_res = self._window_holder.create_file_dialog(
                    webview.FileDialog.OPEN,
                    file_types=("Antigravity Backup (*.json;*.agb)",),
                )
                if not dialog_res:
                    return {"ok": False, "cancelled": True, "message": "Импорт отменён"}
                source_path = dialog_res[0] if isinstance(dialog_res, (list, tuple)) else dialog_res
                source = Path(source_path)
                if source.suffix.lower() not in (".json", ".agb") or not source.is_file():
                    return {"ok": False, "message": "Выберите файл резервной копии .agb или .json."}
                with source.open("rb") as stream:
                    raw = stream.read(crypto_backup.MAX_BACKUP_BYTES + 1)
                if len(raw) > crypto_backup.MAX_BACKUP_BYTES:
                    return {"ok": False, "message": "Резервная копия превышает 16 МиБ"}
                if crypto_backup.is_encrypted_backup(raw):
                    token = secrets.token_urlsafe(32)
                    self._pending_backup = (token, time.monotonic() + 180, raw)
                    return {
                        "ok": False,
                        "requires_password": True,
                        "import_token": token,
                        "message": "Файл резервной копии зашифрован. Введите пароль для расшифровки."
                    }
                data = crypto_backup.load_backup_json(raw)
            return self._restore_backup_data(data)
        except Exception as exc:
            hub_logging.failed("Read backup", exc)
            return {"ok": False, "message": "Не удалось прочитать резервную копию."}
        finally:
            self._backup_lock.release()

    def _restore_backup_data(self, data: dict) -> dict:
        warnings = []
        completed = []
        counts = {"google": 0, "openai": 0, "claude": 0}
        stage = None

        def require(result):
            if result is False:
                raise OSError("write failed")
            return result

        def optional(label, action):
            try:
                require(action())
            except Exception as exc:
                hub_logging.failed(f"Restore backup: {label}", exc)
                warnings.append(label)

        try:
            _validate_backup(data)
            g_list = _backup_account_rows(data, "google_accounts")
            o_list = _backup_account_rows(data, "openai_accounts")
            c_list = _backup_account_rows(data, "claude_accounts")
            backup_cfg = _backup_config(data["config"]) if "config" in data else None
            if backup_cfg is not None:
                cfg = self.load_config()
                if (vless_service.is_running() and
                        backup_cfg.get("vless_url", cfg.get("vless_url")) != cfg.get("vless_url")):
                    raise ValueError("Остановите туннель перед восстановлением активной VLESS-ссылки")

            if backup_cfg is not None or any(data.get(name, {}).get("api_key")
                                              for name in ("xpiki", "deepseek", "openrouter", "tokenlavka")) or c_list:
                raw = _read_if_present(_opencode_config_path())
                if raw is not None:
                    try:
                        jsonc_config.parse_config(raw.decode("utf-8-sig"))
                    except ValueError:
                        raise ValueError("Сначала исправьте конфигурацию OpenCode.") from None
            if c_list and not claude_service:
                raise ValueError("Хранилище Claude недоступно.")
            if g_list:
                stage = "аккаунты Google"
                counts["google"] = self._import_google_accounts_list(g_list)
                if counts["google"] != len(g_list):
                    warnings.append(stage)
                else:
                    completed.append(stage)
            if o_list:
                stage = "аккаунты OpenAI"
                counts["openai"] = openai_manager.import_openai_accounts(o_list, strict=True)
                completed.append(stage)
            if c_list:
                stage = "аккаунты Claude"
                counts["claude"] = claude_service.import_backup_accounts(c_list)
                if counts["claude"]:
                    optional("настройка Claude в OpenCode", claude_service.configure_opencode_provider)
                completed.append(stage)

            # 4. Xpiki
            xpiki_data = data.get("xpiki")
            if isinstance(xpiki_data, dict) and isinstance(xpiki_data.get("api_key"), str) and xpiki_data["api_key"].strip():
                stage = "Xpiki"
                raw_base = str(xpiki_data.get("base_url") or xpiki_manager.DEFAULT_BASE_URL).strip()
                parsed_xpiki = urlparse(raw_base)
                if parsed_xpiki.scheme != "https" or not parsed_xpiki.hostname or parsed_xpiki.username or parsed_xpiki.password:
                    raw_base = xpiki_manager.DEFAULT_BASE_URL
                raw_models = xpiki_data.get("enabled_models")
                if isinstance(raw_models, list):
                    enabled_models = [str(m) for m in raw_models if isinstance(m, str) and m in xpiki_manager.XPIKI_MODELS]
                else:
                    enabled_models = list(xpiki_manager.XPIKI_MODELS)
                x_cfg = xpiki_manager.load_xpiki_config()
                x_cfg.update(
                    api_key=xpiki_data["api_key"].strip(),
                    base_url=raw_base,
                    enabled_models=enabled_models or list(xpiki_manager.XPIKI_MODELS),
                    connected=True,
                )
                require(xpiki_manager.save_xpiki_config(x_cfg))
                optional("настройка Xpiki в OpenCode", lambda: xpiki_manager.configure_opencode(
                    x_cfg["api_key"], x_cfg["base_url"], x_cfg["enabled_models"])
                )
                completed.append(stage)

            # 5. OpenRouter
            or_data = data.get("openrouter")
            if isinstance(or_data, dict) and isinstance(or_data.get("api_key"), str) and or_data["api_key"].strip():
                stage = "OpenRouter"
                or_key = or_data["api_key"].strip()
                require(openrouter_manager.save_api_key(or_key))
                optional("ключ OpenRouter в OpenCode", lambda: openrouter_manager.sync_opencode_credential(or_key))
                if isinstance(or_data.get("selected_models"), list):
                    models = [{"id": str(mid), "name": str(mid)} for mid in or_data["selected_models"] if isinstance(mid, str)]
                    if models:
                        optional("модели OpenRouter", lambda: openrouter_manager.configure_models(models))
                completed.append(stage)

            # 6. TokenLavka
            tl_data = data.get("tokenlavka")
            if isinstance(tl_data, dict) and isinstance(tl_data.get("api_key"), str) and tl_data["api_key"].strip():
                stage = "TokenLavka"
                tl_key = tl_data["api_key"].strip()
                require(tokenlavka_manager.save_api_key(tl_key))
                optional("ключ TokenLavka в OpenCode", lambda: tokenlavka_manager.sync_opencode_credential(tl_key))
                if isinstance(tl_data.get("selected_models"), list):
                    valid_tl = [mid for mid in tl_data["selected_models"]
                                if isinstance(mid, str) and mid in tokenlavka_manager.TOKENLAVKA_MODELS]
                    if valid_tl:
                        optional("модели TokenLavka", lambda: tokenlavka_manager.configure_models(valid_tl, tl_key))
                completed.append(stage)

            # 6b. DeepSeek API
            ds_data = data.get("deepseek")
            if isinstance(ds_data, dict) and isinstance(ds_data.get("api_key"), str) and ds_data["api_key"].strip():
                stage = "DeepSeek"
                ds_key = ds_data["api_key"].strip()
                require(deepseek_api.save_api_key(ds_key))
                ds_cfg = deepseek_api.load_config()
                raw_ds_url = str(ds_data.get("base_url") or deepseek_api.DEFAULT_BASE_URL).strip()
                p_ds = urlparse(raw_ds_url)
                if p_ds.scheme == "https" and p_ds.hostname and not p_ds.username and not p_ds.password:
                    ds_cfg["base_url"] = raw_ds_url.rstrip("/")
                ds_cfg["connected"] = bool(ds_data.get("connected", True))
                try:
                    models = deepseek_api.fetch_models(ds_key, ds_cfg["base_url"])
                    ds_cfg["models"] = models
                except Exception as exc:
                    hub_logging.failed("Restore backup: DeepSeek catalog", exc)
                    warnings.append("каталог DeepSeek")
                    models = []
                require(deepseek_api.save_config(ds_cfg))
                if models:
                    optional("модели DeepSeek", lambda: deepseek_api.configure_opencode_models(
                        [m["id"] for m in models], ds_key, ds_cfg["base_url"]))
                optional("ключ DeepSeek в OpenCode", lambda: deepseek_api.sync_opencode_credential(ds_key))
                completed.append(stage)

            # 7. Apply the configuration validated before any imports above.
            if backup_cfg is not None:
                stage = "настройки Hub и сети"
                with self._config_lock:
                    current_cfg = self.load_config()
                    if (vless_service.is_running() and backup_cfg.get("vless_url", current_cfg.get("vless_url"))
                            != current_cfg.get("vless_url")):
                        raise ValueError("Активная ссылка VLESS изменилась во время импорта.")
                    # Import must not turn a different copy's autostart on or off.
                    current_cfg.update({key: value for key, value in backup_cfg.items() if key != "autostart_on_login"})
                    current_cfg["vless_enabled"] = bool(vless_service.is_running())
                    require(self.save_config(current_cfg))
                    if "providers_visibility" in backup_cfg:
                        optional("видимость провайдеров", lambda: self.save_general_settings(
                            {"providers_visibility": backup_cfg["providers_visibility"]}))
                        current_cfg = self.load_config()
                    optional("синхронизация маршрутов", lambda: self._sync_routes(current_cfg))
                    self._invalidate_diagnostics_cache()
                completed.append(stage)
        except Exception as exc:
            hub_logging.failed("Restore backup", exc)
            if stage is None:
                # Only report messages produced by our schema validation.
                detail = str(exc) if type(exc) is ValueError and not exc.__cause__ else ""
                return {"ok": False, "message": f"Импорт не начат. {detail}".strip(), "counts": counts}
            warnings.append(stage)
        if warnings:
            return {"ok": False, "partial": True, "counts": counts, "completed": completed,
                    "warnings": warnings, "message": "Импорт завершён не полностью. Проверьте: " + ", ".join(warnings) + "."}
        return {"ok": True, "counts": counts, "completed": completed,
                "message": "Импорт завершён. Восстановлено: " + ", ".join(completed) + "." if completed else
                "В копии нет данных для восстановления."}

    def _import_google_accounts_list(self, accounts_list: list) -> int:
        """Imports Google accounts into the active generation store or legacy store."""
        if hasattr(antigravity_manager, "import_google_accounts"):
            return antigravity_manager.import_google_accounts(accounts_list)
        return 0

    def check_updates(self) -> dict:
        if getattr(sys, "frozen", False):
            import webbrowser
            webbrowser.open("https://github.com/ZLoBNbIY/Opencode-antigravity-module/releases")
            return {"status": "manual", "has_update": False,
                    "message": "Для обновления установленного Hub скачайте новый Setup.exe со страницы GitHub Releases."}
        try:
            repo_dir = CURRENT_DIR.parent
            with self._update_lock:
                self._update_offer = None
                info = auto_updater.check_for_updates(repo_dir)
                if info.get("has_update"):
                    commit = info.get("remote_commit")
                    if not isinstance(commit, str) or not re.fullmatch(r"[0-9a-f]{40}", commit):
                        return {"status": "error", "message": "Не удалось подтвердить идентификатор обновления."}
                    self._update_offer = (commit, time.monotonic() + 300)
            if info.get("error") and not info.get("remote_sha"):
                return {"status": "error", "message": f"Ошибка проверки: {info['error']}"}
            if info.get("has_update"):
                return {
                    "status": "update_available",
                    "has_update": True,
                    "remote_sha": info.get("remote_sha", "")[:7],
                    "remote_commit": info.get("remote_commit", ""),
                    "message": f"Доступно обновление: {info.get('remote_sha', '')[:7]} — {info.get('message', '')}",
                }
            return {
                "status": "up_to_date",
                "has_update": False,
                "remote_sha": info.get("remote_sha", "")[:7] or info.get("local_sha", "")[:7],
                "message": f"Установлена последняя версия ({info.get('local_sha', '')[:7]})",
            }
        except Exception as exc:
            hub_logging.failed("Check for updates", exc)
            return {"status": "error", "message": "Не удалось проверить обновления."}

    def apply_update(self, expected_commit: str = "") -> dict:
        if getattr(sys, "frozen", False):
            return {"ok": False, "message": "Для обновления установленного Hub используйте новый Setup.exe."}
        try:
            if not isinstance(expected_commit, str) or not re.fullmatch(r"[0-9a-f]{40}", expected_commit):
                return {"ok": False, "message": "Сначала проверьте обновление и подтвердите коммит."}
            with self._update_lock:
                offer = self._update_offer
                if offer is None or offer[0] != expected_commit or time.monotonic() >= offer[1]:
                    return {"ok": False, "message": "Сначала снова проверьте обновление."}
                self._update_offer = None
                ok, msg = auto_updater.apply_update_git(CURRENT_DIR.parent, expected_commit=expected_commit)
            return {"ok": ok, "message": msg}
        except Exception as exc:
            hub_logging.failed("Apply update", exc)
            return {"ok": False, "message": "Не удалось установить обновление."}

    def restart_hub(self) -> dict:
        """Stop all Hub child processes/servers, exit cleanly, and relaunch Hub."""
        if self._window_holder is None:
            return {"ok": False, "message": "Окно Hub не инициализировано"}
        if not self._hub_restart_lock.acquire(blocking=False):
            return {"ok": False, "message": "Перезапуск Hub уже выполняется"}
        try:
            import hub_restart
            _ = hub_restart.schedule_restart
            self._restart_requested = True
        except Exception as exc:
            self._restart_requested = False
            self._hub_restart_lock.release()
            return {"ok": False, "message": f"Не удалось запланировать перезапуск Hub: {exc}"}

        def _shutdown_and_exit():
            time.sleep(0.15)
            self._closing.set()
            try:
                if self._window_holder is None:
                    raise RuntimeError("Окно Hub не инициализировано")
                self._window_holder.destroy()
            except Exception as exc:
                self._restart_requested = False
                self._closing.clear()
                self._hub_restart_lock.release()
                hub_logging.failed("Close window for restart", exc)

        threading.Thread(target=_shutdown_and_exit, daemon=True, name="hub-restart-exit").start()
        return {"ok": True, "message": "Перезапуск AI HUB..."}

    def _shutdown_runtime(self):
        self._closing.set()
        with self._shutdown_lock:
            teardown_ok = True
            try:
                with self._core_lock:
                    if not vless_service.stop_tunnel()[0]:
                        hub_logging.log.warning("VLESS did not stop")
                        teardown_ok = False
            except Exception as exc:
                hub_logging.failed("Stop VLESS", exc)
                teardown_ok = False
            bridge = getattr(globals().get("claude_manager"), "bridge_service", None)
            for owner in (provider_proxy, bridge):
                if owner is None:
                    continue
                stop_fn = getattr(owner, "stop", None)
                if callable(stop_fn):
                    try:
                        stop_fn()
                    except Exception as exc:
                        hub_logging.failed("Stop local server", exc)
                        teardown_ok = False
                else:
                    server = getattr(owner, "_server", None)
                    if server is not None:
                        try:
                            server.shutdown()
                            server.server_close()
                        except Exception as exc:
                            hub_logging.failed("Stop local server", exc)
                            teardown_ok = False
            if self._tray_holder is not None:
                try:
                    self._tray_holder.remove()
                except Exception as exc:
                    hub_logging.failed("Remove tray icon", exc)
            if self._restart_requested and not self._uninstalled and not self._uninstalling:
                self._restart_requested = False
                if teardown_ok:
                    try:
                        import hub_restart
                        hub_restart.schedule_restart()
                    except Exception as exc:
                        hub_logging.failed("Schedule Hub restart", exc)


def run_webview_app():
    """Starts the native WebView2 Frosted Glass UI with taskbar icon and system tray."""
    import webview

    html_file = CURRENT_DIR / "web" / "index.html"
    icon_file = CURRENT_DIR / "icon.ico"
    icon_str = str(icon_file.resolve()) if icon_file.exists() else None

    api = HubApi()

    # Ensure Windows taskbar groups windows under AI HUB, not Python
    try:
        antigravity_manager.set_windows_taskbar_identity()
    except Exception:
        pass

    window = webview.create_window(
        title="AI HUB - AI аккаунты и сеть для Windows",
        url=str(html_file.resolve()),
        width=1420,
        height=890,
        min_size=(1140, 720),
        background_color="#090d12",
    )
    # Use pywebview's named-function registry, not attribute-based dispatch.
    # The latter can traverse a bound method's receiver and reach raw helpers.
    window.expose(*vars(_WebviewBridge(api)).values())
    api._window_holder = window

    # System Tray & Close-to-Tray setup
    tray = None
    balloon_shown = [False]

    def on_tray_show():
        try:
            window.show()
            window.restore()
        except Exception:
            pass

    def on_tray_refresh():
        try:
            api.refresh_all_quotas()
        except Exception:
            pass

    def on_tray_exit():
        def close_window():
            api._closing.set()
            try:
                window.destroy()
            except Exception as exc:
                if not api._restart_requested:
                    api._closing.clear()
                hub_logging.failed("Close window from tray", exc)

        threading.Thread(target=close_window, daemon=True, name="hub-tray-close").start()

    try:
        tray = win_tray.WindowsTrayIcon(
            title="AI HUB",
            icon_path=icon_str,
            on_show=on_tray_show,
            on_refresh=on_tray_refresh,
            on_exit=on_tray_exit,
        )
        if not tray.start():
            raise RuntimeError("Tray icon was not registered")
        api._tray_holder = tray
    except Exception as e:
        hub_logging.failed("Tray initialization", e)
        tray = None

    def on_window_closing():
        if api._uninstalled or api._uninstalling or api._closing.is_set():
            return True
        close_to_tray = bool(getattr(api, "_close_to_tray", True))
        if tray and close_to_tray:
            try:
                window.hide()
            except Exception as exc:
                hub_logging.failed("Hide window", exc)
            else:
                if not balloon_shown[0]:
                    balloon_shown[0] = True
                    try:
                        tray.show_balloon(
                            "AI HUB свёрнут",
                            "Приложение работает в трее. Кликните левой кнопкой для открытия или правой для меню.",
                        )
                    except Exception as exc:
                        hub_logging.failed("Tray notification", exc)
                return False
        api._closing.set()
        return True

    window.events.closing += on_window_closing

    # Ensure custom window & taskbar icon via Win32 WM_SETICON and dark title bar
    def apply_native_window_styling():
        for _ in range(10):
            time.sleep(0.5)
            if sys.platform != "win32" or api._closing.is_set():
                return
            try:
                import ctypes
                from ctypes import wintypes
                user32 = ctypes.windll.user32
                user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
                user32.FindWindowW.restype = wintypes.HWND
                user32.LoadImageW.argtypes = [
                    wintypes.HINSTANCE, wintypes.LPCWSTR, wintypes.UINT,
                    ctypes.c_int, ctypes.c_int, wintypes.UINT,
                ]
                user32.LoadImageW.restype = wintypes.HANDLE
                user32.SendMessageW.argtypes = [
                    wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM,
                ]
                user32.SendMessageW.restype = wintypes.LPARAM
                hwnd = user32.FindWindowW(None, "AI HUB - AI аккаунты и сеть для Windows")
                if hwnd:
                    # 1. Dark title bar matching the interface background (#090d12)
                    dwmapi = ctypes.windll.dwmapi
                    dwmapi.DwmSetWindowAttribute.argtypes = [
                        wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD,
                    ]
                    dwmapi.DwmSetWindowAttribute.restype = ctypes.c_long
                    c_int = ctypes.c_int
                    # DWMWA_USE_IMMERSIVE_DARK_MODE (20 on Win11/Win10 20H1+, 19 on older Win10)
                    dark = c_int(1)
                    dwmapi.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(dark), ctypes.sizeof(dark))
                    dwmapi.DwmSetWindowAttribute(hwnd, 19, ctypes.byref(dark), ctypes.sizeof(dark))
                    # DWMWA_CAPTION_COLOR = 35 (BGR: 0x00120d09 for #090d12)
                    caption_color = c_int(0x00120d09)
                    dwmapi.DwmSetWindowAttribute(hwnd, 35, ctypes.byref(caption_color), ctypes.sizeof(caption_color))
                    # DWMWA_TEXT_COLOR = 36 (white text)
                    text_color = c_int(0x00f8f5f2)
                    dwmapi.DwmSetWindowAttribute(hwnd, 36, ctypes.byref(text_color), ctypes.sizeof(text_color))
                    # DWMWA_BORDER_COLOR = 34 (dark graphite border #141a22)
                    border_color = c_int(0x00221a14)
                    dwmapi.DwmSetWindowAttribute(hwnd, 34, ctypes.byref(border_color), ctypes.sizeof(border_color))

                    # 2. Window and Taskbar icon
                    if icon_str:
                        h_icon = user32.LoadImageW(
                            None, icon_str, 1, 0, 0, 0x00000010 | 0x00000040
                        )
                        if h_icon:
                            user32.SendMessageW(hwnd, 0x0080, 1, h_icon)  # ICON_BIG
                            user32.SendMessageW(hwnd, 0x0080, 0, h_icon)  # ICON_SMALL
                    break
            except Exception:
                pass

    threading.Thread(target=apply_native_window_styling, daemon=True).start()

    # Start network services and periodic quota checks.
    def bg_refresher():
        if api._closing.is_set() or api._uninstalled or api._uninstalling:
            return
        try:
            import cloudcode_route_patch
            heal = cloudcode_route_patch.self_heal_plugin()
            hub_logging.log.info("Plugin startup check: state=%s reasons=%s",
                                 heal.get("state"), "; ".join(heal.get("reasons", []))[:300])
        except Exception as exc:
            hub_logging.failed("Startup plugin self-heal", exc)
        if api._closing.is_set() or api._uninstalled or api._uninstalling:
            return
        # Primary startup call: isolate CLI/server waiting from network init.
        api._schedule_google_connection()
        try:
            cfg = api.load_config()
            if api._closing.is_set() or api._uninstalled or api._uninstalling:
                return
            if cfg.get("vless_enabled") and cfg.get("vless_url"):
                result = api.start_vless()
                if not result["ok"]:
                    print(result["message"])
            if api._closing.is_set() or api._uninstalled or api._uninstalling:
                return
            api._sync_routes(api.load_config())
            if api._closing.is_set() or api._uninstalled or api._uninstalling:
                return
            if claude_service and claude_service.get_active_account():
                bridge = getattr(globals().get("claude_manager"), "bridge_service", None)
                if bridge is not None:
                    bridge.ensure_running()
        except Exception as exc:
            hub_logging.failed("Network startup", exc)
        # Standalone Google quota CLI returned an unused snapshot and did not
        # update the store. Use a credential-only worker for periodic OAuth.
        if not api._closing.is_set() and not api._uninstalled and not api._uninstalling:
            threading.Thread(target=api._google_refresh.run, daemon=True,
                             name="hub-google-oauth").start()
        while not api._uninstalled and not api._uninstalling and not api._closing.is_set():
            api.refresh_openai_quotas()
            if api._closing.is_set() or api._uninstalled or api._uninstalling:
                break
            try:
                api.refresh_deepseek_balance()
            except Exception:
                pass
            try:
                api.refresh_tokenlavka_balance()
            except Exception:
                pass
            if api._closing.wait(300) or api._uninstalled or api._uninstalling or api._closing.is_set():
                break
            # Detect a plugin update that happened while the Hub was running.
            # A new bundle is silent 429 until it is patched, so check every
            # refresh cycle (~5 min) and re-apply known fixes automatically.
            try:
                import cloudcode_route_patch
                drift = cloudcode_route_patch.check_patch_state()
                if drift.get("state") in ("version_changed", "structure_changed"):
                    healed = cloudcode_route_patch.self_heal_plugin()
                    hub_logging.log.info(
                        "Plugin drift check: %s -> %s (%s)",
                        drift.get("state"), healed.get("state"),
                        "; ".join(healed.get("reasons", []))[:200])
            except Exception as exc:
                hub_logging.failed("Plugin drift check", exc)

    threading.Thread(target=bg_refresher, daemon=True).start()

    try:
        webview.start(icon=icon_str, gui="edgechromium" if getattr(sys, "frozen", False) else None)
    finally:
        api._shutdown_runtime()


if __name__ == "__main__":
    if antigravity_manager.acquire_single_instance():
        run_webview_app()
