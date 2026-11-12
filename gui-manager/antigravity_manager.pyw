"""Antigravity Hub WebView2 application entry point and shared backend helpers."""

import os
import sys
import json
import math
import hashlib
import time
import datetime
import subprocess
import uuid
import secrets
from pathlib import Path
import shutil

sys.path.insert(0, str(Path(__file__).resolve().parent))
import openai_manager
import win_tray
import health_checker
from google_health_auth import refresh_google_health_account
import auto_updater
import crypto_backup
from vless_manager import vless_service, get_http_port, get_active_proxy
from claude_manager import claude_service, CLAUDE_MODELS
import xpiki_manager
import opencode_config

# Keep the Windows mutex handle alive for the lifetime of this process.
_SINGLE_INSTANCE_MUTEX = None


def acquire_single_instance():
    """Return False when another Antigravity Hub instance already owns the mutex."""
    global _SINGLE_INSTANCE_MUTEX
    if sys.platform != "win32":
        return True
    try:
        import ctypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
        kernel32.CreateMutexW.restype = ctypes.c_void_p
        ctypes.set_last_error(0)
        handle = kernel32.CreateMutexW(None, True, "Local\\AntigravityHub.SingleInstance")
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())
        if ctypes.get_last_error() == 183:  # ERROR_ALREADY_EXISTS
            kernel32.CloseHandle(handle)
            return False
        _SINGLE_INSTANCE_MUTEX = handle
        return True
    except Exception as e:
        # Fail closed: do not risk launching a second Hub if the mutex cannot be checked.
        print(f"Could not acquire Antigravity Hub single-instance mutex: {e}")
        return False


def set_windows_taskbar_identity():
    """Give taskbar windows a Hub identity instead of Python's default identity."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        result = ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("AntigravityHub.Desktop")
        if result != 0:
            raise OSError(f"SetCurrentProcessExplicitAppUserModelID failed: 0x{result & 0xffffffff:08X}")
    except Exception as exc:
        print(f"Could not set Antigravity Hub taskbar identity: {exc}")


# --- Paths & Dynamic Resolution ---
def get_node_executable():
    node = shutil.which("node")
    if node and os.path.exists(node):
        return node
    candidates = [
        Path("C:/Program Files/nodejs/node.exe"),
        Path("C:/Program Files (x86)/nodejs/node.exe"),
        Path.home() / "AppData/Local/Programs/cursor/resources/app/resources/helpers/node.exe",
        Path.home() / "AppData/Local/Programs/DeepSeek Harness/resources/runtime/primary-runtime/dependencies/node/bin/node.exe",
        Path.home() / "AppData/Local/Programs/Python/Python312/Lib/site-packages/playwright/driver/node.exe",
        Path.home() / "AppData/Local/Programs/Python/Python311/Lib/site-packages/playwright/driver/node.exe",
    ]
    for c in candidates:
        if c.exists():
            return str(c)
    return "node"

def get_cli_js():
    local_cli = Path(__file__).resolve().parent.parent / "plugin" / "dist" / "cli.js"
    if local_cli.exists():
        return str(local_cli)

    npm_dir = Path.home() / ".cache" / "opencode" / "npm"
    if npm_dir.exists():
        matches = list(npm_dir.glob("**/@cortexkit/opencode-antigravity-auth/dist/cli.js"))
        if matches and matches[0].exists():
            return str(matches[0])
        matches_multi = list(npm_dir.glob("**/opencode-antigravity-multi-auth/dist/cli.js"))
        if matches_multi and matches_multi[0].exists():
            return str(matches_multi[0])

    cache_cli = Path.home() / ".cache" / "opencode" / "packages" / "@cortexkit" / "opencode-antigravity-auth@latest" / "node_modules" / "@cortexkit" / "opencode-antigravity-auth" / "dist" / "cli.js"
    if cache_cli.exists():
        return str(cache_cli)
    return str(local_cli)

def get_opencode_exe():
    candidates = [
        # Current installer layout (OpenCode Desktop >= 2.2)
        Path.home() / "AppData" / "Local" / "Programs" / "ai.opencode.desktop" / "OpenCode.exe",
        Path.home() / "AppData" / "Local" / "Programs" / "@opencodedesktop" / "OpenCode.exe",
        Path.home() / "AppData" / "Local" / "Programs" / "@opencode-desktop" / "OpenCode.exe",
        Path.home() / "AppData" / "Local" / "Programs" / "@opencode-aidesktop" / "OpenCode.exe",
        Path.home() / "AppData" / "Local" / "Programs" / "opencode" / "OpenCode.exe",
    ]
    for c in candidates:
        if c.exists():
            return str(c)
    which_opencode = shutil.which("opencode")
    if which_opencode:
        return which_opencode
    which_opencode_cap = shutil.which("OpenCode")
    if which_opencode_cap:
        return which_opencode_cap
    return str(candidates[0])

def get_opencode_cli():
    """Locates opencode-cli.exe: next to the desktop app, in the Roaming CLI cache, or on PATH."""
    candidates = [Path(get_opencode_exe()).parent / "resources" / "opencode-cli.exe"]
    roaming_cli = Path.home() / "AppData" / "Roaming" / "ai.opencode.desktop" / "cli"
    if roaming_cli.exists():
        candidates.extend(sorted(roaming_cli.glob("*/opencode-cli.exe"), reverse=True))
    path_cli = shutil.which("opencode-cli") or shutil.which("opencode")
    if path_cli:
        candidates.append(Path(path_cli))
    for c in candidates:
        if c.is_file():
            return str(c)
    return None

def cleanup_opencode_locks():
    try:
        state_dir = Path(os.path.expanduser("~/.local/state/opencode"))
        if state_dir.exists():
            for f in state_dir.glob("service.json*"):
                try:
                    f.unlink()
                except Exception:
                    pass
    except Exception:
        pass

NODE_EXE = get_node_executable()
CLI_JS = get_cli_js()
CONFIG_FILE = Path(os.path.expanduser(r"~/.config/opencode/antigravity.json"))
OPENCODE_EXE = get_opencode_exe()
LOG_DIR = Path(os.path.expanduser(r"~/.local/share/opencode/log"))
CONFIG_DIR = Path(os.path.expanduser(r"~/.config/opencode"))


def open_url_in_browser(url: str) -> bool:
    """Reliably opens a URL in the user's default browser on Windows and other platforms."""
    try:
        if sys.platform == "win32":
            os.startfile(url)
            return True
    except Exception:
        pass
    try:
        import webbrowser
        return webbrowser.open(url)
    except Exception as e:
        print(f"Error opening browser for {url}: {e}")
        return False

