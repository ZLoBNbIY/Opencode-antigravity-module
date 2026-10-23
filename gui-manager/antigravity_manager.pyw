"""
Antigravity Hub - Modern Desktop Manager (Cockpit Tools Style)
Features:
- Dark / Light Theme Toggle with saved preference
- Crisp Native Segoe UI Typography
- Left Sidebar Navigation
- Compact 2-Column Grid Cards with high-contrast quotas
- Health Check, Quick Account Rotation, System Tray
"""

import os
import sys
import json
import csv
import time
import datetime
import subprocess
import threading
import uuid
import secrets
from pathlib import Path
import tkinter as tk
from tkinter import messagebox, filedialog

import shutil
import customtkinter as ctk

sys.path.insert(0, str(Path(__file__).resolve().parent))
import openai_manager
if sys.platform == "win32":
    from win_tray import WindowsTrayIcon as TrayIcon
elif sys.platform.startswith("linux"):
    try:
        from linux_tray import LinuxTrayIcon as TrayIcon
    except ImportError:
        TrayIcon = None
else:
    TrayIcon = None
import health_checker
import auto_updater
import crypto_backup
import dns_tester
import local_proxy

# Keep the Windows mutex handle alive for the lifetime of this process.
_SINGLE_INSTANCE_MUTEX = None
_SINGLE_INSTANCE_LOCK_FILE = None


def acquire_single_instance():
    """Return False when another Antigravity Hub instance already owns the mutex."""
    global _SINGLE_INSTANCE_MUTEX, _SINGLE_INSTANCE_LOCK_FILE
    if sys.platform.startswith("linux"):
        try:
            import fcntl

            lock_path = Path.home() / ".local" / "state" / "antigravity-hub" / "hub.lock"
            lock_path.parent.mkdir(parents=True, exist_ok=True)
            lock_file = open(lock_path, "a+", encoding="utf-8")
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            lock_file.seek(0)
            lock_file.truncate()
            lock_file.write(str(os.getpid()))
            lock_file.flush()
            _SINGLE_INSTANCE_LOCK_FILE = lock_file
            return True
        except (BlockingIOError, OSError) as e:
            print(f"Another Antigravity Hub instance is already running: {e}")
            return False
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
    if sys.platform.startswith("linux"):
        return shutil.which("opencode-desktop") or shutil.which("opencode") or ""
    candidates = [
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

def cleanup_opencode_locks():
    try:
        state_dir = Path(os.path.expanduser("~/.local/state/opencode"))
        if state_dir.exists():
            for f in state_dir.glob("service.json*"):
                if sys.platform.startswith("linux"):
                    continue  # Do not remove a potentially active user's service lock.
                try:
                    f.unlink()
                except Exception:
                    pass
    except Exception:
        pass


def stop_opencode_processes():
    if sys.platform.startswith("linux"):
        run_silent_cmd(["pkill", "-x", "opencode"], timeout=5)
        run_silent_cmd(["pkill", "-x", "opencode-desktop"], timeout=5)
        run_silent_cmd(["pkill", "-x", "opencode-cli"], timeout=5)
    elif sys.platform == "win32":
        run_silent_cmd(["taskkill", "/f", "/im", "OpenCode.exe"], timeout=5)
        run_silent_cmd(["taskkill", "/f", "/im", "opencode-cli.exe"], timeout=5)

NODE_EXE = get_node_executable()
CLI_JS = get_cli_js()
CONFIG_FILE = Path(os.path.expanduser(r"~/.config/opencode/antigravity.json"))
OPENCODE_EXE = get_opencode_exe()
LOG_DIR = Path(os.path.expanduser(r"~/.local/share/opencode/log"))
CONFIG_DIR = Path(os.path.expanduser(r"~/.config/opencode"))

DEFAULT_CONFIG = {
    "$schema": "https://raw.githubusercontent.com/cortexkit/opencode-antigravity-auth/main/schema.json",
    "account_selection_strategy": "hybrid",
    "soft_quota_threshold_percent": 100,
    "switch_on_first_rate_limit": True,
    "max_account_switches": 10,
    "quota_style_fallback": True,
    "debug": False,
    "theme_mode": "dark",
}

def run_silent_cmd(cmd, timeout=30):
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
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
        )
        stdout_str = proc.stdout.decode("utf-8", errors="replace") if proc.stdout else ""
        stderr_str = proc.stderr.decode("utf-8", errors="replace") if proc.stderr else ""
    except Exception as e:
        return type("SilentResult", (), {"returncode": 1, "stdout": "", "stderr": str(e)})()

    return type("SilentResult", (), {"returncode": proc.returncode, "stdout": stdout_str, "stderr": stderr_str})()


def open_path(path: Path):
    if not path.exists():
        return
    if sys.platform == "win32":
        os.startfile(path)
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])