DEFAULT_CONFIG = {
    "$schema": "https://raw.githubusercontent.com/cortexkit/opencode-antigravity-auth/main/schema.json",
    "account_selection_strategy": "hybrid",
    "soft_quota_threshold_percent": 100,
    "switch_on_first_rate_limit": True,
    "max_account_switches": 10,
    "quota_style_fallback": True,
    "debug": False,
    "theme_mode": "dark",
    "vless_enabled": False,
    "vless_url": "",
    "vless_core_path": None,
    "vless_kill_switch": True,
    "vless_http_port": 10879,
    "vless_socks_port": 10878,
    "providers_visibility": {
        "antigravity": True,
        "openai": True,
        "claude": True,
        "openrouter": True,
        "xpiki": True,
    },
    "close_to_tray": True,
    "max_rate_limit_wait_seconds": 300,
}

def run_silent_cmd(cmd, timeout=30, env=None):
    flags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
    startupinfo = None
    if sys.platform == "win32":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = subprocess.SW_HIDE
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            timeout=timeout,
            creationflags=flags,
            startupinfo=startupinfo,
            env=env,
        )
        stdout_str = proc.stdout.decode("utf-8", errors="replace") if proc.stdout else ""
        stderr_str = proc.stderr.decode("utf-8", errors="replace") if proc.stderr else ""
    except Exception as e:
        return type("SilentResult", (), {"returncode": 1, "stdout": "", "stderr": str(e)})()

    return type("SilentResult", (), {"returncode": proc.returncode, "stdout": stdout_str, "stderr": stderr_str})()


def provider_route_environment():
    """Environment for helper CLIs that fetch provider models or quotas."""
    import provider_proxy
    return provider_proxy.proxy_environment()


def run_google_route_cmd(cmd, timeout=30):
    return run_silent_cmd(cmd, timeout=timeout, env=provider_route_environment())


def get_active_google_account_index() -> int:
    config_dir = Path(os.path.expanduser("~/.config/opencode"))
    gen_dirs = list(config_dir.glob("*.generation"))
    if gen_dirs:
        cfg_file = gen_dirs[0] / "config.json"
        if cfg_file.exists():
            try:
                cfg = json.loads(cfg_file.read_text(encoding="utf-8"))
                routing = cfg.get("antigravityRouting", {})
                accounts = cfg.get("accounts", [])
                # Check active row for gemini first, then general activeRow
                active_row_id = (
                    routing.get("activeRowByFamily", {}).get("gemini", {}).get("id")
                    or routing.get("activeRow", {}).get("id")
                )
                if active_row_id:
                    for i, acc in enumerate(accounts):
                        if acc.get("id") == active_row_id:
                            return i
                idx = routing.get("activeIndexByFamily", {}).get("gemini")
                if idx is not None and 0 <= int(idx) < len(accounts):
                    return int(idx)
                idx = routing.get("activeIndex")
                if idx is not None and 0 <= int(idx) < len(accounts):
                    return int(idx)
            except Exception:
                pass
    legacy_file = config_dir / "antigravity-accounts.json"
    if legacy_file.exists():
        try:
            data = json.loads(legacy_file.read_text(encoding="utf-8"))
            return int(data.get("activeIndex", 0))
        except Exception:
            pass
    return 0


def set_active_google_account_index(target_index: int) -> bool:
    config_dir = Path(os.path.expanduser("~/.config/opencode"))
    gen_dirs = list(config_dir.glob("*.generation"))
    changed = False
    if gen_dirs:
        cfg_file = gen_dirs[0] / "config.json"
        if cfg_file.exists():
            try:
                cfg = json.loads(cfg_file.read_text(encoding="utf-8"))
                accounts = cfg.get("accounts", [])
                if 0 <= target_index < len(accounts):
                    target_id = accounts[target_index].get("id")
                    routing = cfg.get("antigravityRouting", {})
                    routing["activeIndex"] = target_index
                    routing["activeIndexByFamily"] = {"claude": target_index, "gemini": target_index}
                    if target_id:
                        routing["activeRow"] = {"id": target_id, "credentialEpoch": 1}
                        routing["activeRowByFamily"] = {
                            "claude": {"id": target_id, "credentialEpoch": 1},
                            "gemini": {"id": target_id, "credentialEpoch": 1},
                        }
                    # Ensure selected account is enabled in commonAuthPool
                    rows = cfg.get("commonAuthPool", {}).get("rows", {})
                    if target_id in rows:
                        rows[target_id]["enabled"] = True
                        rows[target_id]["usable"] = True
                    accounts[target_index]["enabled"] = True
                    accounts[target_index]["candidate"] = True

                    cfg["antigravityRouting"] = routing
                    cfg_file.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
                    changed = True
            except Exception as e:
                print(f"Error updating generation config: {e}")

    legacy_file = config_dir / "antigravity-accounts.json"
    if legacy_file.exists():
        try:
            legacy_data = json.loads(legacy_file.read_text(encoding="utf-8"))
            legacy_data["activeIndex"] = target_index
            if "activeIndexByFamily" in legacy_data:
                legacy_data["activeIndexByFamily"] = {"claude": target_index, "gemini": target_index}
            legacy_file.write_text(json.dumps(legacy_data, indent=2, ensure_ascii=False), encoding="utf-8")
            changed = True
        except Exception:
            pass

    return changed