def get_active_google_account_index() -> int:
    config_dir = Path(os.path.expanduser("~/.config/opencode"))
    gen_dirs = list(config_dir.glob("*.generation"))
    if gen_dirs:
        cfg_file = gen_dirs[0] / "config.json"
        if cfg_file.exists():
            try:
                cfg = json.loads(cfg_file.read_text(encoding="utf-8"))
                routing = cfg.get("antigravityRouting", {})
                active_row_id = routing.get("activeRow", {}).get("id")
                accounts = cfg.get("accounts", [])
                if active_row_id:
                    for i, acc in enumerate(accounts):
                        if acc.get("id") == active_row_id:
                            return i
                return int(routing.get("activeIndex", 0))
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
                            "projectId": meta.get("projectId", "aicode-consumers"),
                            "addedAt": meta.get("addedAt") or acc.get("addedAt"),
                            "label": meta.get("label", ""),
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
            g_data = cached.get(g_name, {})
            rem_frac = g_data.get("remainingFraction", 1.0)
            windows = []
            for w in g_data.get("windows", []):
                windows.append({
                    "window": w.get("window"),
                    "remainingPercent": round(w.get("remainingFraction", 1.0) * 100, 1),
                    "resetTime": w.get("resetTime"),
                })
            groups.append({
                "name": g_name,
                "remainingPercent": round(rem_frac * 100, 1),
                "resetTime": g_data.get("resetTime"),
                "windows": windows,
            })

        disk_accounts.append({
            "index": idx,
            "id": aid,
            "email": email,
            "addedAt": added_at,
            "status": "ok" if row.get("enabled", True) else "disabled",
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

def import_google_account(account_dict: dict) -> bool:
    email = account_dict.get("email")
    refresh_token = account_dict.get("refreshToken") or account_dict.get("refresh")
    access_token = account_dict.get("accessToken") or account_dict.get("access") or ""
    project_id = account_dict.get("projectId") or "aicode-consumers"
    added_at = account_dict.get("addedAt") or int(time.time() * 1000)
    label = account_dict.get("label") or (email.split("@")[0] if email else "Google Account")

    if not email or not refresh_token:
        return False

    config_dir = Path(os.path.expanduser("~/.config/opencode"))
    gen_dirs = list(config_dir.glob("*.generation"))

    if gen_dirs:
        gen_dir = gen_dirs[0]
        cfg_file = gen_dir / "config.json"
        state_file = gen_dir / "state.json"
        mig_file = gen_dir / "migration.json"
        if cfg_file.exists() and state_file.exists():
            try:
                cfg = json.loads(cfg_file.read_text(encoding="utf-8"))
                state = json.loads(state_file.read_text(encoding="utf-8"))

                existing_id = None
                for acc in cfg.get("accounts", []):
                    aid = acc.get("id")
                    st = state.get("accounts", {}).get(aid, {})
                    if st.get("commonAuthProviderState", {}).get("metadata", {}).get("email") == email:
                        existing_id = aid
                        break

                target_id = existing_id or str(uuid.uuid4())

                if not existing_id:
                    cfg.setdefault("accounts", []).append({
                        "id": target_id,
                        "type": "oauth",
                        "addedAt": added_at
                    })
                    cfg.setdefault("commonAuthPool", {}).setdefault("rows", {})[target_id] = {
                        "credentialEpoch": 1,
                        "needsFirstReading": True
                    }
                    if len(cfg["accounts"]) == 1:
                        routing = cfg.setdefault("antigravityRouting", {})
                        routing["activeIndex"] = 0
                        routing["activeIndexByFamily"] = {"claude": 0, "gemini": 0}
                        routing["activeRow"] = {"id": target_id, "credentialEpoch": 1}
                        routing["activeRowByFamily"] = {
                            "claude": {"id": target_id, "credentialEpoch": 1},
                            "gemini": {"id": target_id, "credentialEpoch": 1},
                        }
                    cfg_file.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")

                state_accounts = state.setdefault("accounts", {})
                existing_state = state_accounts.get(target_id, {})
                existing_meta = existing_state.get("commonAuthProviderState", {}).get("metadata", {})

                device_id = existing_meta.get("fingerprint", {}).get("deviceId") or str(uuid.uuid4())
                session_token = secrets.token_hex(16)

                state_accounts[target_id] = {
                    "commonAuthProviderState": {
                        "schemaVersion": 1,
                        "metadata": {
                            "email": email,
                            "label": label,
                            "projectId": project_id,
                            "addedAt": added_at,
                            "lastUsed": int(time.time() * 1000),
                            "enabled": True,
                            "fingerprint": {
                                "deviceId": device_id,
                                "sessionToken": session_token,
                                "userAgent": "antigravity/cli/1.1.24 (aidev_client; os_type=windows; arch=amd64; cl=974782877; auth_method=consumer)",
                                "apiClient": "antigravity-cli",
                                "clientMetadata": {
                                    "ideType": "ANTIGRAVITY",
                                    "platform": "WINDOWS",
                                    "pluginType": "GEMINI"
                                },
                                "createdAt": int(time.time() * 1000)
                            },
                            "fingerprintHistory": [],
                            "managedProjectId": project_id,
                            "dailyRequestCounts": {
                                "date": datetime.date.today().isoformat(),
                                "claude": 0,
                                "gemini": 0
                            }
                        }
                    },
                    "commonAuthPool": {},
                    "access": access_token,
                    "refresh": refresh_token,
                    "expires": int(time.time() * 1000) + 3600000,
                    "lastRefreshedAt": int(time.time() * 1000)
                }
                state_file.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")

                if mig_file.exists():
                    try:
                        mig_data = json.loads(mig_file.read_text(encoding="utf-8"))
                        manifest_accs = mig_data.setdefault("manifest", {}).setdefault("accounts", [])
                        m_found = False
                        for ma in manifest_accs:
                            if ma.get("metadata", {}).get("email") == email:
                                ma["refreshToken"] = refresh_token
                                m_found = True
                                break
                        if not m_found:
                            manifest_accs.append({
                                "ordinal": len(manifest_accs),
                                "refreshToken": refresh_token,
                                "metadata": {
                                    "email": email,
                                    "label": label,
                                    "projectId": project_id,
                                    "addedAt": added_at,
                                    "lastUsed": added_at,
                                    "enabled": True
                                }
                            })
                        mig_file.write_text(json.dumps(mig_data, indent=2, ensure_ascii=False), encoding="utf-8")
                    except Exception:
                        pass

                legacy_file = config_dir / "antigravity-accounts.json"
                if legacy_file.exists():
                    try:
                        legacy_file.unlink()
                    except Exception:
                        pass

                return True
            except Exception as e:
                print(f"Error importing to generation store: {e}")
                return False
    else:
        legacy_file = config_dir / "antigravity-accounts.json"
        legacy_data = {"version": 4, "activeIndex": 0, "accounts": []}
        if legacy_file.exists():
            try:
                legacy_data = json.loads(legacy_file.read_text(encoding="utf-8"))
            except Exception:
                pass
        old_accs = legacy_data.get("accounts", [])
        found = False
        for a in old_accs:
            if a.get("email") == email:
                a["refreshToken"] = refresh_token
                if access_token:
                    a["accessToken"] = access_token
                found = True
                break
        if not found:
            old_accs.append({
                "email": email,
                "refreshToken": refresh_token,
                "accessToken": access_token,
                "projectId": project_id,
                "addedAt": added_at
            })
        legacy_data["accounts"] = old_accs
        legacy_file.write_text(json.dumps(legacy_data, indent=2, ensure_ascii=False), encoding="utf-8")
        run_silent_cmd([NODE_EXE, CLI_JS, "migrate", "--offline", "--yes"], timeout=15)

    return True


# =========================================================================
# DUAL-THEME COLOR PALETTE (Tuple format: (Light, Dark))
# CustomTkinter automatically applies the correct element on appearance change
# =========================================================================
COLOR = {
    "bg": ("#f1f5f9", "#0f172a"),
    "sidebar_bg": ("#ffffff", "#1e293b"),
    "card_bg": ("#ffffff", "#1e293b"),
    "subbox_bg": ("#f8fafc", "#0f172a"),
    "border": ("#e2e8f0", "#334155"),
    "border_active": ("#0284c7", "#38bdf8"),
    "text_primary": ("#0f172a", "#f8fafc"),
    "text_secondary": ("#475569", "#94a3b8"),
    "text_muted": ("#64748b", "#64748b"),
    "bar_bg": ("#e2e8f0", "#334155"),
    "statusbar_bg": ("#ffffff", "#1e293b"),
    "nav_active_bg": ("#e0f2fe", "#0284c7"),
    "nav_active_text": ("#0369a1", "#ffffff"),
    "nav_idle_text": ("#475569", "#cbd5e1"),
}


class AntigravityManagerApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("Antigravity Hub — Google & ChatGPT")
        self.geometry("1180x760")
        self.minsize(980, 680)

        # Load config first to read theme
        self.config_data = self.load_config()
        self.current_theme = self.config_data.get("theme_mode", "dark")

        # Apply CustomTkinter appearance mode directly
        self.appearance_mode = "Dark" if self.current_theme == "dark" else "Light"
        ctk.set_appearance_mode(self.appearance_mode)
        ctk.set_default_color_theme("blue")
        self.configure(fg_color=COLOR["bg"])

        icon_file = Path(__file__).resolve().parent / ("icon.ico" if sys.platform == "win32" else "icon.png")
        if icon_file.exists():
            try:
                if sys.platform == "win32":
                    self.iconbitmap(str(icon_file))
                else:
                    png_icon = Path(__file__).resolve().parent / "icon.png"
                    if png_icon.exists():
                        self._window_icon = tk.PhotoImage(file=str(png_icon))
                        self.iconphoto(True, self._window_icon)
            except Exception:
                pass

        # State
        self.accounts_data = []
        self.openai_accounts_data = []
        self.current_nav = "antigravity"
        self.current_provider_view = "google"
        self.is_loading = False
        self.search_query = ""
        self._opencode_status_check_running = False
        self._opencode_status_after_id = None

        # Periodic auto-refresh (every 10 minutes)
        self.auto_refresh_enabled = True

        # Start embedded local proxy tunnel for Bun/OpenCode OpenAI & Google geo-bypass
        try:
            local_proxy.start_local_proxy()
        except Exception as e:
            print(f"Error starting local proxy: {e}")
        self.auto_refresh_interval_min = 10
        self.countdown_seconds = self.auto_refresh_interval_min * 60

        # Background token refresh daemon (every 30 minutes)
        self.token_refresh_interval_min = 30
        self.token_refresh_countdown = self.token_refresh_interval_min * 60

        # Auto-updater state
        self.update_info = None

        # System tray setup
        self.tray = None
        self.protocol("WM_DELETE_WINDOW", self.on_close_to_tray)

        # Root Layout: Sidebar (col 0) + Main Content (col 1)
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=1)

        self.create_sidebar()
        self.create_main_content()

        # Background initialization
        self.init_system_tray()
        self.refresh_all_async()
        self.update_opencode_status()
        self.start_countdown_timer()
        self.check_updates_async()

    # --- Font Helper (Crisp Segoe UI) ---
    def font(self, size=12, weight="normal"):
        return ctk.CTkFont(family="Segoe UI", size=size, weight=weight)

    # --- Configuration Management ---
    def load_config(self):
        if CONFIG_FILE.exists():
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    return {**DEFAULT_CONFIG, **data}
            except Exception as e:
                print(f"Error loading config: {e}")
        return DEFAULT_CONFIG.copy()

    def save_config(self):
        try:
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(self.config_data, f, indent=2, ensure_ascii=False)
            return True, "Настройки сохранены!"
        except Exception as e:
            return False, f"Ошибка сохранения: {e}"

    # --- Theme Toggling ---
    def toggle_theme(self):
        new_theme = "light" if self.current_theme == "dark" else "dark"
        self.current_theme = new_theme
        self.config_data["theme_mode"] = new_theme
        self.save_config()

        ctk.set_appearance_mode("Dark" if new_theme == "dark" else "Light")

        # Update button text in sidebar
        if hasattr(self, "btn_theme_toggle"):
            self.btn_theme_toggle.configure(
                text="☀️  Светлая тема" if new_theme == "dark" else "🌙  Тёмная тема",
            )

        # Force dynamic background color update on main frames
        self.configure(fg_color=COLOR["bg"])
        self.main_frame.configure(fg_color=COLOR["bg"])
        self.content_area.configure(fg_color=COLOR["bg"])
        self.accounts_container.configure(fg_color=COLOR["bg"])

        # Update nav buttons active/idle state
        for k, btn in self.nav_btns.items():
            if k == self.current_nav:
                btn.configure(fg_color=COLOR["nav_active_bg"], text_color=COLOR["nav_active_text"])
            else:
                btn.configure(fg_color="transparent", text_color=COLOR["nav_idle_text"])

        self.render_accounts()

    # --- System Tray Integration ---
    def init_system_tray(self):
        if TrayIcon is None:
            print("System tray is unavailable; install Linux GUI dependencies to enable it.")
            return
        try:
            icon_file = Path(__file__).resolve().parent / ("icon.ico" if sys.platform == "win32" else "icon.png")
            icon_str = str(icon_file) if icon_file.exists() else None
            self.tray = TrayIcon(
                title="Antigravity Hub — Google & ChatGPT",
                icon_path=icon_str,
                on_show=lambda: self.after(0, self.show_from_tray),
                on_refresh=lambda: self.after(0, self.refresh_all_async),
                on_exit=lambda: self.after(0, self.exit_app_fully),
            )
            self.tray.start()
        except Exception as e:
            print(f"Error initializing system tray: {e}")

    def on_close_to_tray(self):
        remembered = self.config_data.get("close_choice_remembered", False)
        choice = self.config_data.get("close_choice") if remembered else None
        remember = remembered
        if choice not in ("tray", "exit"):
            choice, remember = self.ask_close_choice()
        if choice is None:
            return
        if choice == "tray" and (not self.tray or not self.tray.is_visible):
            self.config_data.pop("close_choice", None)
            self.config_data["close_choice_remembered"] = False
            self.save_config()
            messagebox.showwarning(
                "Системный трей недоступен",
                "Не удалось запустить значок в системном трее. Установите Linux-зависимости Antigravity Hub или закройте приложение.",
            )
            return
        if remember:
            self.config_data["close_choice"] = choice
            self.config_data["close_choice_remembered"] = True
        else:
            self.config_data.pop("close_choice", None)
            self.config_data["close_choice_remembered"] = False
        self.save_config()
        if choice == "exit":
            self.exit_app_fully()
            return
        try:
            self.withdraw()
            if self.tray and self.tray.is_visible:
                self.tray.show_balloon(
                    "Antigravity Hub свёрнут",
                    "Приложение работает в фоне. Кликните левой кнопкой для открытия или правой для меню.",
                )
        except Exception:
            self.destroy()

    def ask_close_choice(self):
        dialog = ctk.CTkToplevel(self)
        dialog.title("Закрытие Antigravity Hub")
        dialog.geometry("390x220")
        dialog.resizable(False, False)
        dialog.transient(self)
        dialog.grab_set()
        dialog.protocol("WM_DELETE_WINDOW", lambda: finish(None))

        result = {"choice": None, "remember": False}
        remember_var = tk.BooleanVar(value=False)

        def finish(choice):
            result["choice"] = choice
            result["remember"] = remember_var.get()
            try:
                dialog.grab_release()
                dialog.destroy()
            except Exception:
                pass

        ctk.CTkLabel(
            dialog,
            text="Что сделать с Antigravity Hub?",
            font=self.font(size=15, weight="bold"),
            text_color=COLOR["text_primary"],
        ).pack(padx=20, pady=(22, 14))
        ctk.CTkCheckBox(
            dialog,
            text="Запомнить мой выбор (изменить его можно в настройках)",
            variable=remember_var,
            font=self.font(size=11),
        ).pack(anchor="w", padx=22, pady=(0, 16))
        buttons = ctk.CTkFrame(dialog, fg_color="transparent")
        buttons.pack(fill="x", padx=20, pady=(0, 18))
        ctk.CTkButton(
            buttons,
            text="Свернуть в трей",
            command=lambda: finish("tray"),
        ).pack(side="left", expand=True, fill="x", padx=(0, 6))
        ctk.CTkButton(
            buttons,
            text="Закрыть приложение",
            fg_color="#dc2626",
            hover_color="#b91c1c",
            command=lambda: finish("exit"),
        ).pack(side="left", expand=True, fill="x", padx=(6, 0))
        self.wait_window(dialog)
        return result["choice"], result["remember"]

    def show_from_tray(self):
        try:
            self.deiconify()
            self.lift()
            self.focus_force()
        except Exception:
            pass

    def exit_app_fully(self):
        try:
            if self.tray:
                self.tray.remove()
        except Exception:
            pass
        self.destroy()

    # --- Auto-Updater ---
    def manual_check_updates_action(self):
        self.btn_check_update.configure(state="disabled", text="⏳ Проверка...")
        self.set_status(f"Проверка обновлений на GitHub (ветка {auto_updater.BRANCH})...")

        def _do_manual_check():
            repo_dir = Path(__file__).resolve().parent.parent
            info = auto_updater.check_for_updates(repo_dir)
            self.after(0, lambda: self._on_manual_updates_checked(info))

        threading.Thread(target=_do_manual_check, daemon=True).start()

    def _on_manual_updates_checked(self, info):
        self.btn_check_update.configure(state="normal", text="🔄 Проверить обновления")
        has_update = info.get("has_update", False)
        local_sha = info.get("local_sha", "HEAD")
        remote_sha = info.get("remote_sha", "")
        err = info.get("error")

        if err:
            messagebox.showwarning("Проверка обновлений", f"Не удалось проверить обновления:\n{err}")
            self.set_status(f"Ошибка проверки: {err}")
        elif has_update:
            msg = info.get("message", "Новые улучшения")
            self.update_info = info
            self.show_update_banner(info)
            self.set_status("Доступна новая версия Antigravity Hub")
        else:
            messagebox.showinfo(
                "Обновления не требуются",
                f"У вас установлена самая актуальная версия Antigravity Hub!\n\n"
                f"• Ветка: {auto_updater.BRANCH}\n"
                f"• Коммит: {local_sha}\n"
                f"• Статус: Синхронизировано с GitHub",
            )
            self.set_status("Установлена актуальная версия")

    def check_updates_async(self):
        repo_dir = Path(__file__).resolve().parent.parent
        threading.Thread(target=self._worker_check_updates, args=(repo_dir,), daemon=True).start()

    def _worker_check_updates(self, repo_dir):
        try:
            info = auto_updater.check_for_updates(repo_dir)
            self.after(0, lambda: self._on_updates_checked(info))
        except Exception as e:
            print(f"Error checking updates: {e}")

    def _on_updates_checked(self, info):
        self.update_info = info
        if info.get("has_update"):
            self.show_update_banner(info)

    def show_update_banner(self, info):
        self.update_info = info
        if hasattr(self, "update_banner") and self.update_banner:
            return

        self.update_banner = ctk.CTkFrame(
            self.content_area,
            fg_color="#0369a1" if self.current_theme == "dark" else "#eff6ff",
            corner_radius=10,
            border_width=1,
            border_color="#38bdf8" if self.current_theme == "dark" else "#bfdbfe"
        )
        self.update_banner.pack(fill="x", padx=24, pady=(12, 0))
        self.update_banner.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            self.update_banner,
            text="🚀 Доступна новая версия Antigravity Hub",
            font=self.font(size=12, weight="bold"),
            text_color="#ffffff" if self.current_theme == "dark" else "#1d4ed8",
            anchor="w",
        ).grid(row=0, column=0, sticky="ew", padx=16, pady=8)

        btn_box = ctk.CTkFrame(self.update_banner, fg_color="transparent")
        btn_box.grid(row=0, column=1, sticky="e", padx=12, pady=6)

        ctk.CTkButton(
            btn_box,
            text="Обновить",
            font=self.font(size=11, weight="bold"),
            fg_color="#0284c7",
            hover_color="#0369a1",
            height=28,
            command=self.apply_update_action,
        ).pack(side="left", padx=(0, 6))

        ctk.CTkButton(
            btn_box,
            text="✕",
            font=self.font(size=12),
            fg_color="transparent",
            hover_color="#075985" if self.current_theme == "dark" else "#cbd5e1",
            text_color="#ffffff" if self.current_theme == "dark" else "#475569",
            height=28,
            width=28,
            command=self.dismiss_update_banner,
        ).pack(side="left")

    def dismiss_update_banner(self):
        if getattr(self, "update_banner", None):
            self.update_banner.destroy()
            self.update_banner = None

    def apply_update_action(self):
        info = self.update_info or {}
        changes = (info.get("message") or "Исправления и улучшения Antigravity Hub.").strip()
        changes = changes.splitlines()[0][:240]
        remote_sha = info.get("remote_sha")
        changelog = f"Что обновлено:\n• {changes}"
        if remote_sha:
            changelog += f"\n\nВерсия: {remote_sha}"
        if not messagebox.askyesno("Обновление Antigravity Hub", f"{changelog}\n\nЗагрузить и установить обновление сейчас?"):
            return

        repo_dir = Path(__file__).resolve().parent.parent
        self.set_status(f"Применение обновления с GitHub (ветка {auto_updater.BRANCH})...")

        def _do_update():
            ok, msg = auto_updater.apply_update_git(repo_dir)
            self.after(0, lambda: self._on_update_applied(ok, msg))

        threading.Thread(target=_do_update, daemon=True).start()

    def _on_update_applied(self, ok, msg):
        if ok:
            messagebox.showinfo("Обновление завершено!", f"{msg}\n\nРекомендуется перезапустить OpenCode и Hub.")
            self.dismiss_update_banner()
            self.refresh_all_async()
        else:
            messagebox.showerror("Ошибка обновления", msg)

    # =========================================================================
    # SIDEBAR COMPONENT (Cockpit Tools Style)
    # =========================================================================
    def create_sidebar(self):
        self.sidebar = ctk.CTkFrame(
            self,
            width=230,
            corner_radius=0,
            fg_color=COLOR["sidebar_bg"],
            border_width=1,
            border_color=COLOR["border"],
        )
        self.sidebar.grid(row=0, column=0, sticky="nsew")
        self.sidebar.grid_propagate(False)
        self.sidebar.grid_rowconfigure(5, weight=1)

        # Brand / Logo Header
        logo_box = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        logo_box.grid(row=0, column=0, padx=18, pady=(20, 20), sticky="w")

        icon_badge = ctk.CTkLabel(
            logo_box,
            text="⚡",
            font=self.font(size=16, weight="bold"),
            fg_color="#0284c7",
            text_color="#ffffff",
            width=32,
            height=32,
            corner_radius=8,
        )
        icon_badge.pack(side="left", padx=(0, 10))

        title_lbl = ctk.CTkLabel(
            logo_box,
            text="Antigravity Hub",
            font=self.font(size=16, weight="bold"),
            text_color=COLOR["text_primary"],
        )
        title_lbl.pack(side="left")

        # Nav Buttons Container
        self.nav_btns = {}
        nav_items = [
            ("antigravity", "🚀  Antigravity (Google)", "google"),
            ("openai", "🟢  ChatGPT (OpenAI)", "openai"),
            ("settings", "⚙️  Настройки", "settings"),
            ("system", "🛠  OpenCode & Диагностика", "system"),
        ]

        for idx, (key, label, _) in enumerate(nav_items, start=1):
            btn = ctk.CTkButton(
                self.sidebar,
                text=label,
                font=self.font(size=13, weight="bold"),
                anchor="w",
                height=42,
                corner_radius=8,
                fg_color=COLOR["nav_active_bg"] if key == self.current_nav else "transparent",
                text_color=COLOR["nav_active_text"] if key == self.current_nav else COLOR["nav_idle_text"],
                hover_color=("#e2e8f0", "#334155"),
                command=lambda k=key: self.switch_nav(k),
            )
            btn.grid(row=idx, column=0, padx=12, pady=3, sticky="ew")
            self.nav_btns[key] = btn

        # Sidebar Footer: Theme Toggle + OpenCode status
        footer_box = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        footer_box.grid(row=6, column=0, padx=14, pady=16, sticky="ew")

        # Theme toggle button
        theme_txt = "☀️  Светлая тема" if self.current_theme == "dark" else "🌙  Тёмная тема"
        self.btn_theme_toggle = ctk.CTkButton(
            footer_box,
            text=theme_txt,
            font=self.font(size=12, weight="bold"),
            fg_color=COLOR["card_bg"],
            hover_color=("#e2e8f0", "#334155"),
            text_color=COLOR["text_primary"],
            border_width=1,
            border_color=COLOR["border"],
            height=32,
            command=self.toggle_theme,
        )
        self.btn_theme_toggle.pack(fill="x", pady=(0, 10))

        self.opencode_badge = ctk.CTkLabel(
            footer_box,
            text="● OpenCode: Проверка...",
            font=self.font(size=11, weight="bold"),
            fg_color=COLOR["subbox_bg"],
            text_color=COLOR["text_secondary"],
            corner_radius=6,
            height=26,
        )
        self.opencode_badge.pack(fill="x", pady=(0, 6))

        ctk.CTkButton(
            footer_box,
            text="🔄 Перезапустить OpenCode",
            font=self.font(size=11, weight="bold"),
            fg_color="#3b82f6",
            hover_color="#2563eb",
            text_color="#ffffff",
            height=30,
            command=self.restart_opencode_action,
        ).pack(fill="x")

    def switch_nav(self, target_nav):
        self.current_nav = target_nav
        for key, btn in self.nav_btns.items():
            if key == target_nav:
                btn.configure(fg_color=COLOR["nav_active_bg"], text_color=COLOR["nav_active_text"])
            else:
                btn.configure(fg_color="transparent", text_color=COLOR["nav_idle_text"])

        # Toggle views
        if target_nav in ("antigravity", "openai"):
            self.current_provider_view = "google" if target_nav == "antigravity" else "openai"
            self.top_action_bar.pack(fill="x", padx=24, pady=(16, 0))
            self.accounts_container.pack(fill="both", expand=True, padx=24, pady=(12, 16))
            self.settings_frame.pack_forget()
            self.system_frame.pack_forget()
            self.update_action_bar_for_provider()
            self.render_accounts()
        elif target_nav == "settings":
            self.top_action_bar.pack_forget()
            self.accounts_container.pack_forget()
            self.system_frame.pack_forget()
            self.settings_frame.pack(fill="both", expand=True, padx=24, pady=16)
        elif target_nav == "system":
            self.top_action_bar.pack_forget()
            self.accounts_container.pack_forget()
            self.settings_frame.pack_forget()
            self.system_frame.pack(fill="both", expand=True, padx=24, pady=16)

    # =========================================================================
    # MAIN CONTENT AREA
    # =========================================================================
    def create_main_content(self):
        self.main_frame = ctk.CTkFrame(self, fg_color=COLOR["bg"], corner_radius=0)
        self.main_frame.grid(row=0, column=1, sticky="nsew")
        self.main_frame.grid_rowconfigure(0, weight=1)
        self.main_frame.grid_columnconfigure(0, weight=1)

        self.content_area = ctk.CTkFrame(self.main_frame, fg_color=COLOR["bg"])
        self.content_area.pack(fill="both", expand=True)

        self.create_action_bar()
        self.create_flash_banner()

        self.accounts_container = ctk.CTkScrollableFrame(
            self.content_area,
            fg_color=COLOR["bg"],
            corner_radius=0,
        )
        self.accounts_container.pack(fill="both", expand=True, padx=24, pady=(12, 16))

        self.create_settings_view()
        self.create_system_view()
        self.create_statusbar()

    def create_action_bar(self):
        self.top_action_bar = ctk.CTkFrame(self.content_area, fg_color="transparent")
        self.top_action_bar.pack(fill="x", padx=24, pady=(16, 0))

        # Search input
        self.search_entry = ctk.CTkEntry(
            self.top_action_bar,
            placeholder_text="🔍 Поиск аккаунта...",
            font=self.font(size=12),
            width=240,
            height=36,
            corner_radius=8,
            fg_color=COLOR["card_bg"],
            border_color=COLOR["border"],
            text_color=COLOR["text_primary"],
        )
        self.search_entry.pack(side="left", padx=(0, 10))
        self.search_entry.bind("<KeyRelease>", self.on_search_key)

        # Count pill
        self.lbl_count_pill = ctk.CTkLabel(
            self.top_action_bar,
            text="Все (0)",
            font=self.font(size=12, weight="bold"),
            fg_color=COLOR["subbox_bg"],
            text_color=COLOR["text_secondary"],
            corner_radius=12,
            padx=12,
            height=34,
        )
        self.lbl_count_pill.pack(side="left", padx=(0, 10))

        # Action buttons
        self.btn_add_account = ctk.CTkButton(
            self.top_action_bar,
            text="➕ Добавить аккаунт",
            font=self.font(size=12, weight="bold"),
            fg_color="#0284c7",
            hover_color="#0369a1",
            height=36,
            corner_radius=8,
            command=self.add_account_action,
        )
        self.btn_add_account.pack(side="right", padx=(8, 0))

        self.btn_refresh = ctk.CTkButton(
            self.top_action_bar,
            text="🔄 Обновить квоты",
            font=self.font(size=12, weight="bold"),
            fg_color=COLOR["card_bg"],
            hover_color=COLOR["subbox_bg"],
            text_color=COLOR["text_primary"],
            border_width=1,
            border_color=COLOR["border"],
            height=36,
            width=135,
            corner_radius=8,
            command=self.refresh_all_async,
        )
        self.btn_refresh.pack(side="right", padx=(8, 0))

        self.btn_export = ctk.CTkButton(
            self.top_action_bar,
            text="📤 Экспорт",
            font=self.font(size=12, weight="bold"),
            fg_color=COLOR["card_bg"],
            hover_color=COLOR["subbox_bg"],
            text_color=COLOR["text_primary"],
            border_width=1,
            border_color=COLOR["border"],
            height=36,
            width=90,
            corner_radius=8,
            command=self.export_accounts_action,
        )
        self.btn_export.pack(side="right", padx=(8, 0))

        self.btn_import = ctk.CTkButton(
            self.top_action_bar,
            text="📥 Импорт",
            font=self.font(size=12, weight="bold"),
            fg_color=COLOR["card_bg"],
            hover_color=COLOR["subbox_bg"],
            text_color=COLOR["text_primary"],
            border_width=1,
            border_color=COLOR["border"],
            height=36,
            width=90,
            corner_radius=8,
            command=self.import_accounts_action,
        )
        self.btn_import.pack(side="right", padx=(8, 0))

    def update_action_bar_for_provider(self):
        if self.current_provider_view == "google":
            self.btn_add_account.configure(
                text="➕ Добавить Google",
                command=self.add_account_action,
                fg_color="#0284c7",
                hover_color="#0369a1",
            )
        else:
            self.btn_add_account.configure(
                text="➕ Добавить OpenAI",
                command=self.add_openai_account_action,
                fg_color="#10a37f",
                hover_color="#0e8a6c",
            )

    def show_google_models_action(self):
        """Show models currently registered for the Google provider in OpenCode."""
        if getattr(self, "google_models_loading", False):
            return
        self.google_models_loading = True
        self.btn_google_models.configure(state="disabled", text="⏳ Загружаю...")

        def _load():
            try:
                desktop_exe = Path(get_opencode_exe())
                cli_candidates = [desktop_exe.parent / "resources" / "opencode-cli.exe"]
                path_cli = shutil.which("opencode-cli") or shutil.which("opencode")
                if path_cli:
                    cli_candidates.append(Path(path_cli))
                exe = next((str(candidate) for candidate in cli_candidates if candidate.is_file()), None)
                if not exe:
                    raise RuntimeError("Не найден CLI OpenCode (opencode-cli.exe).")
                result = run_silent_cmd([exe, "models"], timeout=45)
                output = (result.stdout or "").strip()
                error = (result.stderr or "").strip()
                if result.returncode != 0:
                    detail = error or output or f"OpenCode завершился с кодом {result.returncode}."
                    raise RuntimeError(detail[:3000])
                antigravity_models = sorted({line.strip() for line in output.splitlines()
                                             if ("antigravity" in line.strip().lower() or "argon" in line.strip().lower())})
                if not antigravity_models:
                    output = "OpenCode не вывел модели Antigravity. Проверьте, что Antigravity-плагин загружен."
                else:
                    output = "\n".join(antigravity_models)
                self.after(0, lambda: self._show_google_models_result(output, None))
            except Exception as exc:
                self.after(0, lambda message=str(exc): self._show_google_models_result("", message))

        threading.Thread(target=_load, name="hub-google-model-list", daemon=True).start()

    def _show_google_models_result(self, output, error):
        self.google_models_loading = False
        self.btn_google_models.configure(state="normal", text="📋 Модели")
        if error:
            messagebox.showerror("Модели Antigravity в OpenCode", error, parent=self)
            return

        dialog = ctk.CTkToplevel(self)
        dialog.title("Модели Antigravity, доступные в OpenCode")
        dialog.geometry("640x480")
        dialog.transient(self)
        dialog.grab_set()
        ctk.CTkLabel(
            dialog,
            text="Список моделей Antigravity, возвращаемых OpenCode для текущей конфигурации. "
                 "Он не проверяет доступность каждой модели для вашей учётной записи.\n\n"
                 "Список может включать уже отключённые модели: их ID по-прежнему видны "
                 "при сканировании, но сами модели могут быть недоступны для использования.",
            justify="left",
            anchor="w",
            wraplength=600,
        ).pack(fill="x", padx=16, pady=(16, 8))
        textbox = ctk.CTkTextbox(dialog, wrap="none")
        textbox.pack(fill="both", expand=True, padx=16, pady=8)
        textbox.insert("1.0", output)
        textbox.configure(state="disabled")
        ctk.CTkButton(dialog, text="Закрыть", command=dialog.destroy).pack(anchor="e", padx=16, pady=(4, 16))
    def create_flash_banner(self):
        self.flash_banner = ctk.CTkFrame(
            self.content_area,
            fg_color="#0369a1" if self.current_theme == "dark" else "#eff6ff",
            corner_radius=8,
            border_width=1,
            border_color="#38bdf8" if self.current_theme == "dark" else "#bfdbfe",
            height=36,
        )
        self.flash_banner.grid_columnconfigure(0, weight=1)

        self.lbl_flash = ctk.CTkLabel(
            self.flash_banner,
            text="",
            font=self.font(size=12, weight="bold"),
            text_color="#ffffff" if self.current_theme == "dark" else "#1d4ed8",
        )
        self.lbl_flash.grid(row=0, column=0, sticky="w", padx=16, pady=6)

        ctk.CTkButton(
            self.flash_banner,
            text="✕",
            font=self.font(size=11),
            fg_color="transparent",
            hover_color="#0284c7" if self.current_theme == "dark" else "#dbeafe",
            text_color="#ffffff" if self.current_theme == "dark" else "#60a5fa",
            width=24,
            height=24,
            command=lambda: self.flash_banner.pack_forget(),
        ).grid(row=0, column=1, sticky="e", padx=8)

    def show_flash(self, message):
        self.lbl_flash.configure(text=message)
        self.flash_banner.pack(fill="x", padx=24, pady=(10, 0), before=self.accounts_container)
        self.after(6000, lambda: self.flash_banner.pack_forget())

    def on_search_key(self, event):
        self.search_query = self.search_entry.get().strip().lower()
        self.render_accounts()

    # =========================================================================
    # RENDER ACCOUNTS (Grid)
    # =========================================================================
    def render_accounts(self):
        for widget in self.accounts_container.winfo_children():
            widget.destroy()

        if self.current_provider_view == "google":
            self.render_google_grid()
        else:
            self.render_openai_grid()

    def render_google_grid(self):
        data = self.accounts_data
        if self.search_query:
            data = [a for a in data if self.search_query in a.get("email", "").lower()]

        total = len(self.accounts_data)
        active_idx = get_active_google_account_index()
        self.lbl_count_pill.configure(text=f"Все ({total})")

        if not data:
            self._render_empty_state("Google (Antigravity)")
            return

        grid_frame = ctk.CTkFrame(self.accounts_container, fg_color="transparent")
        grid_frame.pack(fill="both", expand=True)

        for col in range(2):
            grid_frame.grid_columnconfigure(col, weight=1, uniform="card_col")

        for idx, acc in enumerate(data):
            row = idx // 2
            col = idx % 2
            is_active = (acc.get("index", 1) - 1 == active_idx)
            card = self.create_compact_card(grid_frame, acc, is_active=is_active)
            card.grid(row=row, column=col, padx=8, pady=8, sticky="nsew")

    def render_openai_grid(self):
        data = self.openai_accounts_data
        if self.search_query:
            data = [a for a in data if self.search_query in a.get("email", "").lower()]

        total = len(self.openai_accounts_data)
        self.lbl_count_pill.configure(text=f"Все ({total})")

        if not data:
            self._render_empty_state("OpenAI (ChatGPT)")
            return

        grid_frame = ctk.CTkFrame(self.accounts_container, fg_color="transparent")
        grid_frame.pack(fill="both", expand=True)

        for col in range(2):
            grid_frame.grid_columnconfigure(col, weight=1, uniform="card_col")

        for idx, acc in enumerate(data):
            row = idx // 2
            col = idx % 2
            is_active = acc.get("is_active", False)
            card = self.create_compact_openai_card(grid_frame, acc, is_active=is_active)
            card.grid(row=row, column=col, padx=8, pady=8, sticky="nsew")

    def _render_empty_state(self, title):
        box = ctk.CTkFrame(self.accounts_container, fg_color=COLOR["card_bg"], corner_radius=12, border_width=1, border_color=COLOR["border"])
        box.pack(fill="x", pady=40, padx=20)
        ctk.CTkLabel(box, text="📭", font=self.font(size=36)).pack(pady=(24, 6))
        ctk.CTkLabel(box, text=f"Нет подключенных аккаунтов {title}", font=self.font(size=15, weight="bold"), text_color=COLOR["text_primary"]).pack()
        ctk.CTkLabel(box, text="Нажмите кнопку '+ Добавить аккаунт' вверху для входа через браузер.", font=self.font(size=12), text_color=COLOR["text_secondary"]).pack(pady=(4, 24))

    # =========================================================================
    # COMPACT CARD (High-contrast Segoe UI, Dual Theme)
    # =========================================================================
    def create_compact_card(self, parent, acc, is_active=False):
        email = acc.get("email", "unknown@gmail.com")
        index = acc.get("index", 1)
        added_at = acc.get("addedAt")
        groups = acc.get("groups", [])

        gemini_group = next((g for g in groups if g.get("name") == "gemini"), None)
        nongemini_group = next((g for g in groups if g.get("name") == "non-gemini"), None)

        card = ctk.CTkFrame(
            parent,
            fg_color=COLOR["card_bg"],
            corner_radius=16,
            border_width=2 if is_active else 1,
            border_color=COLOR["border_active"] if is_active else COLOR["border"],
        )

        # 1. Top Header Row
        header = ctk.CTkFrame(card, fg_color="transparent")
        header.pack(fill="x", padx=16, pady=(14, 8))
        header.grid_columnconfigure(1, weight=1)

        chk_box = ctk.CTkLabel(
            header,
            text="✓" if is_active else " ",
            font=self.font(size=12, weight="bold"),
            fg_color="#0284c7" if is_active else COLOR["subbox_bg"],
            text_color="#ffffff" if is_active else COLOR["border"],
            corner_radius=4,
            width=22,
            height=22,
        )
        chk_box.grid(row=0, column=0, padx=(0, 8))

        short_email = email if len(email) <= 24 else f"{email[:21]}..."
        email_lbl = ctk.CTkLabel(
            header,
            text=short_email,
            font=self.font(size=14, weight="bold"),
            text_color=COLOR["text_primary"],
        )
        email_lbl.grid(row=0, column=1, sticky="w")

        badges_box = ctk.CTkFrame(header, fg_color="transparent")
        badges_box.grid(row=0, column=2, sticky="e")

        if is_active:
            status_badge = ctk.CTkLabel(
                badges_box,
                text="Текущий",
                font=self.font(size=11, weight="bold"),
                fg_color="#16a34a",
                text_color="#ffffff",
                corner_radius=10,
                padx=8,
                pady=2,
            )
            status_badge.pack(side="left", padx=(0, 4))

        pro_badge = ctk.CTkLabel(
            badges_box,
            text="PRO",
            font=self.font(size=11, weight="bold"),
            fg_color="#0284c7",
            text_color="#ffffff",
            corner_radius=10,
            padx=7,
            pady=2,
        )
        pro_badge.pack(side="left")

        # 2. Dual-Column Quota Box (Claude | Gemini)
        quota_box = ctk.CTkFrame(card, fg_color=COLOR["subbox_bg"], corner_radius=12, border_width=1, border_color=COLOR["border"])
        quota_box.pack(fill="x", padx=14, pady=(4, 10))
        quota_box.grid_columnconfigure(0, weight=1)
        quota_box.grid_columnconfigure(1, weight=1)

        self._render_compact_quota_column(quota_box, col=0, title="Claude", group_info=nongemini_group)
        self._render_compact_quota_column(quota_box, col=1, title="Gemini", group_info=gemini_group)

        # 3. Bottom Footer Action Row
        divider = ctk.CTkFrame(card, height=1, fg_color=COLOR["border"])
        divider.pack(fill="x", padx=14, pady=(0, 6))

        footer = ctk.CTkFrame(card, fg_color="transparent")
        footer.pack(fill="x", padx=14, pady=(0, 10))
        footer.grid_columnconfigure(0, weight=1)

        date_str = self.format_added_date(added_at)
        date_pill = ctk.CTkLabel(
            footer,
            text=date_str,
            font=self.font(size=11),
            text_color=COLOR["text_secondary"],
            fg_color=COLOR["subbox_bg"],
            corner_radius=10,
            padx=8,
            pady=2,
        )
        date_pill.grid(row=0, column=0, sticky="w")

        # High-contrast action icon buttons (large, clear, distinct)
        actions_pill = ctk.CTkFrame(footer, fg_color="transparent")
        actions_pill.grid(row=0, column=1, sticky="e")

        # 1. Health check button
        ctk.CTkButton(
            actions_pill,
            text="🩺 Тест",
            font=self.font(size=11, weight="bold"),
            fg_color=COLOR["subbox_bg"],
            hover_color=COLOR["border"],
            text_color=COLOR["text_primary"],
            border_width=1,
            border_color=COLOR["border"],
            width=58,
            height=28,
            corner_radius=6,
            command=lambda a=acc: self.test_google_account_action(a),
        ).pack(side="left", padx=2)

        # 2. Set current button
        ctk.CTkButton(
            actions_pill,
            text="⭐ Выбрать",
            font=self.font(size=11, weight="bold"),
            fg_color="#0284c7" if is_active else COLOR["subbox_bg"],
            hover_color="#0369a1" if is_active else COLOR["border"],
            text_color="#ffffff" if is_active else COLOR["text_primary"],
            border_width=1 if not is_active else 0,
            border_color=COLOR["border"],
            width=76,
            height=28,
            corner_radius=6,
            command=lambda idx=index - 1: self.activate_google_account_action(idx),
        ).pack(side="left", padx=2)

        # 3. Refresh quota button
        ctk.CTkButton(
            actions_pill,
            text="🔄",
            font=self.font(size=14, weight="bold"),
            fg_color=COLOR["subbox_bg"],
            hover_color=COLOR["border"],
            text_color=COLOR["text_primary"],
            border_width=1,
            border_color=COLOR["border"],
            width=32,
            height=28,
            corner_radius=6,
            command=self.refresh_all_async,
        ).pack(side="left", padx=2)

        # 4. Delete button
        ctk.CTkButton(
            actions_pill,
            text="🗑",
            font=self.font(size=14, weight="bold"),
            fg_color=COLOR["subbox_bg"],
            hover_color=("#fee2e2", "#7f1d1d"),
            text_color="#ef4444",
            border_width=1,
            border_color=COLOR["border"],
            width=32,
            height=28,
            corner_radius=6,
            command=lambda a=acc: self.delete_google_account_action(a),
        ).pack(side="left", padx=2)

        return card

    def _render_compact_quota_column(self, parent, col, title, group_info):
        frame = ctk.CTkFrame(parent, fg_color="transparent")
        frame.grid(row=0, column=col, sticky="nsew", padx=10, pady=10)

        ctk.CTkLabel(
            frame,
            text=title,
            font=self.font(size=13, weight="bold"),
            text_color=COLOR["text_primary"],
        ).pack(anchor="w", pady=(0, 4))

        windows = group_info.get("windows", []) if group_info else []

        def window_key(window):
            name = str(window.get("window", "")).strip().lower().replace("_", "-")
            if name in {"5h", "5-hour", "5-hours", "5hr", "5-hr"}:
                return "5h"
            if name in {"weekly", "week", "7d", "7-day", "7-days"}:
                return "weekly"
            return None

        win_5h = next((w for w in windows if window_key(w) == "5h"), None)
        win_weekly = next((w for w in windows if window_key(w) == "weekly"), None)

        if win_5h:
            pct_5h = win_5h.get("remainingPercent", 100.0)
            reset_5h = win_5h.get("resetTime", "")
        elif group_info:
            pct_5h = 100.0
            reset_5h = ""
        else:
            pct_5h = None
            reset_5h = ""

        if win_weekly:
            pct_wk = win_weekly.get("remainingPercent", 100.0)
            reset_wk = win_weekly.get("resetTime", "")
        elif group_info:
            pct_wk = group_info.get("remainingPercent", 100.0)
            reset_wk = group_info.get("resetTime", "")
        else:
            pct_wk = None
            reset_wk = ""

        self._render_compact_subrow(frame, label="5h", pct=pct_5h, reset_iso=reset_5h)
        self._render_compact_subrow(frame, label="Weekly", pct=pct_wk, reset_iso=reset_wk)

    def _render_compact_subrow(self, parent, label, pct, reset_iso):
        rem = round(float(pct), 1) if pct is not None else None
        color = ("#16a34a" if rem > 50 else ("#f59e0b" if rem > 20 else "#ef4444")) if rem is not None else COLOR["text_muted"]

        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", pady=(3, 0))

        ctk.CTkLabel(
            row,
            text=label,
            font=self.font(size=11, weight="bold"),
            text_color=COLOR["text_secondary"],
        ).pack(side="left")

        ctk.CTkLabel(
            row,
            text=f"{int(rem)}%" if rem is not None else "—",
            font=self.font(size=11, weight="bold"),
            text_color=color,
        ).pack(side="right")

        bar = ctk.CTkProgressBar(parent, height=6, corner_radius=3)
        bar.pack(fill="x", pady=(2, 2))
        bar.set(max(0.0, min(1.0, rem / 100.0)) if rem is not None else 0.0)
        bar.configure(progress_color=color, fg_color=COLOR["bar_bg"])

        timer_text = self.format_compact_reset(reset_iso) if rem is not None else "окно квоты недоступно"
        ctk.CTkLabel(
            parent,
            text=timer_text,
            font=self.font(size=10),
            text_color=COLOR["text_muted"],
        ).pack(anchor="w", pady=(0, 4))

    def format_compact_reset(self, reset_value):
        if reset_value is None or reset_value == "":
            return "квота доступна"
        try:
            if isinstance(reset_value, (int, float)):
                timestamp = reset_value / 1000 if reset_value > 1e11 else reset_value
                dt = datetime.datetime.fromtimestamp(timestamp, tz=datetime.timezone.utc)
            else:
                dt = datetime.datetime.fromisoformat(str(reset_value).replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=datetime.timezone.utc)
            local_dt = dt.astimezone()
            now = datetime.datetime.now(datetime.timezone.utc).astimezone()
            diff = local_dt - now

            if diff.total_seconds() <= 0:
                return f"сброшено ({local_dt.strftime('%H:%M')})"

            d = diff.days
            h = int(diff.seconds // 3600)
            m = int((diff.seconds % 3600) // 60)

            dur = f"{d}d {h}h" if d > 0 else (f"{h}h {m}m" if h > 0 else f"{m}m")
            return f"через {dur} ({local_dt.strftime('%H:%M')})"
        except Exception:
            return str(reset_value)[:16]

    def format_added_date(self, ts):
        if not ts:
            return "12.04.2026"
        try:
            if isinstance(ts, (int, float)):
                if ts > 1e11:
                    ts = ts / 1000
                d = datetime.datetime.fromtimestamp(ts)
                return d.strftime("%d.%m.%Y")
            return str(ts)[:10]
        except Exception:
            return "12.04.2026"

    # =========================================================================
    # COMPACT OPENAI CARD (High-contrast Segoe UI, Dual Theme)
    # =========================================================================
    def create_compact_openai_card(self, parent, acc, is_active=False):
        email = acc.get("email", "unknown@chatgpt.com")
        account_id = acc.get("accountId") or acc.get("id") or ""
        plan_type = (acc.get("plan_type") or "plus").upper()
        quota = acc.get("quota") or {}

        primary_quota = quota.get("window_5h") or quota.get("primary") or {}
        secondary_quota = quota.get("window_weekly") or quota.get("secondary") or {}

        card = ctk.CTkFrame(
            parent,
            fg_color=COLOR["card_bg"],
            corner_radius=16,
            border_width=2 if is_active else 1,
            border_color="#10a37f" if is_active else COLOR["border"],
        )

        header = ctk.CTkFrame(card, fg_color="transparent")
        header.pack(fill="x", padx=16, pady=(14, 8))
        header.grid_columnconfigure(1, weight=1)

        chk_box = ctk.CTkLabel(
            header,
            text="✓" if is_active else " ",
            font=self.font(size=12, weight="bold"),
            fg_color="#10a37f" if is_active else COLOR["subbox_bg"],
            text_color="#ffffff" if is_active else COLOR["border"],
            corner_radius=4,
            width=22,
            height=22,
        )
        chk_box.grid(row=0, column=0, padx=(0, 8))

        short_email = email if len(email) <= 24 else f"{email[:21]}..."
        ctk.CTkLabel(
            header,
            text=short_email,
            font=self.font(size=14, weight="bold"),
            text_color=COLOR["text_primary"],
        ).grid(row=0, column=1, sticky="w")

        badges_box = ctk.CTkFrame(header, fg_color="transparent")
        badges_box.grid(row=0, column=2, sticky="e")

        if is_active:
            ctk.CTkLabel(
                badges_box,
                text="Текущий",
                font=self.font(size=11, weight="bold"),
                fg_color="#10a37f",
                text_color="#ffffff",
                corner_radius=10,
                padx=8,
                pady=2,
            ).pack(side="left", padx=(0, 4))

        ctk.CTkLabel(
            badges_box,
            text=plan_type,
            font=self.font(size=11, weight="bold"),
            fg_color="#0284c7",
            text_color="#ffffff",
            corner_radius=10,
            padx=7,
            pady=2,
        ).pack(side="left")

        quota_box = ctk.CTkFrame(card, fg_color=COLOR["subbox_bg"], corner_radius=12, border_width=1, border_color=COLOR["border"])
        quota_box.pack(fill="x", padx=14, pady=(4, 10))
        quota_box.grid_columnconfigure(0, weight=1)
        quota_box.grid_columnconfigure(1, weight=1)

        f1 = ctk.CTkFrame(quota_box, fg_color="transparent")
        f1.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)
        ctk.CTkLabel(f1, text="Лимит 5 часов", font=self.font(size=13, weight="bold"), text_color=COLOR["text_primary"]).pack(anchor="w")
        rem_p = round(float(primary_quota.get("remaining_percent", 100.0)), 1)
        self._render_compact_subrow(f1, "5h", rem_p, primary_quota.get("reset_at"))

        f2 = ctk.CTkFrame(quota_box, fg_color="transparent")
        f2.grid(row=0, column=1, sticky="nsew", padx=10, pady=10)
        ctk.CTkLabel(f2, text="Недельный лимит", font=self.font(size=13, weight="bold"), text_color=COLOR["text_primary"]).pack(anchor="w")
        rem_s = round(float(secondary_quota.get("remaining_percent", 100.0)), 1)
        self._render_compact_subrow(f2, "Weekly", rem_s, secondary_quota.get("reset_at"))

        footer = ctk.CTkFrame(card, fg_color="transparent")
        footer.pack(fill="x", padx=14, pady=(0, 10))
        footer.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            footer,
            text="OpenAI OAuth",
            font=self.font(size=11),
            text_color=COLOR["text_secondary"],
            fg_color=COLOR["subbox_bg"],
            corner_radius=10,
            padx=8,
            pady=2,
        ).grid(row=0, column=0, sticky="w")

        # High-contrast action icon buttons (large, clear, distinct)
        actions_pill = ctk.CTkFrame(footer, fg_color="transparent")
        actions_pill.grid(row=0, column=1, sticky="e")

        ctk.CTkButton(
            actions_pill,
            text="🩺 Тест",
            font=self.font(size=11, weight="bold"),
            fg_color=COLOR["subbox_bg"],
            hover_color=COLOR["border"],
            text_color=COLOR["text_primary"],
            border_width=1,
            border_color=COLOR["border"],
            width=58,
            height=28,
            corner_radius=6,
            command=lambda a=acc: self.test_openai_account_action(a),
        ).pack(side="left", padx=2)

        ctk.CTkButton(
            actions_pill,
            text="⭐ Выбрать",
            font=self.font(size=11, weight="bold"),
            fg_color="#10a37f" if is_active else COLOR["subbox_bg"],
            hover_color="#0e8a6c" if is_active else COLOR["border"],
            text_color="#ffffff" if is_active else COLOR["text_primary"],
            border_width=1 if not is_active else 0,
            border_color=COLOR["border"],
            width=76,
            height=28,
            corner_radius=6,
            command=lambda aid=account_id: self.activate_openai_account_action(aid),
        ).pack(side="left", padx=2)

        ctk.CTkButton(
            actions_pill,
            text="🗑",
            font=self.font(size=14, weight="bold"),
            fg_color=COLOR["subbox_bg"],
            hover_color=("#fee2e2", "#7f1d1d"),
            text_color="#ef4444",
            border_width=1,
            border_color=COLOR["border"],
            width=32,
            height=28,
            corner_radius=6,
            command=lambda a=acc: self.delete_openai_account_action(a),
        ).pack(side="left", padx=2)

        return card

    # =========================================================================
    # SETTINGS VIEW
    # =========================================================================
    def create_settings_view(self):
        self.settings_frame = ctk.CTkScrollableFrame(self.content_area, fg_color=COLOR["bg"])
        self.settings_frame.grid_columnconfigure(0, weight=1)

        update_card = ctk.CTkFrame(self.settings_frame, fg_color=COLOR["card_bg"], corner_radius=12, border_width=1, border_color=COLOR["border"])
        update_card.pack(fill="x", pady=6)
        ctk.CTkLabel(
            update_card,
            text="Обновление Antigravity Hub",
            font=self.font(size=14, weight="bold"),
            text_color=COLOR["text_primary"],
        ).pack(anchor="w", padx=16, pady=(12, 4))
        self.btn_check_update = ctk.CTkButton(
            update_card,
            text="🔄 Проверить обновления",
            font=self.font(size=12, weight="bold"),
            command=self.manual_check_updates_action,
            height=34,
        )
        self.btn_check_update.pack(anchor="w", padx=16, pady=(4, 12))

        c1 = ctk.CTkFrame(self.settings_frame, fg_color=COLOR["card_bg"], corner_radius=12, border_width=1, border_color=COLOR["border"])
        c1.pack(fill="x", pady=6)
        ctk.CTkLabel(c1, text="Стратегия выбора аккаунтов", font=self.font(size=14, weight="bold"), text_color=COLOR["text_primary"]).pack(anchor="w", padx=16, pady=(12, 4))

        current_strat = self.config_data.get("account_selection_strategy", "hybrid")
        self.strategy_var = tk.StringVar(value=current_strat)
        self.strategy_seg = ctk.CTkSegmentedButton(
            c1,
            values=["hybrid", "sticky", "round-robin"],
            variable=self.strategy_var,
            font=self.font(size=12, weight="bold"),
            command=self.on_strategy_change,
        )
        self.strategy_seg.pack(anchor="w", padx=16, pady=(0, 8))
        self.strategy_desc = ctk.CTkLabel(c1, text="", font=self.font(size=11), text_color="#0284c7")
        self.strategy_desc.pack(anchor="w", padx=16, pady=(0, 12))
        self.update_strategy_description(current_strat)

        c2 = ctk.CTkFrame(self.settings_frame, fg_color=COLOR["card_bg"], corner_radius=12, border_width=1, border_color=COLOR["border"])
        c2.pack(fill="x", pady=6)
        ctk.CTkLabel(c2, text="Мгновенное переключение при Rate Limit (429)", font=self.font(size=14, weight="bold"), text_color=COLOR["text_primary"]).pack(anchor="w", padx=16, pady=(12, 4))
        self.rate_limit_var = tk.BooleanVar(value=self.config_data.get("switch_on_first_rate_limit", True))
        ctk.CTkSwitch(c2, text="Включено", variable=self.rate_limit_var).pack(anchor="w", padx=16, pady=(0, 12))

        close_card = ctk.CTkFrame(self.settings_frame, fg_color=COLOR["card_bg"], corner_radius=12, border_width=1, border_color=COLOR["border"])
        close_card.pack(fill="x", pady=6)
        ctk.CTkLabel(
            close_card,
            text="Поведение при нажатии на крестик",
            font=self.font(size=14, weight="bold"),
            text_color=COLOR["text_primary"],
        ).pack(anchor="w", padx=16, pady=(12, 4))
        self.close_choice_remember_var = tk.BooleanVar(
            value=self.config_data.get("close_choice_remembered", False)
        )
        ctk.CTkCheckBox(
            close_card,
            text="Запоминать выбранное действие (свернуть в трей / закрыть приложение)",
            variable=self.close_choice_remember_var,
            command=self.on_close_choice_remember_changed,
            font=self.font(size=11),
        ).pack(anchor="w", padx=16, pady=(0, 12))

        # 3. DNS Configuration (Cockpit / Bezmezhau layout: Standard DNS, DoT, DoH)
        c3 = ctk.CTkFrame(self.settings_frame, fg_color=COLOR["card_bg"], corner_radius=12, border_width=1, border_color=COLOR["border"])
        c3.pack(fill="x", pady=6)
        ctk.CTkLabel(c3, text="🌐 DNS-серверы и маршрутизация", font=self.font(size=14, weight="bold"), text_color=COLOR["text_primary"]).pack(anchor="w", padx=16, pady=(12, 4))
        ctk.CTkLabel(
            c3,
            text="DNS применяется внутри сетевых компонентов Antigravity Hub/OpenCode; системный DNS Windows не меняется.",
            font=self.font(size=11),
            text_color=COLOR["text_secondary"]
        ).pack(anchor="w", padx=16, pady=(0, 10))

        dns_notice = ctk.CTkFrame(c3, fg_color=COLOR["subbox_bg"], corner_radius=8, border_width=1, border_color=COLOR["border"])
        dns_notice.pack(fill="x", padx=16, pady=(0, 10))
        ctk.CTkLabel(
            dns_notice,
            text=(
                "Как работают DNS и туннель\n"
                "• Выбранный протокол (Обычный DNS / DoT / DoH) используется для DNS-запросов, которые выполняют плагин и встроенный туннель.\n"
                "• Локальный адрес http://127.0.0.1:51180 Hub настраивает как прокси OpenCode. Запросы через него разрешаются DNS-сервером, выбранным выше.\n"
                "• Важно: OpenCode может применять переменные прокси ко всему своему HTTPS-трафику, а не только к OpenAI. Поэтому через туннель могут идти запросы и других сервисов.\n"
                "• Кнопки «Проверить доступность» проверяют DNS-резолвер, но не гарантируют успешную авторизацию, доступность модели или наличие квоты. После изменения настроек перезапустите OpenCode из Hub."
            ),
            font=self.font(size=11),
            text_color=COLOR["text_secondary"],
            justify="left",
            anchor="w",
            wraplength=980
        ).pack(fill="x", padx=12, pady=10)

        # DNS Mode Selector (Standard / DoT / DoH / System)
        mode_row = ctk.CTkFrame(c3, fg_color="transparent")
        mode_row.pack(fill="x", padx=16, pady=(0, 10))
        ctk.CTkLabel(mode_row, text="Активный протокол:", font=self.font(size=12, weight="bold"), text_color=COLOR["text_primary"]).pack(side="left", padx=(0, 10))

        dns_mode_labels = {"standard": "Обычный DNS", "dot": "DNS-over-TLS (DoT)", "doh": "DNS-over-HTTPS (DoH)", "system": "Системный DNS"}
        self.dns_mode_var = tk.StringVar(value=dns_mode_labels.get(self.config_data.get("dns_mode", "standard"), "Обычный DNS"))
        self.dns_mode_seg = ctk.CTkSegmentedButton(
            mode_row,
            values=["Обычный DNS", "DNS-over-TLS (DoT)", "DNS-over-HTTPS (DoH)", "Системный DNS"],
            variable=self.dns_mode_var,
            font=self.font(size=11, weight="bold"),
            command=self.on_dns_mode_change,
        )
        self.dns_mode_seg.pack(side="left")

        # Three side-by-side DNS Blocks (Like the user's screenshot)
        dns_blocks_container = ctk.CTkFrame(c3, fg_color="transparent")
        dns_blocks_container.pack(fill="x", padx=16, pady=(0, 12))
        dns_blocks_container.grid_columnconfigure(0, weight=1, uniform="dns_col")
        dns_blocks_container.grid_columnconfigure(1, weight=1, uniform="dns_col")
        dns_blocks_container.grid_columnconfigure(2, weight=1, uniform="dns_col")

        # --- BLOCK 1: Standard DNS ---
        b1 = ctk.CTkFrame(dns_blocks_container, fg_color=COLOR["subbox_bg"], corner_radius=10, border_width=1, border_color=COLOR["border"])
        b1.grid(row=0, column=0, sticky="nsew", padx=(0, 6), pady=4)

        b1_hdr = ctk.CTkFrame(b1, fg_color="transparent")
        b1_hdr.pack(fill="x", padx=12, pady=(10, 4))
        ctk.CTkLabel(b1_hdr, text="Обычный DNS", font=self.font(size=12, weight="bold"), text_color=COLOR["text_primary"]).pack(side="left")

        ctk.CTkLabel(b1, text="Основной DNS (Primary):", font=self.font(size=10), text_color=COLOR["text_secondary"]).pack(anchor="w", padx=12, pady=(2, 0))
        self.dns_primary_entry = ctk.CTkEntry(b1, font=self.font(size=11), height=28, fg_color=COLOR["card_bg"], border_color=COLOR["border"], text_color=COLOR["text_primary"])
        self.dns_primary_entry.pack(fill="x", padx=12, pady=(2, 6))
        current_dns_list = self.config_data.get("custom_dns", ["143.20.64.55", "31.58.216.201"])
        self.dns_primary_entry.insert(0, current_dns_list[0] if len(current_dns_list) > 0 else "143.20.64.55")

        ctk.CTkLabel(b1, text="Дополнительный DNS (Secondary):", font=self.font(size=10), text_color=COLOR["text_secondary"]).pack(anchor="w", padx=12, pady=(2, 0))
        self.dns_secondary_entry = ctk.CTkEntry(b1, font=self.font(size=11), height=28, fg_color=COLOR["card_bg"], border_color=COLOR["border"], text_color=COLOR["text_primary"])
        self.dns_secondary_entry.pack(fill="x", padx=12, pady=(2, 6))
        self.dns_secondary_entry.insert(0, current_dns_list[1] if len(current_dns_list) > 1 else "31.58.216.201")

        b1_btn_row = ctk.CTkFrame(b1, fg_color="transparent")
        b1_btn_row.pack(fill="x", padx=12, pady=(4, 10))
        self.btn_test_std_dns = ctk.CTkButton(
            b1_btn_row,
            text="🩺 Проверить доступность",
            font=self.font(size=11, weight="bold"),
            fg_color="#0284c7",
            hover_color="#0369a1",
            height=26,
            command=self.test_standard_dns_action,
        )
        self.btn_test_std_dns.pack(fill="x")
        self.lbl_test_std_dns = ctk.CTkLabel(b1, text="", font=self.font(size=10), text_color="#16a34a")
        self.lbl_test_std_dns.pack(anchor="w", padx=12, pady=(0, 6))

        # --- BLOCK 2: DNS-over-TLS (DoT) ---
        b2 = ctk.CTkFrame(dns_blocks_container, fg_color=COLOR["subbox_bg"], corner_radius=10, border_width=1, border_color=COLOR["border"])
        b2.grid(row=0, column=1, sticky="nsew", padx=6, pady=4)

        b2_hdr = ctk.CTkFrame(b2, fg_color="transparent")
        b2_hdr.pack(fill="x", padx=12, pady=(10, 4))
        ctk.CTkLabel(b2_hdr, text="DNS-over-TLS (DoT)", font=self.font(size=12, weight="bold"), text_color=COLOR["text_primary"]).pack(side="left")

        ctk.CTkLabel(b2, text="Имя хоста DoT (порт 853):", font=self.font(size=10), text_color=COLOR["text_secondary"]).pack(anchor="w", padx=12, pady=(2, 0))
        self.dot_host_entry = ctk.CTkEntry(b2, font=self.font(size=11), height=28, fg_color=COLOR["card_bg"], border_color=COLOR["border"], text_color=COLOR["text_primary"])
        self.dot_host_entry.pack(fill="x", padx=12, pady=(2, 6))
        self.dot_host_entry.insert(0, self.config_data.get("dot_host", "dns.bezmezhau.com"))

        ctk.CTkLabel(b2, text="Для защищённого TLS-резолвинга\nбез перехвата провайдером.", font=self.font(size=10), text_color=COLOR["text_muted"], justify="left").pack(anchor="w", padx=12, pady=(2, 6))

        b2_btn_row = ctk.CTkFrame(b2, fg_color="transparent")
        b2_btn_row.pack(fill="x", padx=12, pady=(4, 10))
        self.btn_test_dot = ctk.CTkButton(
            b2_btn_row,
            text="🩺 Проверить доступность",
            font=self.font(size=11, weight="bold"),
            fg_color="#0284c7",
            hover_color="#0369a1",
            height=26,
            command=self.test_dot_action,
        )
        self.btn_test_dot.pack(fill="x")
        self.lbl_test_dot = ctk.CTkLabel(b2, text="", font=self.font(size=10), text_color="#16a34a")
        self.lbl_test_dot.pack(anchor="w", padx=12, pady=(0, 6))

        # --- BLOCK 3: DNS-over-HTTPS (DoH) ---
        b3 = ctk.CTkFrame(dns_blocks_container, fg_color=COLOR["subbox_bg"], corner_radius=10, border_width=1, border_color=COLOR["border"])
        b3.grid(row=0, column=2, sticky="nsew", padx=(6, 0), pady=4)

        b3_hdr = ctk.CTkFrame(b3, fg_color="transparent")
        b3_hdr.pack(fill="x", padx=12, pady=(10, 4))
        ctk.CTkLabel(b3_hdr, text="DNS-over-HTTPS (DoH)", font=self.font(size=12, weight="bold"), text_color=COLOR["text_primary"]).pack(side="left")

        ctk.CTkLabel(b3, text="URL эндпоинта DoH:", font=self.font(size=10), text_color=COLOR["text_secondary"]).pack(anchor="w", padx=12, pady=(2, 0))
        self.doh_url_entry = ctk.CTkEntry(b3, font=self.font(size=11), height=28, fg_color=COLOR["card_bg"], border_color=COLOR["border"], text_color=COLOR["text_primary"])
        self.doh_url_entry.pack(fill="x", padx=12, pady=(2, 6))
        self.doh_url_entry.insert(0, self.config_data.get("doh_url", "https://dns.bezmezhau.com/dns-query"))

        ctk.CTkLabel(b3, text="Стандарт RFC 8484 по HTTPS.\nМаксимальная скрытность.", font=self.font(size=10), text_color=COLOR["text_muted"], justify="left").pack(anchor="w", padx=12, pady=(2, 6))

        b3_btn_row = ctk.CTkFrame(b3, fg_color="transparent")
        b3_btn_row.pack(fill="x", padx=12, pady=(4, 10))
        self.btn_test_doh = ctk.CTkButton(
            b3_btn_row,
            text="🩺 Проверить доступность",
            font=self.font(size=11, weight="bold"),
            fg_color="#0284c7",
            hover_color="#0369a1",
            height=26,
            command=self.test_doh_action,
        )
        self.btn_test_doh.pack(fill="x")
        self.lbl_test_doh = ctk.CTkLabel(b3, text="", font=self.font(size=10), text_color="#16a34a")
        self.lbl_test_doh.pack(anchor="w", padx=12, pady=(0, 6))

        # Proxy Row
        proxy_row = ctk.CTkFrame(c3, fg_color="transparent")
        proxy_row.pack(fill="x", padx=16, pady=(0, 14))
        ctk.CTkLabel(proxy_row, text="Прокси для Antigravity (необязательно):", font=self.font(size=11, weight="bold"), text_color=COLOR["text_primary"], width=250, anchor="w").pack(side="left")
        self.proxy_entry = ctk.CTkEntry(
            proxy_row,
            placeholder_text="Оставьте пустым для встроенного туннеля OpenCode",
            font=self.font(size=11),
            height=30,
            fg_color=COLOR["subbox_bg"],
            border_color=COLOR["border"],
            text_color=COLOR["text_primary"]
        )
        self.proxy_entry.pack(side="left", fill="x", expand=True)
        self.proxy_entry.insert(0, self.config_data.get("proxy", "") or "")

        ctk.CTkButton(
            self.settings_frame,
            text="💾 Сохранить настройки",
            font=self.font(size=13, weight="bold"),
            fg_color="#0284c7",
            hover_color="#0369a1",
            height=36,
            command=self.save_settings_action,
        ).pack(anchor="w", pady=12)

    def on_strategy_change(self, val):
        self.update_strategy_description(val)

    def update_strategy_description(self, strat):
        descs = {
            "hybrid": "⭐ Рекомендуется: сохраняет контекст сессии на одном аккаунте, но плавно ротирует при исчерпании лимитов.",
            "sticky": "📌 Последовательная: работает с одним аккаунтом до полного отказа, затем переходит к следующему.",
            "round-robin": "🔄 Равномерная: распределяет каждый новый запрос по очереди между всеми аккаунтами.",
        }
        self.strategy_desc.configure(text=descs.get(strat, ""))

    def on_dns_mode_change(self, val):
        pass

    def test_standard_dns_action(self):
        p_ip = self.dns_primary_entry.get().strip()
        self.btn_test_std_dns.configure(state="disabled", text="⏳ Проверка...")

        def _test():
            res = dns_tester.test_standard_dns(p_ip or "143.20.64.55")
            def _update():
                self.btn_test_std_dns.configure(state="normal", text="🩺 Проверить доступность")
                if res.get("ok"):
                    self.lbl_test_std_dns.configure(text=f"✅ {res.get('message')}", text_color="#16a34a")
                else:
                    self.lbl_test_std_dns.configure(text=f"❌ {res.get('message')}", text_color="#ef4444")
            self.after(0, _update)

        threading.Thread(target=_test, daemon=True).start()

    def test_dot_action(self):
        host = self.dot_host_entry.get().strip()
        self.btn_test_dot.configure(state="disabled", text="⏳ Проверка...")

        def _test():
            res = dns_tester.test_dot_endpoint(host or "dns.bezmezhau.com")
            def _update():
                self.btn_test_dot.configure(state="normal", text="🩺 Проверить доступность")
                if res.get("ok"):
                    self.lbl_test_dot.configure(text=f"✅ {res.get('message')}", text_color="#16a34a")
                else:
                    self.lbl_test_dot.configure(text=f"❌ {res.get('message')}", text_color="#ef4444")
            self.after(0, _update)

        threading.Thread(target=_test, daemon=True).start()

    def test_doh_action(self):
        url = self.doh_url_entry.get().strip()
        self.btn_test_doh.configure(state="disabled", text="⏳ Проверка...")

        def _test():
            res = dns_tester.test_doh_endpoint(url or "https://dns.bezmezhau.com/dns-query")
            def _update():
                self.btn_test_doh.configure(state="normal", text="🩺 Проверить доступность")
                if res.get("ok"):
                    self.lbl_test_doh.configure(text=f"✅ {res.get('message')}", text_color="#16a34a")
                else:
                    self.lbl_test_doh.configure(text=f"❌ {res.get('message')}", text_color="#ef4444")
            self.after(0, _update)

        threading.Thread(target=_test, daemon=True).start()

    def on_close_choice_remember_changed(self):
        enabled = self.close_choice_remember_var.get()
        self.config_data["close_choice_remembered"] = enabled
        if not enabled:
            self.config_data.pop("close_choice", None)
        self.save_config()

    def save_settings_action(self):
        self.config_data["account_selection_strategy"] = self.strategy_var.get()
        self.config_data["switch_on_first_rate_limit"] = self.rate_limit_var.get()

        # Save DNS Mode
        selected_mode = self.dns_mode_var.get()
        if "DoT" in selected_mode:
            self.config_data["dns_mode"] = "dot"
        elif "DoH" in selected_mode:
            self.config_data["dns_mode"] = "doh"
        elif "Системный" in selected_mode:
            self.config_data["dns_mode"] = "system"
        else:
            self.config_data["dns_mode"] = "standard"

        # Save Standard DNS
        p_ip = self.dns_primary_entry.get().strip()
        s_ip = self.dns_secondary_entry.get().strip()
        dns_list = []
        if p_ip: dns_list.append(p_ip)
        if s_ip: dns_list.append(s_ip)
        if dns_list:
            self.config_data["custom_dns"] = dns_list
        else:
            self.config_data.pop("custom_dns", None)

        # Save DoT Host
        dot_val = self.dot_host_entry.get().strip()
        if dot_val:
            self.config_data["dot_host"] = dot_val
        else:
            self.config_data.pop("dot_host", None)

        # Save DoH URL
        doh_val = self.doh_url_entry.get().strip()
        if doh_val:
            self.config_data["doh_url"] = doh_val
        else:
            self.config_data.pop("doh_url", None)

        # Save Proxy for Antigravity:
        # Antigravity uses its own direct transport with custom DNS (DoH/DoT/Standard).
        # We only save proxy to antigravity.json if the user explicitly provided an external proxy.
        user_proxy = self.proxy_entry.get().strip()
        if user_proxy and user_proxy != "http://127.0.0.1:51180":
            self.config_data["proxy"] = user_proxy
        else:
            self.config_data.pop("proxy", None)

        # Synchronize proxy to opencode.json strictly for OpenAI provider:
        # OpenAI/ChatGPT will use http://127.0.0.1:51180 (or user proxy), while Antigravity stays on direct DNS.
        try:
            opencode_cfg_path = Path.home() / ".config" / "opencode" / "opencode.json"
            if opencode_cfg_path.exists():
                oc_data = json.loads(opencode_cfg_path.read_text(encoding="utf-8"))
                dns_active = self.config_data.get("dns_mode") in ("standard", "dot", "doh")
                effective_openai_proxy = user_proxy if (user_proxy and user_proxy != "http://127.0.0.1:51180") else ("http://127.0.0.1:51180" if dns_active else None)

                if effective_openai_proxy:
                    if "provider" not in oc_data:
                        oc_data["provider"] = {}
                    if "openai" not in oc_data["provider"]:
                        oc_data["provider"]["openai"] = {}
                    if "options" not in oc_data["provider"]["openai"]:
                        oc_data["provider"]["openai"]["options"] = {}
                    oc_data["provider"]["openai"]["options"]["proxy"] = effective_openai_proxy
                else:
                    if "provider" in oc_data and "openai" in oc_data["provider"]:
                        if "options" in oc_data["provider"]["openai"]:
                            oc_data["provider"]["openai"]["options"].pop("proxy", None)
                opencode_cfg_path.write_text(json.dumps(oc_data, indent=4, ensure_ascii=False), encoding="utf-8")
        except Exception as e:
            print(f"Warning: Failed to sync proxy to opencode.json: {e}")

        ok, msg = self.save_config()
        if ok:
            messagebox.showinfo("Успешно", "Настройки сохранены!\n\n• Antigravity (Google/Claude) работает напрямую через указанный DNS.\n• OpenAI/ChatGPT изолированно направляется через локальный туннель.")
        else:
            messagebox.showerror("Ошибка", msg)

    # =========================================================================
    # SYSTEM VIEW
    # =========================================================================
    def create_system_view(self):
        self.system_frame = ctk.CTkScrollableFrame(self.content_area, fg_color=COLOR["bg"])
        self.system_frame.grid_columnconfigure(0, weight=1)

        c1 = ctk.CTkFrame(self.system_frame, fg_color=COLOR["card_bg"], corner_radius=12, border_width=1, border_color=COLOR["border"])
        c1.pack(fill="x", pady=6)
        ctk.CTkLabel(c1, text="Управление OpenCode", font=self.font(size=14, weight="bold"), text_color=COLOR["text_primary"]).pack(anchor="w", padx=16, pady=(12, 6))

        row = ctk.CTkFrame(c1, fg_color="transparent")
        row.pack(fill="x", padx=16, pady=(0, 14))

        ctk.CTkButton(row, text="🔄 Перезапустить", fg_color="#2563eb", command=self.restart_opencode_action).pack(side="left", padx=(0, 8))
        ctk.CTkButton(row, text="⏹ Остановить", fg_color="#ef4444", command=self.stop_opencode_action).pack(side="left", padx=(0, 8))
        ctk.CTkButton(row, text="▶ Запустить", fg_color="#10b981", command=self.start_opencode_action).pack(side="left")

        c2 = ctk.CTkFrame(self.system_frame, fg_color=COLOR["card_bg"], corner_radius=12, border_width=1, border_color=COLOR["border"])
        c2.pack(fill="x", pady=6)
        ctk.CTkLabel(c2, text="Быстрый доступ к папкам", font=self.font(size=14, weight="bold"), text_color=COLOR["text_primary"]).pack(anchor="w", padx=16, pady=(12, 6))

        r2 = ctk.CTkFrame(c2, fg_color="transparent")
        r2.pack(fill="x", padx=16, pady=(0, 14))
        ctk.CTkButton(r2, text="📂 Конфиги (~/.config/opencode)", fg_color=COLOR["subbox_bg"], text_color=COLOR["text_primary"], command=lambda: open_path(CONFIG_DIR)).pack(side="left", padx=(0, 8))
        ctk.CTkButton(r2, text="📂 Логи", fg_color=COLOR["subbox_bg"], text_color=COLOR["text_primary"], command=lambda: open_path(LOG_DIR)).pack(side="left")

    # =========================================================================
    # STATUSBAR
    # =========================================================================
    def create_statusbar(self):
        self.statusbar = ctk.CTkFrame(self.main_frame, height=28, corner_radius=0, fg_color=COLOR["statusbar_bg"], border_width=1, border_color=COLOR["border"])
        self.statusbar.pack(fill="x", side="bottom")

        self.lbl_status = ctk.CTkLabel(
            self.statusbar,
            text="Готов к работе",
            font=self.font(size=11),
            text_color=COLOR["text_muted"],
        )
        self.lbl_status.pack(side="left", padx=16)

        self.lbl_auto_refresh = ctk.CTkLabel(
            self.statusbar,
            text="⏱ Автообновление: 10:00",
            font=self.font(size=11),
            text_color="#0284c7",
        )
        self.lbl_auto_refresh.pack(side="right", padx=16)

    def set_status(self, text):
        self.lbl_status.configure(text=text)

    # =========================================================================
    # TIMERS & ACTIONS
    # =========================================================================
    def start_countdown_timer(self):
        self._countdown_tick()

    def _countdown_tick(self):
        if self.auto_refresh_enabled:
            if self.countdown_seconds <= 0:
                self.countdown_seconds = self.auto_refresh_interval_min * 60
                if not self.is_loading:
                    self.refresh_all_async()
            else:
                self.countdown_seconds -= 1

            mins = self.countdown_seconds // 60
            secs = self.countdown_seconds % 60
            self.lbl_auto_refresh.configure(
                text=f"⏱ Автообновление: {mins:02d}:{secs:02d}",
            )

            if hasattr(self, "token_refresh_countdown"):
                if self.token_refresh_countdown <= 0:
                    self.token_refresh_countdown = self.token_refresh_interval_min * 60
                    self.run_background_token_refresh_silent()
                else:
                    self.token_refresh_countdown -= 1

        self.after(1000, self._countdown_tick)

    def run_background_token_refresh_silent(self):
        def _bg_refresher():
            try:
                node_exe = get_node_executable()
                cli_js = get_cli_js()
                if os.path.exists(node_exe) and os.path.exists(cli_js):
                    run_silent_cmd([node_exe, cli_js, "quota", "--refresh", "--json"], timeout=25)
                try:
                    openai_manager.refresh_all_openai_accounts()
                except Exception:
                    pass
            except Exception as e:
                print(f"Token refresh warning: {e}")

        threading.Thread(target=_bg_refresher, daemon=True).start()

    def refresh_all_async(self):
        if self.is_loading:
            return
        self.is_loading = True
        self.btn_refresh.configure(state="disabled", text="⏳ Загрузка...")
        self.set_status("Получение актуальных данных о квотах...")
        self.countdown_seconds = self.auto_refresh_interval_min * 60

        threading.Thread(target=self._worker_refresh_quotas, daemon=True).start()

    def _worker_refresh_quotas(self):
        google_accounts = []
        try:
            node_exe = get_node_executable()
            cli_js = get_cli_js()
            if os.path.exists(node_exe) and os.path.exists(cli_js):
                cmd = [node_exe, cli_js, "quota", "--refresh", "--json"]
                result = run_silent_cmd(cmd, timeout=20)
                if result.returncode == 0 and result.stdout.strip():
                    try:
                        data = json.loads(result.stdout)
                        google_accounts = data.get("accounts", [])
                    except Exception:
                        pass
                if not google_accounts:
                    cmd = [node_exe, cli_js, "quota", "--json"]
                    result = run_silent_cmd(cmd, timeout=10)
                    if result.returncode == 0 and result.stdout.strip():
                        try:
                            data = json.loads(result.stdout)
                            google_accounts = data.get("accounts", [])
                        except Exception:
                            pass
        except Exception as e:
            print(f"Error fetching Google quotas: {e}")

        try:
            google_accounts = enrich_google_accounts_with_generation_store(google_accounts)
        except Exception as e:
            print(f"Error enriching Google accounts: {e}")

        openai_accounts = []
        rotate_msg = None
        try:
            openai_accounts, rotate_msg = openai_manager.refresh_all_openai_accounts()
        except Exception as e:
            print(f"Error fetching OpenAI quotas: {e}")
            try:
                openai_accounts = openai_manager.load_openai_accounts()
            except Exception:
                openai_accounts = []

        try:
            self.after(0, lambda: self._on_quotas_fetched(google_accounts, openai_accounts, rotate_msg))
        except Exception as e:
            print(f"Callback error: {e}")

    def _on_quotas_fetched(self, google_accounts, openai_accounts, rotate_msg=None):
        self.accounts_data = google_accounts
        self.openai_accounts_data = openai_accounts
        self.render_accounts()
        self.is_loading = False
        self.btn_refresh.configure(state="normal", text="🔄 Обновить квоты")
        now_str = datetime.datetime.now().strftime("%H:%M:%S")
        self.countdown_seconds = self.auto_refresh_interval_min * 60
        if rotate_msg:
            self.set_status(f"🔄 {rotate_msg}")
        else:
            self.set_status(f"Квоты обновлены в {now_str}")
        self.update_opencode_status()

    def add_account_action(self):
        self.btn_add_account.configure(state="disabled", text="⏳ Открываем...")
        self.set_status("Ожидание входа в Google через браузер...")

        def _do_add():
            try:
                node_exe = get_node_executable()
                cli_js = get_cli_js()
                cmd = [node_exe, cli_js, "login"]
                proc = run_silent_cmd(cmd, timeout=300)
                success = proc.returncode == 0
                output = proc.stdout + proc.stderr
                if success:
                    run_silent_cmd([node_exe, cli_js, "migrate", "--offline", "--yes"], timeout=30)
            except Exception as e:
                success = False
                output = str(e)
            self.after(0, lambda: self._on_account_added(success, output))

        threading.Thread(target=_do_add, daemon=True).start()

    def _on_account_added(self, success, output):
        self.btn_add_account.configure(state="normal", text="➕ Добавить Google")
        if success:
            messagebox.showinfo("Успешно!", "Google аккаунт авторизован и добавлен в пул!")
            self.refresh_all_async()
        else:
            messagebox.showerror("Ошибка входа", f"Не удалось завершить вход:\n{output[:300]}")

    def activate_google_account_action(self, target_idx: int):
        ok = set_active_google_account_index(target_idx)
        if ok:
            email = self.accounts_data[target_idx].get("email", f"#{target_idx+1}") if target_idx < len(self.accounts_data) else f"#{target_idx+1}"
            self.show_flash(f"Переключено на {email}")
            self.set_status(f"Активный аккаунт: #{target_idx + 1}")
            self.render_accounts()
        else:
            messagebox.showerror("Ошибка", "Не удалось сменить активный аккаунт.")

    def delete_google_account_action(self, acc):
        email = acc.get("email", "unknown")
        if not messagebox.askyesno("Удаление", f"Удалить Google аккаунт {email} из ротации?", icon="warning"):
            return
        if delete_google_account(email):
            self.show_flash(f"Аккаунт {email} удален")
            self.refresh_all_async()
        else:
            messagebox.showerror("Ошибка", f"Не удалось удалить {email}")

    def add_openai_account_action(self):
        self.btn_add_account.configure(state="disabled", text="⏳ Открываем...")
        self.set_status("Ожидание входа в ChatGPT через браузер...")

        def _do_login():
            try:
                success, message, new_acc = openai_manager.login_openai_browser(timeout=300)
            except Exception as e:
                success, message, new_acc = False, str(e), None
            self.after(0, lambda: self._on_openai_added(success, message, new_acc))

        threading.Thread(target=_do_login, daemon=True).start()

    def _on_openai_added(self, success, message, new_acc):
        self.btn_add_account.configure(state="normal", text="➕ Добавить OpenAI")
        if success and new_acc:
            messagebox.showinfo("Успешно!", f"Аккаунт {new_acc.get('email')} добавлен в OpenCode!")
            self.refresh_all_async()
        else:
            messagebox.showerror("Ошибка входа", message)

    def activate_openai_account_action(self, account_id):
        if openai_manager.set_active_openai_account(account_id):
            self.openai_accounts_data = openai_manager.load_openai_accounts()
            self.show_flash("Аккаунт ChatGPT активирован в OpenCode")
            self.render_accounts()
        else:
            messagebox.showerror("Ошибка", "Не удалось активировать аккаунт.")

    def delete_openai_account_action(self, acc):
        email = acc.get("email", "unknown")
        if not messagebox.askyesno("Удаление", f"Удалить аккаунт {email}?"):
            return
        openai_manager.remove_openai_account(acc.get("accountId") or acc.get("id"))
        self.openai_accounts_data = openai_manager.load_openai_accounts()
        self.show_flash(f"Аккаунт {email} удален")
        self.render_accounts()

    def test_google_account_action(self, acc):
        email = acc.get("email", "unknown")
        self.set_status(f"🩺 Проверка {email}...")

        exported_accs = export_google_accounts()
        matched = next((a for a in exported_accs if a.get("email") == email or a.get("id") == acc.get("id")), None)
        target_dict = matched or acc

        def _do_test():
            res = health_checker.test_google_account_health(target_dict)
            self.after(0, lambda: self._on_google_tested(email, res))

        threading.Thread(target=_do_test, daemon=True).start()

    def _on_google_tested(self, email, res):
        ok = res.get("ok", False)
        latency = res.get("latency_ms", 0)
        has_claude = res.get("has_claude", False)
        has_gemini = res.get("has_gemini", False)

        if ok:
            claude_status = "✅ Доступен (Opus / Sonnet 4.6)" if has_claude else "⚠️ Не найден"
            gemini_status = "✅ Доступен (Gemini 3.8 / Pro)" if has_gemini else "⚠️ Не найден"
            info_text = (
                f"Аккаунт: {email}\n\n"
                f"• Пинг: 🟢 {latency} мс\n"
                f"• Google OAuth: Валиден\n"
                f"• Claude: {claude_status}\n"
                f"• Gemini: {gemini_status}\n\n"
                f"⚡ Готов к работе в OpenCode!"
            )
            messagebox.showinfo("🩺 Результат теста", info_text)
            self.set_status(f"Тест {email} пройден ({latency} мс)")
        else:
            messagebox.showwarning("🩺 Ошибка теста", f"Аккаунт {email} не прошёл проверку:\n{res.get('message')}")

    def test_openai_account_action(self, acc):
        email = acc.get("email", "unknown")
        self.set_status(f"🩺 Проверка {email}...")

        def _do_test():
            res = health_checker.test_openai_account_health(acc)
            self.after(0, lambda: self._on_openai_tested(email, res))

        threading.Thread(target=_do_test, daemon=True).start()

    def _on_openai_tested(self, email, res):
        ok = res.get("ok", False)
        latency = res.get("latency_ms", 0)
        if ok:
            messagebox.showinfo("🩺 Результат теста", f"Аккаунт: {email}\n\n• Пинг: 🟢 {latency} мс\n• Сессия: Активна\n• Модели: Доступны")
        else:
            messagebox.showwarning("🩺 Ошибка теста", f"Ошибка: {res.get('message')}")

    def export_accounts_action(self):
        want_pwd = messagebox.askyesno(
            "Шифрование",
            "Защитить резервную копию паролем?\n\n• Да — зашифрованный файл .agb\n• Нет — обычный JSON",
            icon="question"
        )
        password = None
        if want_pwd:
            pwd_dialog = ctk.CTkInputDialog(title="Пароль", text="Введите пароль:")
            password = pwd_dialog.get_input()
            if not password:
                return

        ext = ".agb" if password else ".json"
        file_path = filedialog.asksaveasfilename(
            title="Экспорт",
            defaultextension=ext,
            initialfile=f"antigravity_backup{ext}",
            filetypes=[("Файл бэкапа", f"*{ext}")],
        )
        if not file_path:
            return

        try:
            google_accs = export_google_accounts()
            openai_accs = openai_manager.load_openai_accounts()
            backup_data = {
                "schemaVersion": 2,
                "exported_at": datetime.datetime.now().isoformat(),
                "google_accounts": google_accs,
                "openai_accounts": openai_accs,
                "config": self.config_data,
            }
            if password:
                with open(file_path, "wb") as f:
                    f.write(crypto_backup.encrypt_backup(backup_data, password))
            else:
                with open(file_path, "w", encoding="utf-8") as f:
                    json.dump(backup_data, f, indent=2, ensure_ascii=False)
            messagebox.showinfo("Успешно", f"Экспортировано {len(google_accs)} Google и {len(openai_accs)} OpenAI аккаунтов!")
        except Exception as e:
            messagebox.showerror("Ошибка", str(e))

    def import_accounts_action(self):
        file_path = filedialog.askopenfilename(
            title="Импорт",
            filetypes=[("Все файлы бэкапа", "*.agb;*.json"), ("Все файлы", "*.*")],
        )
        if not file_path:
            return

        try:
            with open(file_path, "rb") as f:
                raw = f.read()

            if crypto_backup.is_encrypted_backup(raw):
                pwd_dialog = ctk.CTkInputDialog(title="Ввод пароля", text="Введите пароль от файла:")
                pwd = pwd_dialog.get_input()
                if not pwd:
                    return
                data = crypto_backup.decrypt_backup(raw, pwd)
            else:
                data = json.loads(raw.decode("utf-8"))

            imp_g, imp_o = 0, 0
            g_list = data.get("google_accounts", data.get("accounts", []))
            for g in g_list:
                if isinstance(g, dict) and import_google_account(g):
                    imp_g += 1

            o_list = data.get("openai_accounts", [])
            if o_list:
                imp_o = openai_manager.import_openai_accounts(o_list)

            messagebox.showinfo("Импорт завершен", f"Импортировано:\n• Google: {imp_g}\n• OpenAI: {imp_o}")
            self.refresh_all_async()
        except Exception as e:
            messagebox.showerror("Ошибка импорта", str(e))

    def update_opencode_status(self):
        # Coalesce overlapping requests (startup, refresh, start/stop actions).
        if self._opencode_status_check_running:
            return
        self._opencode_status_check_running = True
        if self._opencode_status_after_id is not None:
            try:
                self.after_cancel(self._opencode_status_after_id)
            except Exception:
                pass
            self._opencode_status_after_id = None

        def _check():
            visible_window = False
            desktop_running = False
            service_running = False
            try:
                if sys.platform.startswith("linux"):
                    desktop_running = any(
                        run_silent_cmd(["pgrep", "-x", process_name], timeout=3).returncode == 0
                        for process_name in ("opencode", "opencode-desktop")
                    )
                    service_res = run_silent_cmd([get_opencode_exe(), "service", "status"], timeout=5)
                    service_running = service_res.returncode == 0 and "127.0.0.1" in service_res.stdout
                else:
                    res = run_silent_cmd(
                        ["tasklist", "/fo", "csv", "/nh", "/fi", "IMAGENAME eq OpenCode.exe"],
                        timeout=3,
                    )
                    desktop_pids = set()
                    for row in (res.stdout or "").splitlines():
                        try:
                            fields = next(csv.reader([row]))
                            if len(fields) >= 2 and fields[0].lower() == "opencode.exe":
                                desktop_running = True
                                desktop_pids.add(int(fields[1]))
                        except (ValueError, csv.Error, StopIteration):
                            continue

                    # A desktop process may remain alive in the tray/background.
                    # Only call the UI open if a visible top-level window belongs to it.
                    if desktop_pids and sys.platform == "win32":
                        import ctypes
                        from ctypes import wintypes

                        enum_windows = ctypes.windll.user32.EnumWindows
                        is_window_visible = ctypes.windll.user32.IsWindowVisible
                        get_window_pid = ctypes.windll.user32.GetWindowThreadProcessId
                        callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

                        def inspect_window(hwnd, _lparam):
                            nonlocal visible_window
                            rect = wintypes.RECT()
                            title_length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
                            if is_window_visible(hwnd) and title_length > 0 and ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                                if rect.right <= rect.left or rect.bottom <= rect.top:
                                    return True
                                pid = wintypes.DWORD()
                                get_window_pid(hwnd, ctypes.byref(pid))
                                if pid.value in desktop_pids:
                                    visible_window = True
                                    return False
                            return True

                        enum_windows(callback_type(inspect_window), 0)

                    cli_res = run_silent_cmd(
                        ["tasklist", "/fo", "csv", "/nh", "/fi", "IMAGENAME eq opencode-cli.exe"],
                        timeout=3,
                    )
                    service_running = any(
                        row.lower().startswith('"opencode-cli.exe"')
                        for row in (cli_res.stdout or "").splitlines()
                    )
            except Exception:
                pass

            def _update():
                self._opencode_status_check_running = False
                try:
                    if visible_window:
                        self.opencode_badge.configure(
                            text="● OpenCode: Окно открыто",
                            text_color="#16a34a",
                            fg_color=("#dcfce7", "#14532d"),
                        )
                    elif service_running:
                        self.opencode_badge.configure(
                            text="◉ OpenCode: Фоновый сервис работает",
                            text_color="#d97706",
                            fg_color=("#fef3c7", "#78350f"),
                        )
                    elif desktop_running:
                        self.opencode_badge.configure(
                            text="◉ OpenCode: Запущен" if sys.platform.startswith("linux") else "◉ OpenCode: Запущен в фоне",
                            text_color="#d97706",
                            fg_color=("#fef3c7", "#78350f"),
                        )
                    else:
                        self.opencode_badge.configure(
                            text="○ OpenCode: Остановлен",
                            text_color=COLOR["text_muted"],
                            fg_color=COLOR["subbox_bg"],
                        )
                    # One recurring poll; explicit refreshes replace its pending timer.
                    self._opencode_status_after_id = self.after(5000, self.update_opencode_status)
                except Exception:
                    pass

            try:
                self.after(0, _update)
            except Exception:
                self._opencode_status_check_running = False

        threading.Thread(target=_check, daemon=True).start()

    def restart_opencode_action(self):
        self.set_status("Перезапуск OpenCode...")

        def _do_restart():
            stop_opencode_processes()
            time.sleep(1)
            cleanup_opencode_locks()
            time.sleep(1)
            exe = get_opencode_exe()
            if os.path.exists(exe):
                launch_env = os.environ.copy()
                dns_active = self.config_data.get("dns_mode") in ("standard", "dot", "doh")
                tunnel_url = "http://127.0.0.1:51180" if dns_active else None
                user_proxy = self.config_data.get("proxy")
                effective_proxy = user_proxy if (user_proxy and user_proxy != "http://127.0.0.1:51180") else tunnel_url

                if effective_proxy:
                    launch_env["HTTPS_PROXY"] = effective_proxy
                    launch_env["HTTP_PROXY"] = effective_proxy
                    launch_env["ALL_PROXY"] = effective_proxy
                    launch_env["https_proxy"] = effective_proxy
                    launch_env["http_proxy"] = effective_proxy
                    launch_env["all_proxy"] = effective_proxy
                    # Exclude Google / Gemini and localhost so Gemini uses direct SmartDNS transport and never connects to 51180
                    no_proxy_rules = "googleapis.com,.googleapis.com,google.com,.google.com,cloudcode-pa.googleapis.com,localhost,127.0.0.1"
                    launch_env["NO_PROXY"] = no_proxy_rules
                    launch_env["no_proxy"] = no_proxy_rules
                else:
                    for var in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy", "NO_PROXY", "no_proxy"):
                        launch_env.pop(var, None)
                subprocess.Popen([exe], cwd=os.path.dirname(exe), env=launch_env)
            time.sleep(2)
            self.after(0, self.update_opencode_status)
            self.after(0, lambda: self.set_status("OpenCode перезапущен!"))

        threading.Thread(target=_do_restart, daemon=True).start()

    def stop_opencode_action(self):
        stop_opencode_processes()
        cleanup_opencode_locks()
        self.update_opencode_status()
        self.set_status("OpenCode остановлен")

    def start_opencode_action(self):
        cleanup_opencode_locks()
        exe = get_opencode_exe()
        if os.path.exists(exe):
            launch_env = os.environ.copy()
            dns_active = self.config_data.get("dns_mode") in ("standard", "dot", "doh")
            tunnel_url = "http://127.0.0.1:51180" if dns_active else None
            user_proxy = self.config_data.get("proxy")
            effective_proxy = user_proxy if (user_proxy and user_proxy != "http://127.0.0.1:51180") else tunnel_url

            if effective_proxy:
                launch_env["HTTPS_PROXY"] = effective_proxy
                launch_env["HTTP_PROXY"] = effective_proxy
                launch_env["ALL_PROXY"] = effective_proxy
                launch_env["https_proxy"] = effective_proxy
                launch_env["http_proxy"] = effective_proxy
                launch_env["all_proxy"] = effective_proxy
                # Exclude Google / Gemini and localhost so Gemini uses direct SmartDNS transport and never connects to 51180
                no_proxy_rules = "googleapis.com,.googleapis.com,google.com,.google.com,cloudcode-pa.googleapis.com,localhost,127.0.0.1"
                launch_env["NO_PROXY"] = no_proxy_rules
                launch_env["no_proxy"] = no_proxy_rules
            else:
                for var in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy", "NO_PROXY", "no_proxy"):
                    launch_env.pop(var, None)
            subprocess.Popen([exe], cwd=os.path.dirname(exe), env=launch_env)
            self.set_status("OpenCode запущен")
        self.after(2000, self.update_opencode_status)


if __name__ == "__main__":
    if not acquire_single_instance():
        sys.exit(0)
    app = AntigravityManagerApp()
    app.mainloop()