def set_google_account_candidate(target_email_or_id: str, candidate: bool) -> bool:
    """Persists account auto-rotation candidate flag without disabling the account itself."""
    config_dir = Path(os.path.expanduser("~/.config/opencode"))
    gen_dirs = list(config_dir.glob("*.generation"))
    changed = False

    if gen_dirs:
        gen_dir = gen_dirs[0]
        cfg_file = gen_dir / "config.json"
        state_file = gen_dir / "state.json"
        if cfg_file.exists():
            try:
                cfg = json.loads(cfg_file.read_text(encoding="utf-8"))
                target_id = None

                if state_file.exists():
                    try:
                        state = json.loads(state_file.read_text(encoding="utf-8"))
                        for aid, st in state.get("accounts", {}).items():
                            meta = st.get("commonAuthProviderState", {}).get("metadata", {})
                            if aid == target_email_or_id or meta.get("email") == target_email_or_id:
                                target_id = aid
                                break
                    except Exception:
                        pass

                if not target_id:
                    for acc in cfg.get("accounts", []):
                        if acc.get("id") == target_email_or_id or acc.get("email") == target_email_or_id:
                            target_id = acc.get("id")
                            break

                if target_id:
                    rows = cfg.get("commonAuthPool", {}).get("rows", {})
                    if target_id in rows:
                        rows[target_id]["usable"] = candidate
                    for acc in cfg.get("accounts", []):
                        if acc.get("id") == target_id:
                            acc["candidate"] = candidate

                    cfg_file.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
                    changed = True
            except Exception as e:
                print(f"Error updating candidate in generation config: {e}")

    legacy_file = config_dir / "antigravity-accounts.json"
    if legacy_file.exists():
        try:
            legacy_data = json.loads(legacy_file.read_text(encoding="utf-8"))
            for acc in legacy_data.get("accounts", []):
                if acc.get("id") == target_email_or_id or acc.get("email") == target_email_or_id:
                    acc["candidate"] = candidate
                    changed = True
            if changed:
                legacy_file.write_text(json.dumps(legacy_data, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass

    return changed


def set_google_account_enabled(target_email_or_id: str, enabled: bool) -> bool:
    """Persists account enabled/disabled state to commonAuthPool and config."""
    config_dir = Path(os.path.expanduser("~/.config/opencode"))
    gen_dirs = list(config_dir.glob("*.generation"))
    changed = False

    if gen_dirs:
        gen_dir = gen_dirs[0]
        cfg_file = gen_dir / "config.json"
        state_file = gen_dir / "state.json"
        if cfg_file.exists():
            try:
                cfg = json.loads(cfg_file.read_text(encoding="utf-8"))
                target_id = None

                if state_file.exists():
                    try:
                        state = json.loads(state_file.read_text(encoding="utf-8"))
                        for aid, st in state.get("accounts", {}).items():
                            meta = st.get("commonAuthProviderState", {}).get("metadata", {})
                            if aid == target_email_or_id or meta.get("email") == target_email_or_id:
                                target_id = aid
                                break
                    except Exception:
                        pass

                if not target_id:
                    for acc in cfg.get("accounts", []):
                        if acc.get("id") == target_email_or_id or acc.get("email") == target_email_or_id:
                            target_id = acc.get("id")
                            break

                if target_id:
                    rows = cfg.get("commonAuthPool", {}).get("rows", {})
                    current_cand = True
                    for acc in cfg.get("accounts", []):
                        if acc.get("id") == target_id:
                            current_cand = acc.get("candidate", True)
                            acc["enabled"] = enabled
                            break

                    if target_id in rows:
                        rows[target_id]["enabled"] = enabled
                        rows[target_id]["usable"] = enabled and current_cand

                    cfg_file.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
                    changed = True

                    if state_file.exists():
                        try:
                            state = json.loads(state_file.read_text(encoding="utf-8"))
                            if target_id in state.get("accounts", {}):
                                meta = state["accounts"][target_id].setdefault("commonAuthProviderState", {}).setdefault("metadata", {})
                                meta["enabled"] = enabled
                                state_file.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
                        except Exception:
                            pass
            except Exception as e:
                print(f"Error updating enabled in generation config: {e}")

    legacy_file = config_dir / "antigravity-accounts.json"
    if legacy_file.exists():
        try:
            legacy_data = json.loads(legacy_file.read_text(encoding="utf-8"))
            for acc in legacy_data.get("accounts", []):
                if acc.get("id") == target_email_or_id or acc.get("email") == target_email_or_id:
                    acc["enabled"] = enabled
                    changed = True
            if changed:
                legacy_file.write_text(json.dumps(legacy_data, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass

    return changed

def export_google_accounts() -> list[dict]:
    config_dir = Path(os.path.expanduser("~/.config/opencode"))
    gen_dirs = list(config_dir.glob("*.generation"))
    accounts = []
    if gen_dirs:
        gen_dir = gen_dirs[0]
        cfg_file = gen_dir / "config.json"
        state_file = gen_dir / "state.json"
        if cfg_file.exists() and state_file.exists():
            try:
                cfg = json.loads(cfg_file.read_text(encoding="utf-8"))
                state = json.loads(state_file.read_text(encoding="utf-8"))
                for acc in cfg.get("accounts", []):
                    aid = acc.get("id")
                    st = state.get("accounts", {}).get(aid, {})
                    meta = st.get("commonAuthProviderState", {}).get("metadata", {})
                    email = meta.get("email")
                    refresh = st.get("refresh")
                    if email and refresh:
                        accounts.append({
                            "id": aid,
                            "email": email,
                            "refreshToken": refresh,
                            "accessToken": st.get("access", ""),
                            "expires": st.get("expires", 0),
                            "projectId": meta.get("projectId", "aicode-consumers"),
                            "addedAt": meta.get("addedAt") or acc.get("addedAt"),
                            "label": meta.get("label", ""),
                            "enabled": meta.get("enabled", True),
                            "fingerprint": meta.get("fingerprint"),
                        })
            except Exception as e:
                print(f"Error reading generation accounts: {e}")

    legacy_file = config_dir / "antigravity-accounts.json"
    if not accounts and legacy_file.exists():
        try:
            data = json.loads(legacy_file.read_text(encoding="utf-8"))
            accounts = data.get("accounts", [])
        except Exception:
            pass

    return accounts

def get_active_google_health_account():
    """Match the stored active row by ID; exported rows can omit incomplete accounts."""
    accounts = export_google_accounts()
    index = get_active_google_account_index()
    generations = list((Path.home() / ".config" / "opencode").glob("*.generation"))
    if generations and (generations[0] / "config.json").exists():
        config = json.loads((generations[0] / "config.json").read_text(encoding="utf-8"))
        rows = config.get("accounts", [])
        if 0 <= index < len(rows):
            active_id = rows[index].get("id")
            return next((account for account in accounts if account.get("id") == active_id), None)
        return None
    return accounts[index] if 0 <= index < len(accounts) else None


def delete_google_account(target_email_or_id: str) -> bool:
    config_dir = Path(os.path.expanduser("~/.config/opencode"))
    gen_dirs = list(config_dir.glob("*.generation"))
    deleted = False

    if gen_dirs:
        gen_dir = gen_dirs[0]
        cfg_file = gen_dir / "config.json"
        state_file = gen_dir / "state.json"
        if cfg_file.exists() and state_file.exists():
            try:
                cfg = json.loads(cfg_file.read_text(encoding="utf-8"))
                state = json.loads(state_file.read_text(encoding="utf-8"))
                target_id = None
                for acc in cfg.get("accounts", []):
                    aid = acc.get("id")
                    st = state.get("accounts", {}).get(aid, {})
                    email = st.get("commonAuthProviderState", {}).get("metadata", {}).get("email")
                    if aid == target_email_or_id or email == target_email_or_id:
                        target_id = aid
                        break

                if target_id:
                    cfg["accounts"] = [a for a in cfg.get("accounts", []) if a.get("id") != target_id]
                    if "commonAuthPool" in cfg and "rows" in cfg["commonAuthPool"]:
                        cfg["commonAuthPool"]["rows"].pop(target_id, None)

                    routing = cfg.get("antigravityRouting", {})
                    active_row_id = routing.get("activeRow", {}).get("id")
                    remaining = cfg.get("accounts", [])
                    if active_row_id == target_id:
                        if remaining:
                            new_id = remaining[0]["id"]
                            routing["activeIndex"] = 0
                            routing["activeIndexByFamily"] = {"claude": 0, "gemini": 0}
                            routing["activeRow"] = {"id": new_id, "credentialEpoch": 1}
                            routing["activeRowByFamily"] = {
                                "claude": {"id": new_id, "credentialEpoch": 1},
                                "gemini": {"id": new_id, "credentialEpoch": 1},
                            }
                        else:
                            routing["activeIndex"] = 0
                            routing["activeRow"] = None
                    else:
                        for i, a in enumerate(remaining):
                            if a.get("id") == active_row_id:
                                routing["activeIndex"] = i
                                routing["activeIndexByFamily"] = {"claude": i, "gemini": i}
                                break
                    cfg["antigravityRouting"] = routing
                    cfg_file.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")

                    if "accounts" in state:
                        state["accounts"].pop(target_id, None)
                    state_file.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
                    deleted = True
            except Exception as e:
                print(f"Error deleting account: {e}")

    legacy_file = config_dir / "antigravity-accounts.json"
    if legacy_file.exists():
        try:
            legacy_data = json.loads(legacy_file.read_text(encoding="utf-8"))
            old_accounts = legacy_data.get("accounts", [])
            new_accounts = [
                a for a in old_accounts
                if a.get("email") != target_email_or_id and a.get("id") != target_email_or_id
            ]
            if len(new_accounts) != len(old_accounts):
                legacy_data["accounts"] = new_accounts
                cur_idx = legacy_data.get("activeIndex", 0)
                if cur_idx >= len(new_accounts):
                    legacy_data["activeIndex"] = max(0, len(new_accounts) - 1)
                legacy_file.write_text(json.dumps(legacy_data, indent=2, ensure_ascii=False), encoding="utf-8")
                deleted = True
        except Exception:
            pass

    return deleted

def enrich_google_accounts_with_generation_store(accounts: list[dict]) -> list[dict]:
    config_dir = Path(os.path.expanduser("~/.config/opencode"))
    gen_dirs = list(config_dir.glob("*.generation"))
    if not gen_dirs:
        return accounts

    cfg_p = gen_dirs[0] / "config.json"
    state_p = gen_dirs[0] / "state.json"
    if not (cfg_p.exists() and state_p.exists()):
        return accounts

    try:
        cfg = json.loads(cfg_p.read_text(encoding="utf-8"))
        state = json.loads(state_p.read_text(encoding="utf-8"))
    except Exception:
        return accounts

    disk_accounts = []
    for idx, acc in enumerate(cfg.get("accounts", []), start=1):
        aid = acc.get("id")
        row = cfg.get("commonAuthPool", {}).get("rows", {}).get(aid, {})
        meta = state.get("accounts", {}).get(aid, {}).get("commonAuthProviderState", {}).get("metadata", {})
        email = meta.get("email", f"Account {idx}")
        added_at = meta.get("addedAt") or acc.get("addedAt")
        cached = row.get("quota", {}).get("cachedQuota", {})

        groups = []
        for g_name in ["gemini", "non-gemini"]:
            g_data = cached.get(g_name)
            if not g_data or not isinstance(g_data, dict):
                continue
            rem_frac = g_data.get("remainingFraction")
            rem_pct = round(rem_frac * 100, 1) if rem_frac is not None else None
            windows = []
            for w in g_data.get("windows", []):
                w_frac = w.get("remainingFraction")
                windows.append({
                    "window": w.get("window"),
                    "remainingPercent": round(w_frac * 100, 1) if w_frac is not None else None,
                    "resetTime": w.get("resetTime"),
                })
            groups.append({
                "name": g_name,
                "remainingPercent": rem_pct,
                "resetTime": g_data.get("resetTime"),
                "windows": windows,
            })

        is_enabled = row.get("enabled", True)
        is_candidate = acc.get("candidate", row.get("usable", is_enabled))
        disk_accounts.append({
            "index": idx,
            "id": aid,
            "email": email,
            "addedAt": added_at,
            "enabled": is_enabled,
            "status": "ok" if is_enabled else "disabled",
            "candidate": is_candidate,
            "groups": groups,
        })

    if not accounts:
        return disk_accounts

    for idx, acc in enumerate(accounts):
        account_id = acc.get("id") or acc.get("accountId")
        email = (acc.get("email") or "").strip().lower()
        disk_acc = next(
            (
                item for item in disk_accounts
                if (account_id and item.get("id") == account_id)
                or (email and item.get("email", "").strip().lower() == email)
            ),
            None,
        )
        # Older CLI output omits stable identifiers; only then use its ordering.
        if disk_acc is None and not account_id and not email and idx < len(disk_accounts):
            disk_acc = disk_accounts[idx]
        if disk_acc:
            acc["enabled"] = disk_acc.get("enabled", True)
            acc["candidate"] = disk_acc.get("candidate", True)
            acc["status"] = disk_acc.get("status", "ok")
            if not acc.get("email") or acc.get("email", "").startswith("Account "):
                acc["email"] = disk_acc["email"]
            if not acc.get("addedAt"):
                acc["addedAt"] = disk_acc.get("addedAt")
            if not acc.get("id"):
                acc["id"] = disk_acc.get("id")

            if not acc.get("groups"):
                acc["groups"] = disk_acc.get("groups", [])
            else:
                for g in acc.get("groups", []):
                    g_name = g.get("name")
                    if not g.get("windows"):
                        matching_dg = next((dg for dg in disk_acc.get("groups", []) if dg.get("name") == g_name), None)
                        if matching_dg and matching_dg.get("windows"):
                            g["windows"] = matching_dg["windows"]

    return accounts

def repair_legacy_google_account_file(config_dir=None) -> str | None:
    """Normalize known legacy credential metadata before the plugin migration."""
    config_dir = Path(config_dir) if config_dir else Path(os.path.expanduser("~/.config/opencode"))
    legacy_file = config_dir / "antigravity-accounts.json"
    if not legacy_file.exists():
        return None
    try:
        data = json.loads(legacy_file.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return f"Не удалось прочитать файл аккаунтов Google: {exc}"
    if not isinstance(data, dict) or not isinstance(data.get("accounts"), list):
        return "Файл аккаунтов Google имеет неизвестный формат; он оставлен без изменений."

    changed = False
    for index, account in enumerate(data["accounts"]):
        if not isinstance(account, dict):
            return f"Запись Google-аккаунта #{index + 1} имеет неверный формат; файл оставлен без изменений."

        # Older Hub exports wrapped provider fields in `metadata`. The current
        # migration expects a flat legacy row and rejects credential material
        # inside provider metadata. Preserve non-credential fields, but never
        # copy access tokens into the new metadata shape.
        nested = account.get("metadata")
        if nested is not None:
            if not isinstance(nested, dict):
                return f"Metadata записи Google-аккаунта #{index + 1} имеет неверный формат; файл оставлен без изменений."
            nested_refresh = nested.get("refreshToken") or nested.get("refresh")
            if not account.get("refreshToken") and isinstance(nested_refresh, str) and nested_refresh:
                account["refreshToken"] = nested_refresh
            for key, value in nested.items():
                if key not in {"refreshToken", "refresh", "accessToken", "access", "expires", "apiKey"}:
                    account.setdefault(key, value)
            del account["metadata"]
            changed = True

        if not account.get("refreshToken"):
            alias = account.get("refresh")
            if isinstance(alias, str) and alias:
                account["refreshToken"] = alias
                changed = True
        if not isinstance(account.get("refreshToken"), str) or not account["refreshToken"]:
            return f"У записи Google-аккаунта #{index + 1} отсутствует refresh token; файл оставлен без изменений."

        # Access tokens are short-lived. The plugin refreshes them using the
        # refresh token and accepts credentials only in its credential field.
        for key in ("accessToken", "access", "refresh", "expires", "apiKey"):
            if key in account:
                del account[key]
                changed = True

        added_at = account.get("addedAt")
        if not isinstance(added_at, (int, float)) or isinstance(added_at, bool) or not math.isfinite(added_at):
            account["addedAt"] = int(time.time() * 1000)
            changed = True
        last_used = account.get("lastUsed")
        if not isinstance(last_used, (int, float)) or isinstance(last_used, bool) or not math.isfinite(last_used):
            account["lastUsed"] = 0
            changed = True
    if not changed:
        return None

    backup = legacy_file.with_name(
        legacy_file.name + ".pre-repair-" + datetime.datetime.now().strftime("%Y%m%d-%H%M%S-%f") + ".bak"
    )
    temporary = legacy_file.with_name(legacy_file.name + "." + secrets.token_hex(6) + ".tmp")
    try:
        shutil.copy2(legacy_file, backup)
        temporary.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        os.replace(temporary, legacy_file)
    except OSError as exc:
        temporary.unlink(missing_ok=True)
        return f"Не удалось исправить файл аккаунтов Google: {exc}"
    return None


def compute_google_credential_digest(refresh_token: str) -> str:
    secret = f"oauth\x00{refresh_token}"
    return hashlib.sha256(f"credential-stamp\x00{secret}".encode("utf-8")).hexdigest()


def compute_google_dispatch_digest(access_token: str | None, refresh_token: str, expires: int | float | None) -> str:
    parts = [
        "oauth",
        access_token if isinstance(access_token, str) and access_token else None,
        refresh_token,
        int(expires) if isinstance(expires, (int, float)) and math.isfinite(expires) and expires > 0 else None
    ]
    parts_json = json.dumps(parts, separators=(',', ':'))
    return hashlib.sha256(f"credential-dispatch\x00{parts_json}".encode("utf-8")).hexdigest()


def get_active_generation_dir(config_dir: Path) -> Path | None:
    pointer_file = config_dir / "antigravity-accounts.json.store.pointer.json"
    if pointer_file.exists():
        try:
            ptr = json.loads(pointer_file.read_text(encoding="utf-8"))
            dirname = ptr.get("directoryBasename")
            if dirname:
                p = config_dir / dirname
                if p.is_dir():
                    return p
        except Exception:
            pass
    gen_dirs = sorted(config_dir.glob("*.generation"), key=lambda p: p.stat().st_mtime, reverse=True)
    return gen_dirs[0] if gen_dirs else None


def import_google_accounts(accounts_list: list[dict]) -> int:
    """
    Imports Google accounts into the active generation store or legacy store.
    Generates proper credential digest & dispatch stamps and fixes routing.
    """
    if not accounts_list:
        return 0

    config_dir = Path(os.path.expanduser("~/.config/opencode"))
    config_dir.mkdir(parents=True, exist_ok=True)
    gen_dir = get_active_generation_dir(config_dir)

    count = 0
    now_ms = int(time.time() * 1000)

    if gen_dir:
        cfg_file = gen_dir / "config.json"
        state_file = gen_dir / "state.json"
        if cfg_file.exists() and state_file.exists():
            try:
                cfg = json.loads(cfg_file.read_text(encoding="utf-8"))
                state = json.loads(state_file.read_text(encoding="utf-8"))
                cfg_accounts = cfg.setdefault("accounts", [])
                pool_rows = cfg.setdefault("commonAuthPool", {}).setdefault("rows", {})
                cfg.setdefault("commonAuthPool", {})["schemaVersion"] = 1
                state_accounts = state.setdefault("accounts", {})
                state["version"] = 1

                for item in accounts_list:
                    if not isinstance(item, dict):
                        continue
                    nested = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
                    email = item.get("email") or nested.get("email")
                    refresh_token = item.get("refreshToken") or item.get("refresh") or nested.get("refreshToken") or nested.get("refresh")
                    if not email or not refresh_token:
                        continue

                    project_id = item.get("projectId") or nested.get("projectId") or "aicode-consumers"
                    added_at = item.get("addedAt") or nested.get("addedAt")
                    if not isinstance(added_at, (int, float)) or isinstance(added_at, bool) or not math.isfinite(added_at) or added_at <= 0:
                        added_at = now_ms
                    label = item.get("label") or nested.get("label") or email.split("@")[0]
                    access_token = item.get("accessToken") or item.get("access") or ""
                    expires = item.get("expires") or 0

                    digest = compute_google_credential_digest(refresh_token)
                    dispatch = compute_google_dispatch_digest(access_token, refresh_token, expires)

                    # Look for existing account by email or id
                    aid = None
                    target_id = item.get("id")
                    for existing_aid, existing_st in state_accounts.items():
                        st_email = existing_st.get("commonAuthProviderState", {}).get("metadata", {}).get("email")
                        if st_email and st_email.lower() == email.lower():
                            aid = existing_aid
                            break
                        if target_id and existing_aid == target_id:
                            aid = existing_aid
                            break

                    if aid is None:
                        aid = target_id or str(uuid.uuid4())
                        cfg_accounts.append({
                            "id": aid,
                            "type": "oauth",
                            "addedAt": int(added_at)
                        })
                    else:
                        if not any(a.get("id") == aid for a in cfg_accounts):
                            cfg_accounts.append({
                                "id": aid,
                                "type": "oauth",
                                "addedAt": int(added_at)
                            })

                    # Ensure proper generation pool row structure
                    epoch = pool_rows.get(aid, {}).get("credentialEpoch", 1)
                    if not isinstance(epoch, int) or epoch < 1:
                        epoch = 1
                    pool_rows[aid] = {
                        "credentialEpoch": epoch,
                        "needsFirstReading": False
                    }
                    pool_rows[aid].pop("candidate", None)
                    pool_rows[aid].pop("enabled", None)
                    pool_rows[aid].pop("usable", None)

                    existing_st = state_accounts.get(aid, {})
                    existing_meta = existing_st.get("commonAuthProviderState", {}).get("metadata", {})
                    fingerprint = item.get("fingerprint") or existing_meta.get("fingerprint") or {
                        "deviceId": str(uuid.uuid4()),
                        "sessionToken": secrets.token_hex(16),
                        "userAgent": "antigravity/cli/1.1.24 (aidev_client; os_type=windows; arch=amd64; cl=974782877; auth_method=consumer)",
                        "apiClient": "antigravity-cli",
                        "clientMetadata": {
                            "ideType": "ANTIGRAVITY",
                            "platform": "WINDOWS",
                            "pluginType": "GEMINI"
                        },
                        "createdAt": now_ms
                    }

                    state_accounts[aid] = {
                        "commonAuthProviderState": {
                            "schemaVersion": 1,
                            "metadata": {
                                "addedAt": int(added_at),
                                "lastUsed": now_ms,
                                "enabled": item.get("enabled", True),
                                "label": label,
                                "email": email,
                                "projectId": project_id,
                                "fingerprint": fingerprint,
                                "fingerprintHistory": existing_meta.get("fingerprintHistory", []),
                                "managedProjectId": project_id,
                                "dailyRequestCounts": existing_meta.get("dailyRequestCounts", {
                                    "date": datetime.date.today().isoformat(),
                                    "claude": 0,
                                    "gemini": 0
                                }),
                                "rateLimitResetTimes": existing_meta.get("rateLimitResetTimes", {})
                            }
                        },
                        "commonAuthPool": {
                            "credentialEpoch": epoch,
                            "digest": digest,
                            "dispatch": dispatch,
                            "binding": {},
                            "providerState": ""
                        },
                        "access": access_token,
                        "refresh": refresh_token,
                        "expires": expires,
                        "lastRefreshedAt": now_ms
                    }
                    count += 1

                if cfg_accounts:
                    routing = cfg.setdefault("antigravityRouting", {})
                    routing["schemaVersion"] = 1
                    active_idx = routing.get("activeIndex", 0)
                    if not (0 <= active_idx < len(cfg_accounts)):
                        active_idx = 0
                    routing["activeIndex"] = active_idx
                    routing["activeIndexByFamily"] = {"claude": active_idx, "gemini": active_idx}
                    active_row_id = cfg_accounts[active_idx]["id"]
                    active_epoch = pool_rows.get(active_row_id, {}).get("credentialEpoch", 1)
                    routing["activeRow"] = {"id": active_row_id, "credentialEpoch": active_epoch}
                    routing["activeRowByFamily"] = {
                        "claude": {"id": active_row_id, "credentialEpoch": active_epoch},
                        "gemini": {"id": active_row_id, "credentialEpoch": active_epoch}
                    }

                tmp_cfg = cfg_file.with_name(f"{cfg_file.name}.{secrets.token_hex(4)}.tmp")
                tmp_state = state_file.with_name(f"{state_file.name}.{secrets.token_hex(4)}.tmp")
                tmp_cfg.write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
                tmp_state.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
                os.replace(tmp_cfg, cfg_file)
                os.replace(tmp_state, state_file)

                # IMPORTANT: ensure legacy file does not exist to avoid "legacy source was recreated after activation"
                legacy_file = config_dir / "antigravity-accounts.json"
                if legacy_file.exists():
                    try:
                        legacy_file.unlink(missing_ok=True)
                    except Exception:
                        pass

                return count
            except Exception as e:
                print(f"Error importing into generation store: {e}")
                return 0

    # Fallback when no generation store directory exists
    legacy_file = config_dir / "antigravity-accounts.json"
    legacy_data = {"version": 4, "activeIndex": 0, "accounts": []}
    if legacy_file.exists():
        try:
            legacy_data = json.loads(legacy_file.read_text(encoding="utf-8"))
        except Exception:
            pass
    old_accs = legacy_data.setdefault("accounts", [])
    for item in accounts_list:
        if not isinstance(item, dict):
            continue
        nested = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
        email = item.get("email") or nested.get("email")
        refresh_token = item.get("refreshToken") or item.get("refresh") or nested.get("refreshToken") or nested.get("refresh")
        if not email or not refresh_token:
            continue
        existing = next((a for a in old_accs if a.get("email", "").lower() == email.lower()), None)
        if existing:
            existing["refreshToken"] = refresh_token
            existing["projectId"] = item.get("projectId") or nested.get("projectId") or existing.get("projectId", "aicode-consumers")
        else:
            old_accs.append({
                "email": email,
                "refreshToken": refresh_token,
                "projectId": item.get("projectId") or nested.get("projectId") or "aicode-consumers",
                "addedAt": item.get("addedAt") or now_ms,
                "lastUsed": 0
            })
        count += 1

    legacy_file.write_text(json.dumps(legacy_data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    try:
        node_exe = get_node_executable()
        cli_js = get_cli_js()
        if node_exe and cli_js and Path(node_exe).exists() and Path(cli_js).exists():
            run_silent_cmd([node_exe, cli_js, "migrate", "--offline", "--yes"], timeout=30)
    except Exception:
        pass

    return count


def import_google_account(account_dict: dict) -> bool:
    return import_google_accounts([account_dict]) > 0


if __name__ == "__main__":
    if not acquire_single_instance():
        sys.exit(0)
    set_windows_taskbar_identity()
    sys.modules["antigravity_manager"] = sys.modules[__name__]
    import webview_backend
    webview_backend.run_webview_app()
