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
import math
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


def _patch_customtkinter_scrollable_frame():
    """
    Rock-solid mouse wheel scrolling patch for CTkScrollableFrame on Windows, Linux, and macOS.
    Determines whether the pointer is over the scrollable canvas using direct geometry checks.
    """
    def _is_mouse_over(self, event):
        try:
            if not self.winfo_ismapped():
                return False
            c = self._parent_canvas
            if not c.winfo_ismapped():
                return False
            x, y = event.x_root, event.y_root
            rx = c.winfo_rootx()
            ry = c.winfo_rooty()
            rw = c.winfo_width()
            rh = c.winfo_height()
            return (rx <= x <= rx + rw) and (ry <= y <= ry + rh)
        except Exception:
            return False

    def _mouse_wheel_all(self, event):
        if not _is_mouse_over(self, event):
            return

        if sys.platform.startswith("win"):
            delta = int(event.delta / 3) if event.delta != 0 else (1 if event.delta > 0 else -1)
            try:
                if getattr(self, "_shift_pressed", False):
                    self._parent_canvas.xview("scroll", -delta, "units")
                else:
                    self._parent_canvas.yview("scroll", -delta, "units")
            except Exception:
                pass
        elif sys.platform == "darwin":
            try:
                delta = int(event.delta)
                if getattr(self, "_shift_pressed", False):
                    self._parent_canvas.xview("scroll", -delta, "units")
                else:
                    self._parent_canvas.yview("scroll", -delta, "units")
            except Exception:
                pass
        else:
            try:
                step = 3
                direction = -step if getattr(event, "num", None) == 4 else step
                self._parent_canvas.yview_scroll(direction, "units")
            except Exception:
                pass

    ctk.CTkScrollableFrame._mouse_wheel_all = _mouse_wheel_all
    ctk.CTkScrollableFrame._check_if_valid_scroll = lambda self, widget: True


_patch_customtkinter_scrollable_frame()

sys.path.insert(0, str(Path(__file__).resolve().parent))
import openai_manager
import win_tray
import health_checker
from google_health_auth import refresh_google_health_account
import auto_updater
import crypto_backup
import dns_tester
import local_proxy
import hub_restart
from openrouter_view import OpenRouterView
from network_view import NetworkView
from xpiki_view import XpikiView
from vless_manager import vless_service, get_http_port, get_active_proxy
from claude_manager import claude_service, CLAUDE_MODELS
import xpiki_manager
import opencode_config

AVAILABLE_PROVIDERS = [
    ("antigravity", "🚀  Antigravity (Google)", "google", "Google Gemini & Claude через Google Cloud Code"),
    ("openai", "🟢  ChatGPT (OpenAI)", "openai", "Аккаунты ChatGPT (OpenAI)"),
    ("claude", "🟠  Claude Code / Pro", "claude", "Подписка Claude Pro / Team без покупки API-токенов"),
    ("xpiki", "🟠  Claude API (Xpiki)", "xpiki", "Шлюз Claude API (Xpiki) по гайду с квотой 100M и Opus 5"),
    ("openrouter", "🟣  OpenRouter Free", "openrouter", "Бесплатные модели OpenRouter"),
]

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


def set_google_account_candidate(target_email_or_id: str, enabled: bool) -> bool:
    """Persists account enable/disable state to commonAuthPool and config so OpenCode respects auto-rotation toggles."""
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
                        if acc.get("id") == target_email_or_id:
                            target_id = acc.get("id")
                            break

                if target_id:
                    rows = cfg.get("commonAuthPool", {}).get("rows", {})
                    if target_id in rows:
                        rows[target_id]["enabled"] = enabled
                        rows[target_id]["usable"] = enabled
                    for acc in cfg.get("accounts", []):
                        if acc.get("id") == target_id:
                            acc["candidate"] = enabled
                            acc["enabled"] = enabled

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
                print(f"Error updating candidate in generation config: {e}")

    legacy_file = config_dir / "antigravity-accounts.json"
    if legacy_file.exists():
        try:
            legacy_data = json.loads(legacy_file.read_text(encoding="utf-8"))
            for acc in legacy_data.get("accounts", []):
                if acc.get("id") == target_email_or_id or acc.get("email") == target_email_or_id:
                    acc["candidate"] = enabled
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
            "candidate": row.get("enabled", True),
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
            acc["candidate"] = disk_acc.get("candidate", True)
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


def import_google_account(account_dict: dict) -> bool:
    nested_metadata = account_dict.get("metadata") if isinstance(account_dict.get("metadata"), dict) else {}
    email = account_dict.get("email") or nested_metadata.get("email")
    refresh_token = account_dict.get("refreshToken") or account_dict.get("refresh") or nested_metadata.get("refreshToken") or nested_metadata.get("refresh")
    project_id = account_dict.get("projectId") or nested_metadata.get("projectId") or "aicode-consumers"
    added_at = account_dict.get("addedAt") or nested_metadata.get("addedAt")
    if not isinstance(added_at, (int, float)) or isinstance(added_at, bool) or not math.isfinite(added_at) or added_at <= 0:
        added_at = int(time.time() * 1000)
    label = account_dict.get("label") or nested_metadata.get("label") or (email.split("@")[0] if email else "Google Account")

    if not email or not refresh_token:
        return False

    config_dir = Path(os.path.expanduser("~/.config/opencode"))
    repair_error = repair_legacy_google_account_file(config_dir)
    if repair_error:
        print(repair_error)
        return False
    gen_dirs = list(config_dir.glob("*.generation"))

    if gen_dirs:
        # Generation stores are transactionally managed by the plugin. Editing
        # their config/state files directly can target an inactive generation
        # and falsely report success; the plugin exposes no token-import CLI.
        print("Import into an initialized Antigravity generation store is unsupported; sign in to each Google account in the browser instead.")
        return False
    else:
        legacy_file = config_dir / "antigravity-accounts.json"
        legacy_data = {"version": 4, "activeIndex": 0, "accounts": []}
        if legacy_file.exists():
            try:
                legacy_data = json.loads(legacy_file.read_text(encoding="utf-8"))
            except Exception as exc:
                print(f"Cannot read existing Google account file: {exc}")
                return False
        if not isinstance(legacy_data, dict) or not isinstance(legacy_data.get("accounts"), list):
            print("Existing Google account file has an unsupported shape; leaving it untouched")
            return False
        old_accs = legacy_data["accounts"]
        changed = False
        for index, old_account in enumerate(old_accs):
            if not isinstance(old_account, dict) or not isinstance(old_account.get("refreshToken"), str) or not old_account["refreshToken"]:
                print(f"Existing Google account entry {index} is invalid; leaving the file untouched")
                return False
            # V4 account storage requires finite numeric timestamps. Older Hub
            # exports omitted lastUsed, which made migration fail after import.
            if not isinstance(old_account.get("addedAt"), (int, float)) or isinstance(old_account.get("addedAt"), bool) or not math.isfinite(old_account["addedAt"]):
                print(f"Existing Google account entry {index} has invalid addedAt; leaving the file untouched")
                return False
            last_used = old_account.get("lastUsed")
            if not isinstance(last_used, (int, float)) or isinstance(last_used, bool) or not math.isfinite(last_used):
                old_account["lastUsed"] = 0
                changed = True
        found = False
        for a in old_accs:
            if a.get("email") == email:
                a["refreshToken"] = refresh_token
                a.setdefault("addedAt", added_at)
                a.setdefault("lastUsed", 0)
                found = True
                changed = True
                break
        if not found:
            imported_last_used = account_dict.get("lastUsed", 0)
            if not isinstance(imported_last_used, (int, float)) or isinstance(imported_last_used, bool) or not math.isfinite(imported_last_used):
                imported_last_used = 0
            old_accs.append({
                "email": email,
                "refreshToken": refresh_token,
                "projectId": project_id,
                "addedAt": added_at,
                "lastUsed": imported_last_used,
            })
            changed = True
        legacy_data["accounts"] = old_accs
        if legacy_file.exists() and changed:
            backup_file = legacy_file.with_name(legacy_file.name + ".pre-import-" + datetime.datetime.now().strftime("%Y%m%d-%H%M%S-%f") + ".bak")
            shutil.copy2(legacy_file, backup_file)
        legacy_file.write_text(json.dumps(legacy_data, indent=2, ensure_ascii=False), encoding="utf-8")
        migration = run_silent_cmd([NODE_EXE, CLI_JS, "migrate", "--offline", "--yes"], timeout=30)
        if migration.returncode != 0:
            print(f"Google account migration failed: {(migration.stderr or migration.stdout or '')[:1000]}")
            return False

    return True


# =========================================================================
# CONCEPT 3: AMBER GRAPHITE GLASS PALETTE (Light, Dark)
# Dark graphite surfaces, warm amber highlights, and restrained status colors.
# =========================================================================
COLOR = {
    "bg": ("#f2f5f9", "#0b1014"),
    "sidebar_bg": ("#f8faff", "#0d1216"),
    "card_bg": ("#ffffff", "#141b20"),
    "card_active_bg": ("#fff8ed", "#1d211f"),
    "subbox_bg": ("#f4f7fa", "#10171b"),
    "border": ("#d6e0e8", "#2b353a"),
    "border_active": ("#d18b35", "#d99a43"),
    "text_primary": ("#17212b", "#f2f3f3"),
    "text_secondary": ("#536575", "#b6bec2"),
    "text_muted": ("#788897", "#879398"),
    "bar_bg": ("#e5edf2", "#293238"),
    "statusbar_bg": ("#f8faff", "#0d1216"),
    "nav_active_bg": ("#fff0d8", "#322719"),
    "nav_active_text": ("#a96513", "#f0b257"),
    "nav_idle_text": ("#536575", "#a1aaad"),
    "accent_cyan": "#f0ad4e",
    "accent_emerald": "#42d6a0",
    "accent_purple": "#a99aff",
    "accent_amber": "#f3ad55",
    "glass_highlight": ("#ffffff", "#25231f"),
    "quota_5h": ("#168b70", "#36c99b"),
    "quota_5h_bg": ("#dff5ec", "#12392f"),
    "quota_weekly": ("#a66b16", "#f0a944"),
    "quota_weekly_bg": ("#fff2da", "#3b2b1a"),
}


def apply_windows_acrylic_effect(window):
    """Apply Windows 11 Mica backdrop and coordinate titlebar colors with the glass theme."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        hwnd = ctypes.windll.user32.GetParent(window.winfo_id())
        if not hwnd:
            hwnd = window.winfo_id()

        # DWMWA_USE_IMMERSIVE_DARK_MODE = 20
        dark_mode = ctypes.c_int(1)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            hwnd, 20, ctypes.byref(dark_mode), ctypes.sizeof(dark_mode)
        )

        # DWMWA_SYSTEMBACKDROP_TYPE = 38; value 2 is Mica for a main window.
        # Unsupported Windows versions simply ignore this optional material.
        backdrop_type = ctypes.c_int(2)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            hwnd, 38, ctypes.byref(backdrop_type), ctypes.sizeof(backdrop_type)
        )

        # DWMWA_CAPTION_COLOR = 35 (titlebar: #0b1014, BGR 0x0014100b)
        caption_col = ctypes.c_int(0x0014100b)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            hwnd, 35, ctypes.byref(caption_col), ctypes.sizeof(caption_col)
        )

        # DWMWA_TEXT_COLOR = 36 (Titlebar text: crisp silver BGR 0x00ffffff)
        text_col = ctypes.c_int(0x00ffffff)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            hwnd, 36, ctypes.byref(text_col), ctypes.sizeof(text_col)
        )

        # DWMWA_BORDER_COLOR = 34 (graphite hairline #2b353a: BGR 0x003a352b)
        border_col = ctypes.c_int(0x003a352b)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            hwnd, 34, ctypes.byref(border_col), ctypes.sizeof(border_col)
        )
    except Exception:
        pass


def create_cyber_switch(master, text="", variable=None, command=None, font=None, **kwargs):
    """Creates a sleek Linear-style switch."""
    return ctk.CTkSwitch(
        master,
        text=text,
        variable=variable,
        command=command,
        font=font,
        width=44,
        height=22,
        switch_width=36,
        switch_height=18,
        corner_radius=9,
        border_width=1,
        fg_color=("#d0d7de", "#21262d"),
        progress_color=("#1f883d", "#238636"),
        button_color=("#ffffff", "#ffffff"),
        button_hover_color=("#f6f8fa", "#f0f6fc"),
        border_color=("#afb8c1", "#30363d"),
        text_color=COLOR["text_primary"],
        **kwargs
    )


class AntigravityManagerApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("Antigravity Hub — Google, ChatGPT & Claude")
        self.geometry("1440x900")
        self.minsize(1180, 760)

        # Load config first to read theme
        self.config_data = self.load_config()
        self.current_theme = self.config_data.get("theme_mode", "dark")

        # Apply CustomTkinter appearance mode directly
        self.appearance_mode = "Dark" if self.current_theme == "dark" else "Light"
        ctk.set_appearance_mode(self.appearance_mode)
        ctk.set_default_color_theme("blue")
        self.configure(fg_color=COLOR["bg"])

        icon_file = Path(__file__).resolve().parent / "icon.ico"
        if icon_file.exists():
            try:
                self.iconbitmap(str(icon_file))
                self.iconbitmap(default=str(icon_file))
            except Exception:
                print("Could not set Antigravity Hub window icon")

        # Windows 11 / 10 DWM Acrylic / Mica Backdrop Effect
        self.after(50, lambda: apply_windows_acrylic_effect(self))

        # State
        self.accounts_data = []
        self.openai_accounts_data = []
        self.claude_accounts_data = []
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

        # Автоматическая проверка и фиксация модели именования сессий (opencode/big-pickle)
        try:
            opencode_config.ensure_session_title_config()
        except Exception as e:
            print(f"[Hub] Ошибка проверки настройки подписи сессий: {e}")

    # --- Font Helper (Crisp Segoe UI) ---
    def font(self, size=12, weight="normal", underline=False):
        return ctk.CTkFont(family="Segoe UI", size=size, weight=weight, underline=underline)

    # --- Configuration Management ---
    def load_config(self):
        if CONFIG_FILE.exists():
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    cfg = {**DEFAULT_CONFIG, **data}
                    if cfg.get("max_rate_limit_wait_seconds", 300) < 300:
                        cfg["max_rate_limit_wait_seconds"] = 300
                    return cfg
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
        try:
            icon_file = Path(__file__).resolve().parent / "icon.ico"
            icon_str = str(icon_file) if icon_file.exists() else None
            self.tray = win_tray.WindowsTrayIcon(
                title="Antigravity Hub — Google, ChatGPT & OpenRouter Free",
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
        try:
            vless_service.stop_tunnel()
        except Exception:
            pass
        self.destroy()

    # --- Auto-Updater ---
    def manual_check_updates_action(self):
        self.btn_check_update.configure(state="disabled", text="⏳ Проверка...")
        self.set_status("Проверка обновлений на GitHub (ветка V2)...")

        def _do_manual_check():
            repo_dir = Path(__file__).resolve().parent.parent
            info = auto_updater.check_for_updates(repo_dir)
            self.after(0, lambda: self._on_manual_updates_checked(info))

        threading.Thread(target=_do_manual_check, daemon=True).start()

    def _on_manual_updates_checked(self, info):
        self.btn_check_update.configure(state="normal", text="🔄 Проверить обновления")
        has_update = info.get("has_update", False)
        local_sha = info.get("local_sha", "HEAD")
        err = info.get("error")

        if err:
            messagebox.showwarning("Проверка обновлений", f"Не удалось проверить обновления:\n{err}")
            self.set_status(f"Ошибка проверки: {err}")
        elif has_update:
            self.update_info = info
            self.show_update_banner(info)
            self.set_status("Доступна новая версия Antigravity Hub")
        else:
            messagebox.showinfo(
                "Обновления не требуются",
                f"У вас установлена самая актуальная версия Antigravity Hub!\n\n"
                f"• Ветка: V2\n"
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
            fg_color=("#0969da", "#c88635"),
            hover_color=("#0550ae", "#e09a43"),
            corner_radius=6,
            height=28,
            command=self.apply_update_action,
        ).pack(side="left", padx=(0, 6))

        ctk.CTkButton(
            btn_box,
            text="✕",
            font=self.font(size=12),
            fg_color="transparent",
            hover_color=("#eaeef2", "#21262d"),
            text_color=COLOR["text_muted"],
            corner_radius=6,
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
        self.set_status("Применение обновления с GitHub (ветка V2)...")

        def _do_update():
            ok, msg = auto_updater.apply_update_git(repo_dir)
            self.after(0, lambda: self._on_update_applied(ok, msg))

        threading.Thread(target=_do_update, daemon=True).start()

    def _on_update_applied(self, ok, msg):
        if ok:
            self.dismiss_update_banner()
            self.update_banner = ctk.CTkFrame(self.content_area, corner_radius=10)
            self.update_banner.pack(fill="x", padx=24, pady=(12, 0))
            ctk.CTkLabel(
                self.update_banner, text="Обновление установлено. Перезапустите Hub, чтобы применить изменения.",
                wraplength=520, justify="left",
            ).pack(side="left", padx=16, pady=12)
            ctk.CTkButton(
                self.update_banner, text="Перезапустить Hub", command=self.restart_hub_action,
            ).pack(side="right", padx=16, pady=12)
            self.set_status(msg)
        else:
            messagebox.showerror("Ошибка обновления", msg)

    def restart_hub_action(self):
        try:
            hub_restart.schedule_restart()
        except OSError as error:
            messagebox.showerror("Перезапуск Hub", f"Не удалось запустить Hub заново:\n{error}")
            return
        self.exit_app_fully()

    # =========================================================================
    # SIDEBAR COMPONENT (Cockpit Tools Style)
    # =========================================================================
    def create_sidebar(self):
        self.sidebar = ctk.CTkFrame(
            self,
            width=296,
            corner_radius=0,
            fg_color=COLOR["sidebar_bg"],
            border_width=1,
            border_color=COLOR["border"],
        )
        self.sidebar.grid(row=0, column=0, sticky="nsew")
        self.sidebar.grid_propagate(False)
        self.sidebar.grid_rowconfigure(8, weight=1)

        # Brand / Logo Header
        logo_box = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        logo_box.grid(row=0, column=0, padx=18, pady=(20, 20), sticky="w")

        icon_badge = ctk.CTkLabel(
            logo_box,
            text="✨",
            font=self.font(size=17, weight="bold"),
            fg_color=("#eaeef2", "#21262d"),
            text_color=COLOR["accent_cyan"],
            width=32,
            height=32,
            corner_radius=8,
        )
        icon_badge.pack(side="left", padx=(0, 10))

        title_lbl = ctk.CTkLabel(
            logo_box,
            text="Antigravity Hub",
            font=self.font(size=15, weight="bold"),
            text_color=COLOR["text_primary"],
        )
        title_lbl.pack(side="left")

        # Nav Buttons Container
        self.nav_btns = {}
        self.nav_frame = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        self.nav_frame.grid(row=1, column=0, sticky="nsew", padx=0, pady=0)
        self.sidebar.grid_rowconfigure(2, weight=1)

        self.rebuild_sidebar_nav()

        # Sidebar Footer: Theme Toggle + OpenCode status
        footer_box = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        footer_box.grid(row=3, column=0, padx=12, pady=14, sticky="ew")

        # Theme toggle button
        theme_txt = "☀️  Светлая тема" if self.current_theme == "dark" else "🌙  Тёмная тема"
        self.btn_theme_toggle = ctk.CTkButton(
            footer_box,
            text=theme_txt,
            font=self.font(size=11, weight="bold"),
            fg_color=COLOR["card_bg"],
            hover_color=("#eaeef2", "#21262d"),
            text_color=COLOR["text_secondary"],
            border_width=1,
            border_color=COLOR["border"],
            height=32,
            corner_radius=8,
            command=self.toggle_theme,
        )
        self.btn_theme_toggle.pack(fill="x", pady=(0, 8))

        self.opencode_badge = ctk.CTkLabel(
            footer_box,
            text="● OpenCode: Проверка...",
            font=self.font(size=11),
            fg_color=COLOR["card_bg"],
            text_color=COLOR["text_secondary"],
            border_width=1,
            border_color=COLOR["border"],
            corner_radius=8,
            height=28,
            wraplength=230,
            justify="center",
        )
        self.opencode_badge.pack(fill="x", pady=(0, 8))

        ctk.CTkButton(
            footer_box,
            text="🔄 Перезапуск OpenCode",
            font=self.font(size=11, weight="bold"),
            fg_color=("#f6f8fa", "#21262d"),
            hover_color=("#eaeef2", "#30363d"),
            text_color=COLOR["text_primary"],
            border_width=1,
            border_color=COLOR["border"],
            height=32,
            corner_radius=8,
            command=self.restart_opencode_action,
        ).pack(fill="x")

    def rebuild_sidebar_nav(self):
        for btn in self.nav_btns.values():
            btn.destroy()
        self.nav_btns.clear()

        vis = self.config_data.get("providers_visibility", {})
        nav_items = []
        for key, label, _, _ in AVAILABLE_PROVIDERS:
            is_vis = vis.get(key, (key != "deepseek"))
            if is_vis:
                nav_items.append((key, label))

        # Core non-provider tools
        nav_items.append(("network", "🌐  Сеть, DNS & VLESS"))
        nav_items.append(("settings", "⚙️  Настройки"))
        nav_items.append(("system", "🛠  Диагностика OpenCode"))

        for key, label in nav_items:
            is_active = (key == self.current_nav)
            btn = ctk.CTkButton(
                self.nav_frame,
                text=label,
                font=self.font(size=13, weight="bold"),
                anchor="w",
                height=42,
                corner_radius=10,
                border_width=1 if is_active else 0,
                border_color=COLOR["border_active"],
                fg_color=COLOR["nav_active_bg"] if is_active else "transparent",
                text_color=COLOR["nav_active_text"] if is_active else COLOR["nav_idle_text"],
                hover_color=("#edf4f7", "#1a303e"),
                command=lambda k=key: self.switch_nav(k),
            )
            btn.pack(fill="x", padx=10, pady=2)
            self.nav_btns[key] = btn

        if self.current_nav not in self.nav_btns:
            first_key = nav_items[0][0] if nav_items else "settings"
            self.switch_nav(first_key)

    def switch_nav(self, target_nav):
        self.current_nav = target_nav
        self.openrouter_view.pack_forget()
        if hasattr(self, "network_view"):
            self.network_view.pack_forget()
        if hasattr(self, "xpiki_view"):
            self.xpiki_view.pack_forget()
        for key, btn in self.nav_btns.items():
            if key == target_nav:
                btn.configure(
                    fg_color=COLOR["nav_active_bg"],
                    text_color=COLOR["nav_active_text"],
                    border_width=1,
                    border_color=COLOR["border"]
                )
            else:
                btn.configure(
                    fg_color="transparent",
                    text_color=COLOR["nav_idle_text"],
                    border_width=0
                )

        # Toggle views
        if target_nav in ("antigravity", "openai", "claude"):
            if target_nav == "antigravity":
                self.current_provider_view = "google"
            elif target_nav == "openai":
                self.current_provider_view = "openai"
            else:
                self.current_provider_view = "claude"
            if target_nav == "antigravity":
                self.google_page_header.pack(fill="x", padx=28, pady=(18, 0), before=self.top_action_bar)
            else:
                self.google_page_header.pack_forget()
            self.top_action_bar.pack(fill="x", padx=28, pady=(12, 0))
            self.accounts_container.pack(fill="both", expand=True, padx=24, pady=(12, 16))
            self.settings_frame.pack_forget()
            self.system_frame.pack_forget()
            self.update_action_bar_for_provider()
            self.render_accounts()
        elif target_nav == "xpiki":
            self.google_page_header.pack_forget()
            self.top_action_bar.pack_forget()
            self.accounts_container.pack_forget()
            self.settings_frame.pack_forget()
            self.system_frame.pack_forget()
            self.xpiki_view.pack(fill="both", expand=True, padx=24, pady=16)
        elif target_nav == "openrouter":
            self.google_page_header.pack_forget()
            self.top_action_bar.pack_forget()
            self.accounts_container.pack_forget()
            self.settings_frame.pack_forget()
            self.system_frame.pack_forget()
            self.openrouter_view.pack(fill="both", expand=True, padx=24, pady=16)
        elif target_nav == "network":
            self.google_page_header.pack_forget()
            self.top_action_bar.pack_forget()
            self.accounts_container.pack_forget()
            self.settings_frame.pack_forget()
            self.system_frame.pack_forget()
            self.network_view.pack(fill="both", expand=True, padx=24, pady=16)
            if hasattr(self.network_view, "update_core_status"):
                self.network_view.update_core_status()
            if hasattr(self.network_view, "update_vless_status"):
                self.network_view.update_vless_status()
        elif target_nav == "settings":
            self.google_page_header.pack_forget()
            self.top_action_bar.pack_forget()
            self.accounts_container.pack_forget()
            self.system_frame.pack_forget()
            self.settings_frame.pack(fill="both", expand=True, padx=24, pady=16)
        elif target_nav == "system":
            self.google_page_header.pack_forget()
            self.top_action_bar.pack_forget()
            self.accounts_container.pack_forget()
            self.settings_frame.pack_forget()
            self.system_frame.pack_forget()
            self.system_frame.pack(fill="both", expand=True, padx=24, pady=16)
            if hasattr(self, "update_session_title_status"):
                self.update_session_title_status()

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
        self.google_page_header = ctk.CTkFrame(self.content_area, fg_color="transparent")
        self.google_page_header.grid_columnconfigure(0, weight=1)
        self.google_page_title = ctk.CTkLabel(
            self.google_page_header,
            text="Google Antigravity",
            font=self.font(size=25, weight="bold"),
            text_color=COLOR["text_primary"],
        )
        self.google_page_title.grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(
            self.google_page_header,
            text="Управление аккаунтами Google",
            font=self.font(size=13),
            text_color=COLOR["text_secondary"],
        ).grid(row=1, column=0, sticky="w", pady=(2, 0))
        self.google_accounts_status = ctk.CTkLabel(
            self.google_page_header,
            text="● Подключено",
            font=self.font(size=12, weight="bold"),
            fg_color=COLOR["quota_5h_bg"],
            text_color=COLOR["accent_emerald"],
            corner_radius=12,
            padx=13,
            pady=7,
        )
        self.google_accounts_status.grid(row=0, column=1, rowspan=2, sticky="e", padx=(12, 0))
        self.google_page_header.pack(fill="x", padx=28, pady=(18, 0), before=self.top_action_bar)
        self.create_flash_banner()

        self.accounts_container = ctk.CTkScrollableFrame(
            self.content_area,
            fg_color=COLOR["bg"],
            corner_radius=0,
        )
        self.accounts_container.pack(fill="both", expand=True, padx=24, pady=(12, 16))

        self.create_settings_view()
        self.create_system_view()
        self.openrouter_view = OpenRouterView(self.content_area, self, COLOR)
        self.xpiki_view = XpikiView(self.content_area, self, COLOR)
        self.network_view = NetworkView(self.content_area, self, COLOR)
        self.create_statusbar()

    def create_action_bar(self):
        self.top_action_bar = ctk.CTkFrame(self.content_area, fg_color="transparent")
        self.top_action_bar.pack(fill="x", padx=24, pady=(16, 0))

        # Search input
        self.search_entry = ctk.CTkEntry(
            self.top_action_bar,
            placeholder_text="🔍  Поиск аккаунта по email...",
            font=self.font(size=12),
            width=230,
            height=34,
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
            text_color=COLOR["accent_cyan"],
            corner_radius=8,
            border_width=1,
            border_color=COLOR["border"],
            padx=12,
            height=34,
        )
        self.lbl_count_pill.pack(side="left", padx=(0, 10))

        # Action buttons
        self.actions_right_frame = ctk.CTkFrame(self.top_action_bar, fg_color="transparent")
        self.actions_right_frame.pack(side="right")

        self.btn_import = ctk.CTkButton(
            self.actions_right_frame,
            text="📥",
            font=self.font(size=13, weight="bold"),
            fg_color=COLOR["card_bg"],
            hover_color=COLOR["subbox_bg"],
            text_color=COLOR["text_primary"],
            border_width=1,
            border_color=COLOR["border"],
            height=34,
            width=36,
            corner_radius=8,
            command=self.import_accounts_action,
        )
        self.btn_import.pack(side="left", padx=3)

        self.btn_export = ctk.CTkButton(
            self.actions_right_frame,
            text="📤",
            font=self.font(size=13, weight="bold"),
            fg_color=COLOR["card_bg"],
            hover_color=COLOR["subbox_bg"],
            text_color=COLOR["text_primary"],
            border_width=1,
            border_color=COLOR["border"],
            height=34,
            width=36,
            corner_radius=8,
            command=self.export_accounts_action,
        )
        self.btn_export.pack(side="left", padx=3)

        self.btn_refresh = ctk.CTkButton(
            self.actions_right_frame,
            text="🔄 Квоты",
            font=self.font(size=11, weight="bold"),
            fg_color=COLOR["card_bg"],
            hover_color=COLOR["subbox_bg"],
            text_color=COLOR["text_primary"],
            border_width=1,
            border_color=COLOR["border"],
            height=34,
            width=90,
            corner_radius=8,
            command=self.refresh_all_async,
        )
        self.btn_refresh.pack(side="left", padx=3)

        self.btn_google_models = ctk.CTkButton(
            self.actions_right_frame,
            text="📋 Модели",
            font=self.font(size=11, weight="bold"),
            fg_color=COLOR["card_bg"],
            hover_color=COLOR["subbox_bg"],
            text_color=COLOR["text_primary"],
            border_width=1,
            border_color=COLOR["border"],
            height=34,
            width=90,
            corner_radius=8,
            command=self.show_google_models_action,
        )
        self.btn_google_models.pack(side="left", padx=3)

        self.btn_add_account = ctk.CTkButton(
            self.actions_right_frame,
            text="＋ Добавить аккаунт",
            font=self.font(size=12, weight="bold"),
            fg_color="#a96e2c",
            hover_color="#c88635",
            text_color="#ffffff",
            height=40,
            width=150,
            corner_radius=12,
            command=self.add_account_action,
        )
        self.btn_add_account.pack(side="left", padx=(3, 0))

    def update_action_bar_for_provider(self):
        if self.current_provider_view == "google":
            self.btn_google_models.pack(side="left", padx=3, before=self.btn_add_account)
            self.btn_add_account.configure(
                text="＋ Добавить аккаунт",
                command=self.add_account_action,
                fg_color="#a96e2c",
                hover_color="#c88635",
            )
        elif self.current_provider_view == "openai":
            self.btn_google_models.pack_forget()
            self.btn_add_account.configure(
                text="＋ Добавить OpenAI",
                command=self.add_openai_account_action,
                fg_color="#a96e2c",
                hover_color="#c88635",
            )
        elif self.current_provider_view == "claude":
            self.btn_google_models.pack_forget()
            self.btn_add_account.configure(
                text="➕ Добавить Claude",
                command=self.add_claude_account_action,
                fg_color="#a96e2c",
                hover_color="#c88635",
            )

    def show_google_models_action(self):
        """Show models currently registered for the Google provider in OpenCode."""
        if getattr(self, "google_models_loading", False):
            return
        self.google_models_loading = True
        self.btn_google_models.configure(state="disabled", text="⏳ Загружаю...")

        def _load():
            try:
                exe = get_opencode_cli()
                if not exe:
                    raise RuntimeError("Не найден CLI OpenCode (opencode-cli.exe).")
                result = run_silent_cmd([exe, "models", "--standalone"], timeout=45, env=provider_route_environment())
                if result.returncode != 0:
                    result = run_silent_cmd([exe, "models"], timeout=45, env=provider_route_environment())
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

    def test_google_generation_action(self):
        if getattr(self, "google_generation_testing", False):
            return
        self.google_generation_testing = True
        self.set_status("Тест Gemini 3.8: обновление токена и запрос генерации...")

        def worker():
            try:
                import google_health_auth
                account = get_active_google_health_account()
                if not account:
                    raise ValueError("Нет активного аккаунта")
                account = google_health_auth.refresh_google_health_account(
                    account, run_google_route_cmd, get_node_executable(), get_cli_js())
                result = health_checker.test_antigravity_model(account, "antigravity-gemini-3.8-flash")
                report = health_checker.format_model_probe_result(result)
            except Exception:
                report = "Не удалось подготовить тест. Проверьте активный Google-аккаунт, авторизацию и сеть."

            def done():
                self.google_generation_testing = False
                self.set_status("Тест Gemini 3.8 завершён")
                messagebox.showinfo("Генерация Gemini 3.8", report, parent=self)

            self.after(0, done)

        threading.Thread(target=worker, daemon=True).start()

    def _show_google_models_result(self, output, error):
        self.google_models_loading = False
        self.btn_google_models.configure(state="normal", text="📋 Модели")
        if error:
            messagebox.showerror("Модели Antigravity в OpenCode", error, parent=self)
            return

        deprecated_versions = ("3.7", "3.6", "3.5", "3.1")
        model_lines = [
            line.strip() for line in output.splitlines()
            if line.strip() and not any(v in line for v in deprecated_versions)
        ]

        dialog = ctk.CTkToplevel(self)
        dialog.title("Модели Antigravity, доступные в OpenCode")
        dialog.geometry("740x600")
        dialog.minsize(640, 480)
        dialog.transient(self)
        dialog.grab_set()

        # Header Frame
        header = ctk.CTkFrame(dialog, fg_color="transparent")
        header.pack(fill="x", padx=18, pady=(16, 8))

        ctk.CTkLabel(
            header,
            text="📋 Модели Antigravity в OpenCode",
            font=self.font(size=16, weight="bold"),
            text_color=COLOR["text_primary"]
        ).pack(anchor="w")

        # Find active account
        active_idx = get_active_google_account_index()
        active_acc = None
        if self.accounts_data:
            for a in self.accounts_data:
                if a.get("index", 1) - 1 == active_idx:
                    active_acc = a
                    break
            if not active_acc:
                active_acc = self.accounts_data[0]
        if not active_acc:
            accs = export_google_accounts()
            if accs:
                active_acc = accs[0]

        acc_email = active_acc.get("email", "Не выбран") if active_acc else "Не найден"

        ctk.CTkLabel(
            header,
            text=f"Аккаунт для тестирования: {acc_email} | Проверка выполняет реальный пробный запрос через API",
            font=self.font(size=11),
            text_color=COLOR["text_secondary"]
        ).pack(anchor="w", pady=(2, 8))

        top_bar = ctk.CTkFrame(header, fg_color="transparent")
        top_bar.pack(fill="x", pady=(4, 0))

        btn_check_all = ctk.CTkButton(
            top_bar,
            text="🩺 Проверить доступность всех моделей",
            font=self.font(size=12, weight="bold"),
            fg_color=("#0969da", "#c88635"),
            hover_color=("#0550ae", "#e09a43"),
            height=34,
            corner_radius=6
        )
        btn_check_all.pack(side="left")

        lbl_check_status = ctk.CTkLabel(
            top_bar,
            text="Нажмите кнопку, чтобы проверить доступность моделей",
            font=self.font(size=11),
            text_color=COLOR["text_muted"]
        )
        lbl_check_status.pack(side="left", padx=14)

        # Scrollable models frame
        scroll_frame = ctk.CTkScrollableFrame(dialog, fg_color=COLOR["bg"], corner_radius=10)
        scroll_frame.pack(fill="both", expand=True, padx=18, pady=8)

        model_badges = {}
        model_test_btns = {}

        def get_auth_account():
            target_acc = active_acc
            if not target_acc:
                accs = export_google_accounts()
                if accs:
                    target_acc = accs[0]
            if not target_acc:
                return None
            try:
                import google_health_auth
                node_exe = get_node_executable()
                cli_js = get_cli_js()
                refreshed = google_health_auth.refresh_google_health_account(
                    target_acc, run_google_route_cmd, node_exe, cli_js
                )
                return refreshed
            except Exception:
                return target_acc

        def apply_result(m_id, res):
            badge = model_badges.get(m_id)
            btn = model_test_btns.get(m_id)
            if btn:
                btn.configure(state="normal", text="🩺 Тест")
            if not badge:
                return
            status = res.get("status", "")
            badge_text = res.get("badge", "Готово")

            if res.get("ok"):
                fg = ("#dcfce7", "#14532d")
                txt_col = "#16a34a"
            elif status == "rate_limited":
                fg = ("#fef3c7", "#78350f")
                txt_col = "#d97706"
            else:
                fg = ("#fee2e2", "#7f1d1d")
                txt_col = "#ef4444"

            badge.configure(text=badge_text, text_color=txt_col, fg_color=fg)

        def check_single_model(m_id):
            badge = model_badges.get(m_id)
            btn = model_test_btns.get(m_id)
            if badge:
                badge.configure(text="⏳ Проверка...", fg_color=COLOR["subbox_bg"], text_color=COLOR["accent_cyan"])
            if btn:
                btn.configure(state="disabled", text="⏳...")

            def _worker():
                acc = get_auth_account()
                if not acc:
                    res = {"ok": False, "status": "no_auth", "badge": "🔴 Нет аккаунта", "color": "#ef4444"}
                else:
                    res = health_checker.test_antigravity_model(acc, m_id, timeout=30)
                def done():
                    if not dialog.winfo_exists():
                        return
                    apply_result(m_id, res)
                    messagebox.showinfo("Результат генерации", health_checker.format_model_probe_result(res), parent=dialog)
                dialog.after(0, done)

            threading.Thread(target=_worker, daemon=True).start()

        def check_all_models():
            btn_check_all.configure(state="disabled", text="⏳ Проверка моделей...")
            lbl_check_status.configure(text="Выполняется тестирование моделей через Google CloudCode API...")
            for b in model_badges.values():
                b.configure(text="⏳ Ожидание...", fg_color=COLOR["subbox_bg"], text_color=COLOR["text_muted"])
            for btn in model_test_btns.values():
                btn.configure(state="disabled")

            def _worker_all():
                acc = get_auth_account()
                if not acc:
                    dialog.after(0, lambda: lbl_check_status.configure(text="❌ Ошибка: нет авторизованного аккаунта Google"))
                    dialog.after(0, lambda: btn_check_all.configure(state="normal", text="🩺 Проверить доступность всех моделей"))
                    return

                import concurrent.futures
                results_summary = {"ok": 0, "rate_limit": 0, "error": 0}

                with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
                    futures = {
                        executor.submit(health_checker.test_antigravity_model, acc, m, 30): m
                        for m in model_lines
                    }
                    for future in concurrent.futures.as_completed(futures):
                        m = futures[future]
                        try:
                            res = future.result()
                        except Exception as e:
                            res = {"ok": False, "status": "error", "badge": f"🔴 Ошибка", "color": "#ef4444"}
                        if res.get("ok"):
                            results_summary["ok"] += 1
                        elif res.get("status") == "rate_limited":
                            results_summary["rate_limit"] += 1
                        else:
                            results_summary["error"] += 1
                        dialog.after(0, lambda mid=m, r=res: apply_result(mid, r))

                def _finish():
                    btn_check_all.configure(state="normal", text="🔄 Проверить все заново")
                    lbl_check_status.configure(
                        text=f"Тест завершён: 🟢 Работают: {results_summary['ok']} | 🟡 Лимит 429: {results_summary['rate_limit']} | 🔴 Ошибка: {results_summary['error']}"
                    )
                    for btn in model_test_btns.values():
                        btn.configure(state="normal", text="🩺 Тест")

                dialog.after(0, _finish)

            threading.Thread(target=_worker_all, daemon=True).start()

        btn_check_all.configure(command=check_all_models)

        for m_id in model_lines:
            row_frame = ctk.CTkFrame(
                scroll_frame,
                fg_color=COLOR["card_bg"],
                corner_radius=10,
                border_width=1,
                border_color=COLOR["border"]
            )
            row_frame.pack(fill="x", padx=4, pady=4)
            row_frame.grid_columnconfigure(1, weight=1)

            # Determine icon and display name
            low_id = m_id.lower()
            if "claude" in low_id:
                icon = "🧠"
            elif "gpt-oss" in low_id:
                icon = "🤖"
            elif "image" in low_id:
                icon = "🎨"
            else:
                icon = "✨"

            clean_id = m_id.replace("google/", "")
            mapping = health_checker.ANTIGRAVITY_MODEL_INTERNAL_MAP.get(clean_id)
            if mapping:
                display_name = mapping[0]
            else:
                display_name = clean_id.replace("antigravity-", "").replace("-", " ").title()

            icon_lbl = ctk.CTkLabel(row_frame, text=icon, font=self.font(size=18))
            icon_lbl.grid(row=0, column=0, rowspan=2, padx=(12, 10), pady=8)

            title_lbl = ctk.CTkLabel(
                row_frame,
                text=display_name,
                font=self.font(size=13, weight="bold"),
                text_color=COLOR["text_primary"]
            )
            title_lbl.grid(row=0, column=1, sticky="w", pady=(8, 0))

            id_lbl = ctk.CTkLabel(
                row_frame,
                text=m_id,
                font=self.font(size=11),
                text_color=COLOR["text_muted"]
            )
            id_lbl.grid(row=1, column=1, sticky="w", pady=(0, 8))

            badge = ctk.CTkLabel(
                row_frame,
                text="⚪ Не проверена",
                font=self.font(size=11, weight="bold"),
                fg_color=COLOR["subbox_bg"],
                text_color=COLOR["text_muted"],
                corner_radius=6,
                padx=10,
                pady=4
            )
            badge.grid(row=0, column=2, rowspan=2, padx=8, pady=8)
            model_badges[m_id] = badge

            btn_test = ctk.CTkButton(
                row_frame,
                text="🩺 Тест",
                font=self.font(size=11, weight="bold"),
                fg_color=COLOR["subbox_bg"],
                hover_color=COLOR["border"],
                text_color=COLOR["text_primary"],
                width=65,
                height=28,
                corner_radius=6,
                command=lambda mid=m_id: check_single_model(mid)
            )
            btn_test.grid(row=0, column=3, rowspan=2, padx=(0, 12), pady=8)
            model_test_btns[m_id] = btn_test

        # Footer
        footer = ctk.CTkFrame(dialog, fg_color="transparent")
        footer.pack(fill="x", padx=18, pady=(4, 16))

        ctk.CTkLabel(
            footer,
            text=f"Всего моделей: {len(model_lines)}",
            font=self.font(size=11),
            text_color=COLOR["text_muted"]
        ).pack(side="left")

        ctk.CTkButton(
            footer,
            text="Закрыть",
            font=self.font(size=12, weight="bold"),
            width=90,
            command=dialog.destroy
        ).pack(side="right")

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
            hover_color=("#eaeef2", "#21262d"),
            text_color=COLOR["text_muted"],
            width=24,
            height=24,
            corner_radius=6,
            command=lambda: self.flash_banner.pack_forget(),
        ).grid(row=0, column=1, sticky="e", padx=8)

    def show_flash(self, message):
        self.lbl_flash.configure(text=message)
        # CTkScrollableFrame packs an outer wrapper, not the widget itself.
        # Anchor to the action bar (a direct sibling) so Tk can place the banner.
        self.flash_banner.pack(fill="x", padx=24, pady=(10, 0), after=self.top_action_bar)
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
        elif self.current_provider_view == "openai":
            self.render_openai_grid()
        elif self.current_provider_view == "claude":
            self.render_claude_grid()

    def render_google_grid(self):
        data = self.accounts_data
        if self.search_query:
            data = [a for a in data if self.search_query in a.get("email", "").lower()]

        total = len(self.accounts_data)
        active_idx = get_active_google_account_index()
        self.lbl_count_pill.configure(text=f"Все ({total})")
        self.google_accounts_status.configure(text=f"● Аккаунтов: {total}")

        if not data:
            self._render_empty_state("Google (Antigravity)")
            return

        data = sorted(data, key=lambda account: account.get("index", 1) - 1 != active_idx)

        # Prototype layout: account list on the left and selected-account details
        # (including the actual configured route) on the right.
        page = ctk.CTkFrame(self.accounts_container, fg_color="transparent")
        page.pack(fill="both", expand=True)
        page.configure(height=680)
        page.grid_propagate(False)
        page.grid_columnconfigure(0, weight=7, uniform="google_page")
        page.grid_columnconfigure(1, weight=4, uniform="google_page")
        page.grid_rowconfigure(0, weight=1)

        account_list = ctk.CTkFrame(page, fg_color="transparent")
        account_list.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        account_list.grid_columnconfigure(0, weight=1)

        active_account = next(
            (a for a in data if a.get("index", 1) - 1 == active_idx), data[0]
        )
        for idx, acc in enumerate(data):
            is_active = (acc.get("index", 1) - 1 == active_idx)
            card = self.create_google_prototype_card(account_list, acc, is_active=is_active)
            card.grid(row=idx, column=0, padx=(0, 4), pady=(0, 10), sticky="ew")

        self.render_google_account_detail(page, active_account)

    def create_google_prototype_card(self, parent, account, is_active=False):
        """Compact wide account row matching the selected frosted-glass prototype."""
        email = account.get("email", "unknown@gmail.com")
        account_index = account.get("index", 1)
        groups = account.get("groups", [])
        gemini = next((group for group in groups if group.get("name") == "gemini"), None)

        def quota_percent(group, period):
            if not group:
                return 100
            windows = group.get("windows", [])
            for window in windows:
                name = str(window.get("window", "")).lower()
                if (period == "short" and "5" in name) or (
                    period == "weekly" and any(token in name for token in ("week", "7d"))
                ):
                    try:
                        return max(0, min(100, float(window.get("remainingPercent", 100))))
                    except (TypeError, ValueError):
                        break
            try:
                return max(0, min(100, float(group.get("remainingPercent", 100))))
            except (TypeError, ValueError):
                return 100

        remaining_5h = quota_percent(gemini, "short")
        remaining_week = quota_percent(gemini, "weekly")
        card = ctk.CTkFrame(
            parent, fg_color=COLOR["card_active_bg"] if is_active else COLOR["card_bg"],
            corner_radius=16, border_width=1,
            border_color=COLOR["border_active"] if is_active else COLOR["border"],
        )

        body = ctk.CTkFrame(card, fg_color="transparent")
        body.pack(fill="x", padx=15, pady=(13, 9))
        body.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(
            body, text="G", width=34, height=34, corner_radius=17,
            fg_color=COLOR["glass_highlight"], text_color="#78b9ff",
            font=self.font(size=18, weight="bold"),
        ).grid(row=0, column=0, rowspan=2, sticky="w", padx=(0, 11))
        ctk.CTkLabel(
            body, text=email, font=self.font(size=14, weight="bold"),
            text_color=COLOR["text_primary"], anchor="w",
        ).grid(row=0, column=1, sticky="ew")
        ctk.CTkLabel(
            body, text="Основной аккаунт" if is_active else "Дополнительный аккаунт",
            font=self.font(size=11), text_color=COLOR["text_muted"], anchor="w",
        ).grid(row=1, column=1, sticky="ew", pady=(2, 0))
        ctk.CTkLabel(
            body, text="● Активен" if is_active else "В пуле",
            font=self.font(size=11, weight="bold"),
            text_color=COLOR["accent_emerald"] if is_active else COLOR["text_muted"],
            fg_color=COLOR["quota_5h_bg"] if is_active else COLOR["subbox_bg"],
            corner_radius=9, padx=9, pady=4,
        ).grid(row=0, column=2, rowspan=2, sticky="e", padx=(10, 0))

        quotas = ctk.CTkFrame(card, fg_color="transparent")
        quotas.pack(fill="x", padx=15, pady=(0, 10))
        quotas.grid_columnconfigure(0, weight=1, uniform="quota")
        quotas.grid_columnconfigure(1, weight=1, uniform="quota")
        for col, title, value, color in (
            (0, "Квота Gemini · 5 часов", remaining_5h, COLOR["quota_5h"][1]),
            (1, "Недельная квота Gemini", remaining_week, COLOR["quota_weekly"][1]),
        ):
            meter = ctk.CTkFrame(quotas, fg_color="transparent")
            meter.grid(row=0, column=col, sticky="ew", padx=(0, 12) if col == 0 else (12, 0))
            label_row = ctk.CTkFrame(meter, fg_color="transparent")
            label_row.pack(fill="x", pady=(0, 4))
            ctk.CTkLabel(label_row, text=title, font=self.font(size=11),
                         text_color=COLOR["text_secondary"]).pack(side="left")
            ctk.CTkLabel(label_row, text=f"{value:.0f}%", font=self.font(size=11, weight="bold"),
                         text_color=COLOR["text_primary"]).pack(side="right")
            bar = ctk.CTkProgressBar(meter, height=7, corner_radius=4,
                                     fg_color=COLOR["bar_bg"], progress_color=color)
            bar.pack(fill="x")
            bar.set(value / 100)

        actions = ctk.CTkFrame(card, fg_color="transparent")
        actions.pack(fill="x", padx=15, pady=(0, 12))
        if not is_active:
            ctk.CTkButton(
                actions, text="Сделать активным", height=32, width=140, corner_radius=10,
                fg_color=COLOR["nav_active_bg"], hover_color=COLOR["glass_highlight"],
                text_color=COLOR["nav_active_text"], border_width=1,
                border_color=COLOR["border"], font=self.font(size=11, weight="bold"),
                command=lambda idx=account_index - 1: self.activate_google_account_action(idx),
            ).pack(side="left", padx=(0, 6))
        ctk.CTkButton(
            actions, text="Проверить", height=32, width=92, corner_radius=10,
            fg_color=COLOR["subbox_bg"], hover_color=COLOR["glass_highlight"],
            text_color=COLOR["text_secondary"], border_width=1,
            border_color=COLOR["border"], font=self.font(size=11),
            command=lambda a=account: self.test_google_account_action(a),
        ).pack(side="left", padx=(0, 6))
        ctk.CTkButton(
            actions, text="Удалить", height=32, width=76, corner_radius=10,
            fg_color=COLOR["subbox_bg"], hover_color=("#ffebe9", "#3c1e1e"),
            text_color=("#cf222e", "#f85149"), border_width=1,
            border_color=COLOR["border"], font=self.font(size=11),
            command=lambda a=account: self.delete_google_account_action(a),
        ).pack(side="left")
        rotation_var = tk.BooleanVar(value=account.get("candidate", True))
        create_cyber_switch(
            actions, text="Авторотация", variable=rotation_var,
            font=self.font(size=11),
            command=lambda a=account, v=rotation_var: self.toggle_account_candidate(a, v.get()),
        ).pack(side="right")
        return card

    def render_google_account_detail(self, parent, account):
        """Render the prototype's right-side account and network detail panel."""
        detail = ctk.CTkFrame(
            parent, fg_color=COLOR["card_bg"], corner_radius=16,
            border_width=1, border_color=COLOR["border"],
        )
        detail.grid(row=0, column=1, sticky="nsew", padx=(8, 0), pady=(0, 0))
        detail.grid_columnconfigure(0, weight=1)
        detail.grid_rowconfigure(5, weight=1)

        email = account.get("email", "Google account")
        is_active = account.get("index", 1) - 1 == get_active_google_account_index()
        head = ctk.CTkFrame(detail, fg_color="transparent")
        head.grid(row=0, column=0, sticky="ew", padx=18, pady=(18, 14))
        ctk.CTkLabel(
            head, text="G", width=38, height=38, corner_radius=19,
            fg_color=COLOR["glass_highlight"], text_color="#78b9ff",
            font=self.font(size=20, weight="bold"),
        ).pack(side="left", padx=(0, 12))
        identity = ctk.CTkFrame(head, fg_color="transparent")
        identity.pack(side="left", fill="x", expand=True)
        ctk.CTkLabel(
            identity, text=email, font=self.font(size=13, weight="bold"),
            text_color=COLOR["text_primary"], anchor="w",
        ).pack(anchor="w")
        ctk.CTkLabel(
            identity, text="Активный аккаунт" if is_active else "Аккаунт в пуле",
            font=self.font(size=10), text_color=COLOR["text_muted"], anchor="w",
        ).pack(anchor="w", pady=(2, 0))

        state = "● Активен" if is_active else "● В пуле"
        ctk.CTkLabel(
            detail, text=state, font=self.font(size=10, weight="bold"),
            text_color=COLOR["accent_emerald"], fg_color=COLOR["quota_5h_bg"],
            corner_radius=9, padx=10, pady=5,
        ).grid(row=1, column=0, sticky="w", padx=18, pady=(0, 14))

        route = self.config_data.get("provider_routes", {}).get("google", "direct")
        route_labels = {
            "google-smart": "Google SmartDNS", "vless": "VLESS-туннель",
            "proxy": "Внешний прокси", "dns": "DNS-прокси Hub", "direct": "Напрямую",
        }
        route_card = ctk.CTkFrame(
            detail, fg_color=COLOR["subbox_bg"], corner_radius=12,
            border_width=1, border_color=COLOR["border"],
        )
        route_card.grid(row=2, column=0, sticky="ew", padx=14, pady=(0, 12))
        ctk.CTkLabel(
            route_card, text="Сеть и маршрут", font=self.font(size=12, weight="bold"),
            text_color=COLOR["text_primary"],
        ).pack(anchor="w", padx=13, pady=(12, 5))
        ctk.CTkLabel(
            route_card, text=f"⇄  {route_labels.get(route, route)}",
            font=self.font(size=12, weight="bold"), text_color=COLOR["accent_cyan"],
        ).pack(anchor="w", padx=13, pady=(0, 3))
        route_short = {
            "google-smart": "SmartDNS", "vless": "VLESS", "proxy": "Прокси",
            "dns": "DNS Hub", "direct": "Напрямую",
        }.get(route, str(route))
        flow = ctk.CTkFrame(route_card, fg_color="transparent")
        flow.pack(fill="x", padx=13, pady=(8, 7))
        for column in (0, 2, 4):
            flow.grid_columnconfigure(column, weight=1, uniform="route_flow")
        for column, title in ((0, "Этот компьютер"), (2, route_short), (4, "Cloud Code")):
            ctk.CTkLabel(
                flow, text=title, fg_color=COLOR["glass_highlight"],
                text_color=COLOR["text_secondary"], font=self.font(size=10, weight="bold"),
                corner_radius=8, height=34, wraplength=90,
            ).grid(row=0, column=column, sticky="ew", padx=2)
        for column in (1, 3):
            ctk.CTkLabel(
                flow, text="›", text_color=COLOR["accent_cyan"],
                font=self.font(size=17, weight="bold"), width=14,
            ).grid(row=0, column=column)
        ctk.CTkLabel(
            route_card, text="Маршрут применяется к запросам Google Cloud Code.",
            font=self.font(size=10), text_color=COLOR["text_muted"], wraplength=260,
            justify="left",
        ).pack(anchor="w", padx=13, pady=(0, 12))

        info = ctk.CTkFrame(
            detail, fg_color=COLOR["subbox_bg"], corner_radius=12,
            border_width=1, border_color=COLOR["border"],
        )
        info.grid(row=3, column=0, sticky="ew", padx=14, pady=(0, 12))
        ctk.CTkLabel(
            info, text="Сведения об аккаунте", font=self.font(size=12, weight="bold"),
            text_color=COLOR["text_primary"],
        ).pack(anchor="w", padx=13, pady=(12, 7))
        added_at = account.get("addedAt")
        added_label = self.format_added_date(added_at) if added_at else "Не указана"
        account_id = account.get("id") or "Не указан"
        for label, value in (("Статус", "Активен" if is_active else "В пуле"),
                             ("Добавлен", added_label), ("ID", str(account_id)[:18])):
            row = ctk.CTkFrame(info, fg_color="transparent")
            row.pack(fill="x", padx=13, pady=3)
            ctk.CTkLabel(row, text=label, font=self.font(size=10),
                         text_color=COLOR["text_muted"]).pack(side="left")
            ctk.CTkLabel(row, text=value, font=self.font(size=10, weight="bold"),
                         text_color=COLOR["text_secondary"]).pack(side="right")
        quota_card = ctk.CTkFrame(
            detail, fg_color=COLOR["subbox_bg"], corner_radius=12,
            border_width=1, border_color=COLOR["border"],
        )
        quota_card.grid(row=4, column=0, sticky="ew", padx=14, pady=(0, 12))
        ctk.CTkLabel(
            quota_card, text="Квоты использования", font=self.font(size=12, weight="bold"),
            text_color=COLOR["text_primary"],
        ).pack(anchor="w", padx=13, pady=(12, 8))
        gemini_group = next((g for g in account.get("groups", []) if g.get("name") == "gemini"), None)

        def quota_remaining(group, tokens):
            if not group:
                return None
            for window in group.get("windows", []):
                name = str(window.get("window", "")).lower()
                if any(token in name for token in tokens):
                    try:
                        return max(0.0, min(100.0, float(window.get("remainingPercent", 100))))
                    except (TypeError, ValueError):
                        return None
            try:
                return max(0.0, min(100.0, float(group.get("remainingPercent", 100))))
            except (TypeError, ValueError):
                return None

        for title, remaining, color in (
            ("Текущая квота · 5 часов", quota_remaining(gemini_group, ("5",)), COLOR["quota_5h"][1]),
            ("Недельная квота", quota_remaining(gemini_group, ("week", "7d")), COLOR["quota_weekly"][1]),
        ):
            meter = ctk.CTkFrame(quota_card, fg_color="transparent")
            meter.pack(fill="x", padx=13, pady=(2, 8))
            row = ctk.CTkFrame(meter, fg_color="transparent")
            row.pack(fill="x", pady=(0, 5))
            ctk.CTkLabel(row, text=title, font=self.font(size=11),
                         text_color=COLOR["text_secondary"]).pack(side="left")
            shown = f"{remaining:.0f}%" if remaining is not None else "Нет данных"
            ctk.CTkLabel(row, text=shown, font=self.font(size=11, weight="bold"),
                         text_color=COLOR["text_primary"]).pack(side="right")
            bar = ctk.CTkProgressBar(meter, height=8, corner_radius=4,
                                     fg_color=COLOR["bar_bg"], progress_color=color)
            bar.pack(fill="x")
            bar.set(remaining / 100 if remaining is not None else 0)

        ctk.CTkButton(
            detail, text="Диагностика маршрута Google", height=36, corner_radius=10,
            fg_color=COLOR["nav_active_bg"], hover_color=COLOR["glass_highlight"],
            text_color=COLOR["nav_active_text"], border_width=1,
            border_color=COLOR["border"], command=self.open_google_route_diagnostics,
        ).grid(row=6, column=0, sticky="ew", padx=14, pady=(0, 14))

    def open_google_route_diagnostics(self):
        self.switch_nav("network")
        if hasattr(self.network_view, "diagnose_google_route"):
            self.network_view.diagnose_google_route()

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

    def render_claude_grid(self):
        data = self.claude_accounts_data
        if self.search_query:
            data = [a for a in data if self.search_query in a.get("email", "").lower()]

        total = len(self.claude_accounts_data)
        self.lbl_count_pill.configure(text=f"Все ({total})")

        if not data:
            self._render_empty_state("Claude (Anthropic Pro)")
            return

        grid_frame = ctk.CTkFrame(self.accounts_container, fg_color="transparent")
        grid_frame.pack(fill="both", expand=True)

        for col in range(2):
            grid_frame.grid_columnconfigure(col, weight=1, uniform="card_col")

        for idx, acc in enumerate(data):
            row = idx // 2
            col = idx % 2
            is_active = acc.get("active", False)
            card = self.create_compact_claude_card(grid_frame, acc, is_active=is_active)
            card.grid(row=row, column=col, padx=8, pady=8, sticky="nsew")

    def _render_empty_state(self, title):
        box = ctk.CTkFrame(
            self.accounts_container, fg_color=COLOR["card_bg"], corner_radius=18,
            border_width=1, border_color=COLOR["border"],
        )
        box.pack(fill="x", expand=True, pady=(34, 20), padx=24)
        ctk.CTkLabel(
            box, text="＋", width=64, height=64, corner_radius=32,
            fg_color=COLOR["glass_highlight"], text_color=COLOR["accent_cyan"],
            font=self.font(size=34, weight="bold"),
        ).pack(pady=(30, 16))
        ctk.CTkLabel(
            box, text=f"Подключите {title}", font=self.font(size=21, weight="bold"),
            text_color=COLOR["text_primary"],
        ).pack()
        ctk.CTkLabel(
            box, text="Здесь появятся аккаунты и актуальная информация после подключения.",
            font=self.font(size=13), text_color=COLOR["text_secondary"],
            justify="center", wraplength=520,
        ).pack(pady=(7, 18), padx=24)
        provider = getattr(self, "current_provider_view", "google")
        add_action = {
            "google": self.add_account_action,
            "openai": self.add_openai_account_action,
            "claude": self.add_claude_account_action,
        }.get(provider, self.add_account_action)
        ctk.CTkButton(
            box, text=f"＋ Добавить {title}", command=add_action,
            font=self.font(size=13, weight="bold"), height=42, corner_radius=12,
            fg_color="#a96e2c", hover_color="#c88635",
            text_color="#ffffff",
        ).pack(pady=(0, 30))

    def copy_to_clipboard(self, text, message="Скопировано в буфер"):
        try:
            self.clipboard_clear()
            self.clipboard_append(text)
            self.update()
            self.show_flash(f"📋 {message}")
        except Exception:
            pass

    def toggle_account_candidate(self, acc, enabled):
        try:
            acc["candidate"] = enabled
            aid = acc.get("id") or acc.get("email")
            email = acc.get("email", "Аккаунт")
            if aid:
                set_google_account_candidate(aid, enabled)
            self.show_flash(f"Аккаунт {email} {'включен в авторотацию' if enabled else 'исключен из авторотации'}")
        except Exception as e:
            print(f"Error toggling candidate: {e}")

    # =========================================================================
    # COMPACT CARD (High-contrast Segoe UI, Dual Theme)
    # =========================================================================
    def create_compact_card(self, parent, acc, is_active=False):
        email = acc.get("email", "unknown@gmail.com")
        index = acc.get("index", 1)
        added_at = acc.get("addedAt")
        aid = str(acc.get("id") or "")
        short_id = aid[:8] if aid else f"acc-{index}"
        groups = acc.get("groups", [])

        gemini_group = next((g for g in groups if g.get("name") == "gemini"), None)
        nongemini_group = next((g for g in groups if g.get("name") == "non-gemini"), None)

        card = ctk.CTkFrame(
            parent,
            fg_color=COLOR["card_active_bg"] if is_active else COLOR["card_bg"],
            corner_radius=16,
            border_width=1,
            border_color=COLOR["border_active"] if is_active else COLOR["border"],
        )

        # 1. Top Header Row
        header = ctk.CTkFrame(card, fg_color="transparent")
        header.pack(fill="x", padx=14, pady=(14, 6))
        header.grid_columnconfigure(0, weight=1)

        title_box = ctk.CTkFrame(header, fg_color="transparent")
        title_box.grid(row=0, column=0, sticky="w")

        prefix = "⭐ " if is_active else ""
        short_email = email if len(email) <= 26 else f"{email[:23]}..."
        email_lbl = ctk.CTkLabel(
            title_box,
            text=f"{prefix}{short_email}",
            font=self.font(size=13, weight="bold"),
            text_color=COLOR["text_primary"],
        )
        email_lbl.pack(anchor="w")

        status_sub = "Токен активен" if acc.get("accessToken") else "Готов к работе"
        meta_lbl = ctk.CTkLabel(
            title_box,
            text=f"{status_sub} • ID: {short_id}",
            font=self.font(size=11),
            text_color=COLOR["text_muted"],
        )
        meta_lbl.pack(anchor="w", pady=(1, 0))

        # Badges box
        badges_box = ctk.CTkFrame(header, fg_color="transparent")
        badges_box.grid(row=0, column=1, sticky="e")

        if is_active:
            status_badge = ctk.CTkLabel(
                badges_box,
                text="● Активен",
                font=self.font(size=11, weight="bold"),
                fg_color=("#2da44e", "#238636"),
                text_color="#ffffff",
                corner_radius=6,
                padx=8,
                pady=2,
            )
            status_badge.pack(side="left", padx=(0, 6))
        else:
            in_pool_badge = ctk.CTkLabel(
                badges_box,
                text="В пуле",
                font=self.font(size=11, weight="bold"),
                fg_color=COLOR["subbox_bg"],
                text_color=COLOR["text_muted"],
                border_width=1,
                border_color=COLOR["border"],
                corner_radius=6,
                padx=8,
                pady=2,
            )
            in_pool_badge.pack(side="left", padx=(0, 6))

        pro_badge = ctk.CTkLabel(
            badges_box,
            text="PRO",
            font=self.font(size=11, weight="bold"),
            fg_color=COLOR["subbox_bg"],
            text_color=COLOR["accent_cyan"],
            border_width=1,
            border_color=COLOR["border"],
            corner_radius=6,
            padx=7,
            pady=2,
        )
        pro_badge.pack(side="left")

        # 2. Sleek Inset Quotas Box (Linear Minimal spec)
        quotas_container = ctk.CTkFrame(
            card,
            fg_color=COLOR["subbox_bg"],
            corner_radius=8,
            border_width=1,
            border_color=COLOR["border"],
        )
        quotas_container.pack(fill="x", padx=14, pady=(4, 8), ipadx=4, ipady=4)

        def extract_quota_windows(group_info):
            if not group_info:
                return (100.0, ""), (100.0, "")
            windows = group_info.get("windows", [])
            w5h = None
            w_weekly = None
            for w in windows:
                w_name = str(w.get("window", "")).strip().lower()
                if "5" in w_name:
                    w5h = w
                elif any(k in w_name for k in ("week", "7d")):
                    w_weekly = w

            if w5h:
                pct_5h = round(float(w5h.get("remainingPercent", 100.0)), 1)
                reset_5h = self.format_compact_reset(w5h.get("resetTime", ""))
            else:
                pct_5h = round(float(group_info.get("remainingPercent", 100.0)), 1)
                reset_5h = self.format_compact_reset(group_info.get("resetTime", ""))

            if w_weekly:
                pct_wk = round(float(w_weekly.get("remainingPercent", 100.0)), 1)
                reset_wk = self.format_compact_reset(w_weekly.get("resetTime", ""))
            else:
                pct_wk = round(float(group_info.get("remainingPercent", 100.0)), 1)
                reset_wk = self.format_compact_reset(group_info.get("resetTime", ""))

            return (pct_5h, reset_5h), (pct_wk, reset_wk)

        def render_model_quota(container, model_title, q_5h, q_weekly, is_last=False):
            pct_5h, reset_5h = q_5h
            pct_wk, reset_wk = q_weekly

            # Model title
            t_row = ctk.CTkFrame(container, fg_color="transparent")
            t_row.pack(fill="x", padx=8, pady=(4, 2))
            ctk.CTkLabel(t_row, text=model_title, font=self.font(size=12, weight="bold"), text_color=COLOR["text_primary"]).pack(side="left")

            # 5-hour limit
            r5_row = ctk.CTkFrame(container, fg_color="transparent")
            r5_row.pack(fill="x", padx=8, pady=(2, 1))
            col_5h = "#f85149" if pct_5h <= 20 else COLOR["quota_5h"][1]
            reset_str_5h = f" ({reset_5h})" if reset_5h else ""

            b5_lbl = ctk.CTkLabel(
                r5_row,
                text="⚡ 5 часов",
                font=self.font(size=10, weight="bold"),
                fg_color=COLOR["quota_5h_bg"],
                text_color=col_5h,
                corner_radius=4,
                padx=6,
                pady=1
            )
            b5_lbl.pack(side="left")
            ctk.CTkLabel(r5_row, text=f"{int(pct_5h)}%{reset_str_5h}", font=self.font(size=11, weight="bold"), text_color=col_5h).pack(side="right")

            b_5h = ctk.CTkProgressBar(container, height=4, corner_radius=2)
            b_5h.pack(fill="x", padx=8, pady=(2, 4))
            b_5h.set(max(0.0, min(1.0, pct_5h / 100.0)))
            b_5h.configure(progress_color=col_5h, fg_color=COLOR["bar_bg"])

            # Weekly limit
            rwk_row = ctk.CTkFrame(container, fg_color="transparent")
            rwk_row.pack(fill="x", padx=8, pady=(2, 1))
            col_wk = "#f85149" if pct_wk <= 20 else COLOR["quota_weekly"][1]
            reset_str_wk = f" ({reset_wk})" if reset_wk else ""

            bwk_lbl = ctk.CTkLabel(
                rwk_row,
                text="📅 Неделя",
                font=self.font(size=10, weight="bold"),
                fg_color=COLOR["quota_weekly_bg"],
                text_color=col_wk,
                corner_radius=4,
                padx=6,
                pady=1
            )
            bwk_lbl.pack(side="left")
            ctk.CTkLabel(rwk_row, text=f"{int(pct_wk)}%{reset_str_wk}", font=self.font(size=11, weight="bold"), text_color=col_wk).pack(side="right")

            b_wk = ctk.CTkProgressBar(container, height=4, corner_radius=2)
            b_wk.pack(fill="x", padx=8, pady=(2, 2 if is_last else 6))
            b_wk.set(max(0.0, min(1.0, pct_wk / 100.0)))
            b_wk.configure(progress_color=col_wk, fg_color=COLOR["bar_bg"])

        render_model_quota(quotas_container, "Gemini 3.8 Flash", *extract_quota_windows(gemini_group))
        render_model_quota(quotas_container, "Claude Sonnet 4.6 / 5.5", *extract_quota_windows(nongemini_group), is_last=True)

        # 3. Card Footer with Action Buttons & Cyber Switch
        divider = ctk.CTkFrame(card, height=1, fg_color=COLOR["border"])
        divider.pack(fill="x", padx=14, pady=(4, 8))

        footer = ctk.CTkFrame(card, fg_color="transparent")
        footer.pack(fill="x", padx=14, pady=(0, 10))
        footer.grid_columnconfigure(0, weight=1)

        # Left: Actions
        actions_pill = ctk.CTkFrame(footer, fg_color="transparent")
        actions_pill.grid(row=0, column=0, sticky="w")

        ctk.CTkButton(
            actions_pill,
            text="🩺 Тест",
            font=self.font(size=11, weight="bold"),
            fg_color=("#f6f8fa", "#21262d"),
            hover_color=("#eaeef2", "#30363d"),
            text_color=COLOR["text_primary"],
            border_width=1,
            border_color=COLOR["border"],
            width=58,
            height=28,
            corner_radius=6,
            command=lambda a=acc: self.test_google_account_action(a),
        ).pack(side="left", padx=(0, 4))

        if not is_active:
            ctk.CTkButton(
                actions_pill,
                text="⭐ Выбрать",
                font=self.font(size=11, weight="bold"),
                fg_color=("#0969da", "#c88635"),
                hover_color=("#0550ae", "#e09a43"),
                text_color="#ffffff",
                width=76,
                height=28,
                corner_radius=6,
                command=lambda idx=index - 1: self.activate_google_account_action(idx),
            ).pack(side="left", padx=(0, 4))

        ctk.CTkButton(
            actions_pill,
            text="📋",
            font=self.font(size=13, weight="bold"),
            fg_color=("#f6f8fa", "#21262d"),
            hover_color=("#eaeef2", "#30363d"),
            text_color=COLOR["text_primary"],
            border_width=1,
            border_color=COLOR["border"],
            width=30,
            height=28,
            corner_radius=6,
            command=lambda e=email: self.copy_to_clipboard(e, "Email скопирован"),
        ).pack(side="left", padx=(0, 4))

        ctk.CTkButton(
            actions_pill,
            text="🗑",
            font=self.font(size=13, weight="bold"),
            fg_color=("#f6f8fa", "#21262d"),
            hover_color=("#ffebe9", "#3c1e1e"),
            text_color=("#cf222e", "#f85149"),
            border_width=1,
            border_color=COLOR["border"],
            width=30,
            height=28,
            corner_radius=6,
            command=lambda a=acc: self.delete_google_account_action(a),
        ).pack(side="left")

        # Right: Cyber Pill Switch for Auto-rotation / In Pool
        right_box = ctk.CTkFrame(footer, fg_color="transparent")
        right_box.grid(row=0, column=1, sticky="e")

        rot_var = tk.BooleanVar(value=acc.get("candidate", True))
        create_cyber_switch(
            right_box,
            text="Авторотация",
            variable=rot_var,
            font=self.font(size=11),
            command=lambda a=acc, v=rot_var: self.toggle_account_candidate(a, v.get())
        ).pack(side="right")

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
        color = (COLOR["quota_5h"][1] if rem > 50 else (COLOR["quota_weekly"][1] if rem > 20 else "#f85149")) if rem is not None else COLOR["text_muted"]

        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", pady=(2, 0))

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

        bar = ctk.CTkProgressBar(parent, height=4, corner_radius=2)
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
    # COMPACT OPENAI CARD (Linear Minimal spec)
    # =========================================================================
    def create_compact_openai_card(self, parent, acc, is_active=False):
        email = acc.get("email", "unknown@chatgpt.com")
        account_id = acc.get("accountId") or acc.get("id") or ""
        short_id = account_id[:8] if account_id else "chatgpt"
        plan_type = (acc.get("plan_type") or "plus").upper()
        quota = acc.get("quota") or {}

        primary_quota = quota.get("window_5h") or quota.get("primary") or {}
        secondary_quota = quota.get("window_weekly") or quota.get("secondary") or {}

        card = ctk.CTkFrame(
            parent,
            fg_color=COLOR["card_active_bg"] if is_active else COLOR["card_bg"],
            corner_radius=16,
            border_width=1,
            border_color=COLOR["border_active"] if is_active else COLOR["border"],
        )

        # 1. Top Header Row
        header = ctk.CTkFrame(card, fg_color="transparent")
        header.pack(fill="x", padx=14, pady=(14, 6))
        header.grid_columnconfigure(0, weight=1)

        title_box = ctk.CTkFrame(header, fg_color="transparent")
        title_box.grid(row=0, column=0, sticky="w")

        prefix = "⭐ " if is_active else ""
        short_email = email if len(email) <= 26 else f"{email[:23]}..."
        ctk.CTkLabel(
            title_box,
            text=f"{prefix}{short_email}",
            font=self.font(size=13, weight="bold"),
            text_color=COLOR["text_primary"],
        ).pack(anchor="w")

        ctk.CTkLabel(
            title_box,
            text=f"OpenAI OAuth • ID: {short_id}",
            font=self.font(size=11),
            text_color=COLOR["text_muted"],
        ).pack(anchor="w", pady=(1, 0))

        badges_box = ctk.CTkFrame(header, fg_color="transparent")
        badges_box.grid(row=0, column=1, sticky="e")

        if is_active:
            ctk.CTkLabel(
                badges_box,
                text="● Активен",
                font=self.font(size=11, weight="bold"),
                fg_color=("#2da44e", "#238636"),
                text_color="#ffffff",
                corner_radius=6,
                padx=8,
                pady=2,
            ).pack(side="left", padx=(0, 6))
        else:
            ctk.CTkLabel(
                badges_box,
                text="В пуле",
                font=self.font(size=11, weight="bold"),
                fg_color=COLOR["subbox_bg"],
                text_color=COLOR["text_muted"],
                border_width=1,
                border_color=COLOR["border"],
                corner_radius=6,
                padx=8,
                pady=2,
            ).pack(side="left", padx=(0, 6))

        ctk.CTkLabel(
            badges_box,
            text=plan_type,
            font=self.font(size=11, weight="bold"),
            fg_color=COLOR["subbox_bg"],
            text_color=COLOR["accent_cyan"],
            border_width=1,
            border_color=COLOR["border"],
            corner_radius=6,
            padx=7,
            pady=2,
        ).pack(side="left")

        # 2. Sleek Inset Quotas Box (Linear Minimal spec)
        quotas_container = ctk.CTkFrame(
            card,
            fg_color=COLOR["subbox_bg"],
            corner_radius=8,
            border_width=1,
            border_color=COLOR["border"],
        )
        quotas_container.pack(fill="x", padx=14, pady=(4, 8), ipadx=4, ipady=4)

        rem_p = round(float(primary_quota.get("remaining_percent", 100.0)), 1)
        reset_p = self.format_compact_reset(primary_quota.get("reset_at"))
        reset_p_str = f" ({reset_p})" if reset_p else ""
        col_p = "#f85149" if rem_p <= 20 else COLOR["quota_5h"][1]

        row1 = ctk.CTkFrame(quotas_container, fg_color="transparent")
        row1.pack(fill="x", padx=8, pady=(4, 1))
        b5_lbl = ctk.CTkLabel(
            row1,
            text="⚡ 5 часов",
            font=self.font(size=10, weight="bold"),
            fg_color=COLOR["quota_5h_bg"],
            text_color=col_p,
            corner_radius=4,
            padx=6,
            pady=1
        )
        b5_lbl.pack(side="left")
        ctk.CTkLabel(row1, text=f"{int(rem_p)}%{reset_p_str}", font=self.font(size=11, weight="bold"), text_color=col_p).pack(side="right")

        bar1 = ctk.CTkProgressBar(quotas_container, height=4, corner_radius=2)
        bar1.pack(fill="x", padx=8, pady=(2, 6))
        bar1.set(max(0.0, min(1.0, rem_p / 100.0)))
        bar1.configure(progress_color=col_p, fg_color=COLOR["bar_bg"])

        rem_s = round(float(secondary_quota.get("remaining_percent", 100.0)), 1)
        reset_s = self.format_compact_reset(secondary_quota.get("reset_at"))
        reset_s_str = f" ({reset_s})" if reset_s else ""
        col_s = "#f85149" if rem_s <= 20 else COLOR["quota_weekly"][1]

        row2 = ctk.CTkFrame(quotas_container, fg_color="transparent")
        row2.pack(fill="x", padx=8, pady=(2, 1))
        bwk_lbl = ctk.CTkLabel(
            row2,
            text="📅 Неделя",
            font=self.font(size=10, weight="bold"),
            fg_color=COLOR["quota_weekly_bg"],
            text_color=col_s,
            corner_radius=4,
            padx=6,
            pady=1
        )
        bwk_lbl.pack(side="left")
        ctk.CTkLabel(row2, text=f"{int(rem_s)}%{reset_s_str}", font=self.font(size=11, weight="bold"), text_color=col_s).pack(side="right")

        bar2 = ctk.CTkProgressBar(quotas_container, height=4, corner_radius=2)
        bar2.pack(fill="x", padx=8, pady=(2, 4))
        bar2.set(max(0.0, min(1.0, rem_s / 100.0)))
        bar2.configure(progress_color=col_s, fg_color=COLOR["bar_bg"])

        # 3. Card Footer Actions
        divider = ctk.CTkFrame(card, height=1, fg_color=COLOR["border"])
        divider.pack(fill="x", padx=14, pady=(4, 8))

        footer = ctk.CTkFrame(card, fg_color="transparent")
        footer.pack(fill="x", padx=14, pady=(0, 10))
        footer.grid_columnconfigure(0, weight=1)

        actions_pill = ctk.CTkFrame(footer, fg_color="transparent")
        actions_pill.grid(row=0, column=0, sticky="w")

        ctk.CTkButton(
            actions_pill,
            text="🩺 Тест",
            font=self.font(size=11, weight="bold"),
            fg_color=("#f6f8fa", "#21262d"),
            hover_color=("#eaeef2", "#30363d"),
            text_color=COLOR["text_primary"],
            border_width=1,
            border_color=COLOR["border"],
            width=58,
            height=28,
            corner_radius=6,
            command=lambda a=acc: self.test_openai_account_action(a),
        ).pack(side="left", padx=(0, 4))

        if not is_active:
            ctk.CTkButton(
                actions_pill,
                text="⭐ Выбрать",
                font=self.font(size=11, weight="bold"),
                fg_color=("#0969da", "#c88635"),
                hover_color=("#0550ae", "#e09a43"),
                text_color="#ffffff",
                width=76,
                height=28,
                corner_radius=6,
                command=lambda aid=account_id: self.activate_openai_account_action(aid),
            ).pack(side="left", padx=(0, 4))

        ctk.CTkButton(
            actions_pill,
            text="📋",
            font=self.font(size=13, weight="bold"),
            fg_color=("#f6f8fa", "#21262d"),
            hover_color=("#eaeef2", "#30363d"),
            text_color=COLOR["text_primary"],
            border_width=1,
            border_color=COLOR["border"],
            width=30,
            height=28,
            corner_radius=6,
            command=lambda e=email: self.copy_to_clipboard(e, "Email скопирован"),
        ).pack(side="left", padx=(0, 4))

        ctk.CTkButton(
            actions_pill,
            text="🗑",
            font=self.font(size=13, weight="bold"),
            fg_color=("#f6f8fa", "#21262d"),
            hover_color=("#ffebe9", "#3c1e1e"),
            text_color=("#cf222e", "#f85149"),
            border_width=1,
            border_color=COLOR["border"],
            width=30,
            height=28,
            corner_radius=6,
            command=lambda a=acc: self.delete_openai_account_action(a),
        ).pack(side="left")

        right_box = ctk.CTkFrame(footer, fg_color="transparent")
        right_box.grid(row=0, column=1, sticky="e")

        rot_var = tk.BooleanVar(value=acc.get("is_active", False) or acc.get("candidate", True))
        create_cyber_switch(
            right_box,
            text="В пуле",
            variable=rot_var,
            font=self.font(size=11),
        ).pack(side="right")

        return card

    # =========================================================================
    # COMPACT CLAUDE PRO CARD (Linear Minimal spec)
    # =========================================================================
    def create_compact_claude_card(self, parent, acc, is_active=False):
        email = acc.get("email", "unknown@claude.ai")
        org_id = acc.get("org_id", "")
        short_id = org_id[:8] if org_id else "claude"
        plan_type = (acc.get("plan") or "pro").upper()

        card = ctk.CTkFrame(
            parent,
            fg_color=COLOR["card_active_bg"] if is_active else COLOR["card_bg"],
            corner_radius=16,
            border_width=1,
            border_color=COLOR["border_active"] if is_active else COLOR["border"],
        )

        # 1. Top Header Row
        header = ctk.CTkFrame(card, fg_color="transparent")
        header.pack(fill="x", padx=14, pady=(14, 6))
        header.grid_columnconfigure(0, weight=1)

        title_box = ctk.CTkFrame(header, fg_color="transparent")
        title_box.grid(row=0, column=0, sticky="w")

        prefix = "⭐ " if is_active else ""
        short_email = email if len(email) <= 26 else f"{email[:23]}..."
        ctk.CTkLabel(
            title_box,
            text=f"{prefix}{short_email}",
            font=self.font(size=13, weight="bold"),
            text_color=COLOR["text_primary"],
        ).pack(anchor="w")

        ctk.CTkLabel(
            title_box,
            text=f"Claude Subscription • ID: {short_id}",
            font=self.font(size=11),
            text_color=COLOR["text_muted"],
        ).pack(anchor="w", pady=(1, 0))

        badges_box = ctk.CTkFrame(header, fg_color="transparent")
        badges_box.grid(row=0, column=1, sticky="e")

        if is_active:
            ctk.CTkLabel(
                badges_box,
                text="● Активен",
                font=self.font(size=11, weight="bold"),
                fg_color=("#2da44e", "#238636"),
                text_color="#ffffff",
                corner_radius=6,
                padx=8,
                pady=2,
            ).pack(side="left", padx=(0, 6))
        else:
            ctk.CTkLabel(
                badges_box,
                text="В пуле",
                font=self.font(size=11, weight="bold"),
                fg_color=COLOR["subbox_bg"],
                text_color=COLOR["text_muted"],
                border_width=1,
                border_color=COLOR["border"],
                corner_radius=6,
                padx=8,
                pady=2,
            ).pack(side="left", padx=(0, 6))

        ctk.CTkLabel(
            badges_box,
            text=plan_type,
            font=self.font(size=11, weight="bold"),
            fg_color=COLOR["subbox_bg"],
            text_color=COLOR["accent_purple"],
            border_width=1,
            border_color=COLOR["border"],
            corner_radius=6,
            padx=7,
            pady=2,
        ).pack(side="left")

        # 2. Sleek Inset Quotas Box (Linear Minimal spec)
        quotas_container = ctk.CTkFrame(
            card,
            fg_color=COLOR["subbox_bg"],
            corner_radius=8,
            border_width=1,
            border_color=COLOR["border"],
        )
        quotas_container.pack(fill="x", padx=14, pady=(4, 8), ipadx=4, ipady=4)

        t_row = ctk.CTkFrame(quotas_container, fg_color="transparent")
        t_row.pack(fill="x", padx=8, pady=(4, 2))
        ctk.CTkLabel(t_row, text="Claude 3.7 / 3.5 Sonnet & Opus", font=self.font(size=12, weight="bold"), text_color=COLOR["text_primary"]).pack(side="left")

        # 5-hour limit
        r5_row = ctk.CTkFrame(quotas_container, fg_color="transparent")
        r5_row.pack(fill="x", padx=8, pady=(2, 1))
        b5_lbl = ctk.CTkLabel(
            r5_row,
            text="⚡ 5 часов",
            font=self.font(size=10, weight="bold"),
            fg_color=COLOR["quota_5h_bg"],
            text_color=COLOR["quota_5h"][1],
            corner_radius=4,
            padx=6,
            pady=1
        )
        b5_lbl.pack(side="left")
        ctk.CTkLabel(r5_row, text="100% (квота доступна)", font=self.font(size=11, weight="bold"), text_color=COLOR["quota_5h"][1]).pack(side="right")

        b_5h = ctk.CTkProgressBar(quotas_container, height=4, corner_radius=2)
        b_5h.pack(fill="x", padx=8, pady=(2, 4))
        b_5h.set(1.0)
        b_5h.configure(progress_color=COLOR["quota_5h"][1], fg_color=COLOR["bar_bg"])

        # Weekly limit
        rwk_row = ctk.CTkFrame(quotas_container, fg_color="transparent")
        rwk_row.pack(fill="x", padx=8, pady=(2, 1))
        bwk_lbl = ctk.CTkLabel(
            rwk_row,
            text="📅 Неделя",
            font=self.font(size=10, weight="bold"),
            fg_color=COLOR["quota_weekly_bg"],
            text_color=COLOR["quota_weekly"][1],
            corner_radius=4,
            padx=6,
            pady=1
        )
        bwk_lbl.pack(side="left")
        ctk.CTkLabel(rwk_row, text="100% (квота доступна)", font=self.font(size=11, weight="bold"), text_color=COLOR["quota_weekly"][1]).pack(side="right")

        b_wk = ctk.CTkProgressBar(quotas_container, height=4, corner_radius=2)
        b_wk.pack(fill="x", padx=8, pady=(2, 4))
        b_wk.set(1.0)
        b_wk.configure(progress_color=COLOR["quota_weekly"][1], fg_color=COLOR["bar_bg"])

        # 3. Card Footer Actions
        divider = ctk.CTkFrame(card, height=1, fg_color=COLOR["border"])
        divider.pack(fill="x", padx=14, pady=(4, 8))

        footer = ctk.CTkFrame(card, fg_color="transparent")
        footer.pack(fill="x", padx=14, pady=(0, 10))
        footer.grid_columnconfigure(0, weight=1)

        actions_pill = ctk.CTkFrame(footer, fg_color="transparent")
        actions_pill.grid(row=0, column=0, sticky="w")

        ctk.CTkButton(
            actions_pill,
            text="🩺 Тест",
            font=self.font(size=11, weight="bold"),
            fg_color=("#f6f8fa", "#21262d"),
            hover_color=("#eaeef2", "#30363d"),
            text_color=COLOR["text_primary"],
            border_width=1,
            border_color=COLOR["border"],
            width=58,
            height=28,
            corner_radius=6,
            command=lambda a=acc: self.test_claude_account_action(a),
        ).pack(side="left", padx=(0, 4))

        if not is_active:
            ctk.CTkButton(
                actions_pill,
                text="⭐ Выбрать",
                font=self.font(size=11, weight="bold"),
                fg_color=("#0969da", "#c88635"),
                hover_color=("#0550ae", "#e09a43"),
                text_color="#ffffff",
                width=76,
                height=28,
                corner_radius=6,
                command=lambda e=email: self.activate_claude_account_action(e),
            ).pack(side="left", padx=(0, 4))

        ctk.CTkButton(
            actions_pill,
            text="📋",
            font=self.font(size=13, weight="bold"),
            fg_color=("#f6f8fa", "#21262d"),
            hover_color=("#eaeef2", "#30363d"),
            text_color=COLOR["text_primary"],
            border_width=1,
            border_color=COLOR["border"],
            width=30,
            height=28,
            corner_radius=6,
            command=lambda e=email: self.copy_to_clipboard(e, "Email скопирован"),
        ).pack(side="left", padx=(0, 4))

        ctk.CTkButton(
            actions_pill,
            text="🗑",
            font=self.font(size=13, weight="bold"),
            fg_color=("#f6f8fa", "#21262d"),
            hover_color=("#ffebe9", "#3c1e1e"),
            text_color=("#cf222e", "#f85149"),
            border_width=1,
            border_color=COLOR["border"],
            width=30,
            height=28,
            corner_radius=6,
            command=lambda a=acc: self.delete_claude_account_action(a),
        ).pack(side="left")

        return card

    # =========================================================================
    # SETTINGS VIEW
    # =========================================================================
    def _add_section_header(self, parent, title, subtitle):
        header = ctk.CTkFrame(parent, fg_color="transparent")
        header.pack(fill="x", padx=8, pady=(18, 14))
        ctk.CTkLabel(
            header, text=title, font=self.font(size=25, weight="bold"),
            text_color=COLOR["text_primary"], anchor="w",
        ).pack(anchor="w")
        ctk.CTkLabel(
            header, text=subtitle, font=self.font(size=13),
            text_color=COLOR["text_secondary"], anchor="w",
        ).pack(anchor="w", pady=(3, 0))
        return header

    def create_settings_view(self):
        self.settings_frame = ctk.CTkScrollableFrame(
            self.content_area, fg_color=COLOR["bg"], corner_radius=0,
        )
        self.settings_frame.grid_columnconfigure(0, weight=1)

        self._add_section_header(
            self.settings_frame, "Настройки", "Поведение аккаунтов, подключений и интерфейса Hub",
        )

        update_card = ctk.CTkFrame(self.settings_frame, fg_color=COLOR["card_bg"], corner_radius=16, border_width=1, border_color=COLOR["border"])
        update_card.pack(fill="x", padx=8, pady=7)
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

        c1 = ctk.CTkFrame(self.settings_frame, fg_color=COLOR["card_bg"], corner_radius=16, border_width=1, border_color=COLOR["border"])
        c1.pack(fill="x", padx=8, pady=7)
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
        self.strategy_desc = ctk.CTkLabel(
            c1,
            text="",
            font=self.font(size=11),
            text_color=COLOR["accent_cyan"],
            anchor="w",
            justify="left",
            wraplength=720,
        )
        self.strategy_desc.pack(fill="x", padx=16, pady=(0, 12))
        self.update_strategy_description(current_strat)

        c2 = ctk.CTkFrame(self.settings_frame, fg_color=COLOR["card_bg"], corner_radius=16, border_width=1, border_color=COLOR["border"])
        c2.pack(fill="x", padx=8, pady=7)
        ctk.CTkLabel(c2, text="Мгновенное переключение при Rate Limit (429)", font=self.font(size=14, weight="bold"), text_color=COLOR["text_primary"]).pack(anchor="w", padx=16, pady=(12, 4))
        self.rate_limit_var = tk.BooleanVar(value=self.config_data.get("switch_on_first_rate_limit", True))
        create_cyber_switch(c2, text="Включено", variable=self.rate_limit_var, font=self.font(size=12)).pack(anchor="w", padx=16, pady=(0, 12))

        close_card = ctk.CTkFrame(self.settings_frame, fg_color=COLOR["card_bg"], corner_radius=16, border_width=1, border_color=COLOR["border"])
        close_card.pack(fill="x", padx=8, pady=7)
        ctk.CTkLabel(
            close_card,
            text="Поведение при нажатии на крестик",
            font=self.font(size=14, weight="bold"),
            text_color=COLOR["text_primary"],
        ).pack(anchor="w", padx=16, pady=(12, 4))
        self.close_choice_remember_var = tk.BooleanVar(
            value=self.config_data.get("close_choice_remembered", False)
        )
        create_cyber_switch(
            close_card,
            text="Запоминать выбранное действие (свернуть в трей / закрыть приложение)",
            variable=self.close_choice_remember_var,
            command=self.on_close_choice_remember_changed,
            font=self.font(size=12),
        ).pack(anchor="w", padx=16, pady=(0, 12))

        # 3. Network & DNS Section Link Card
        c_net = ctk.CTkFrame(self.settings_frame, fg_color=COLOR["card_bg"], corner_radius=16, border_width=1, border_color=COLOR["border"])
        c_net.pack(fill="x", padx=8, pady=7)
        ctk.CTkLabel(c_net, text="🌐 Сеть, DNS и VLESS-маршрутизация", font=self.font(size=14, weight="bold"), text_color=COLOR["text_primary"]).pack(anchor="w", padx=16, pady=(12, 4))
        ctk.CTkLabel(
            c_net,
            text="Управление VLESS-туннелями (Reality / TLS), маршрутизацией всего трафика OpenCode и кастомными DNS (DoH / DoT / Обычный DNS) вынесено в отдельный раздел меню.\n"
                 "Обратите внимание: при выборе метода туннелирования через VLESS настройки DNS утрачивают свою силу.",
            font=self.font(size=11),
            text_color=COLOR["text_secondary"],
            anchor="w",
            justify="left",
            wraplength=720,
        ).pack(fill="x", padx=16, pady=(0, 10))
        ctk.CTkButton(
            c_net,
            text="Перейти в раздел «Сеть, DNS & VLESS» →",
            font=self.font(size=12, weight="bold"),
            fg_color=("#0969da", "#c88635"),
            hover_color=("#0550ae", "#e09a43"),
            corner_radius=6,
            height=34,
            command=lambda: self.switch_nav("network")
        ).pack(anchor="w", padx=16, pady=(0, 12))

        # 4. Providers Visibility Card
        p_card = ctk.CTkFrame(self.settings_frame, fg_color=COLOR["card_bg"], corner_radius=16, border_width=1, border_color=COLOR["border"])
        p_card.pack(fill="x", padx=8, pady=7)
        ctk.CTkLabel(p_card, text="🧩 Провайдеры моделей в боковом меню", font=self.font(size=14, weight="bold"), text_color=COLOR["text_primary"]).pack(anchor="w", padx=16, pady=(12, 4))
        ctk.CTkLabel(
            p_card,
            text="Включение и скрытие провайдеров, которые можно подключить через Antigravity Hub. Отключенные провайдеры скрываются из бокового меню Hub.",
            font=self.font(size=11),
            text_color=COLOR["text_secondary"],
            anchor="w",
            justify="left",
            wraplength=720,
        ).pack(fill="x", padx=16, pady=(0, 10))

        vis = self.config_data.get("providers_visibility", {})
        self.provider_visibility_vars = {}
        for key, label, _, desc in AVAILABLE_PROVIDERS:
            is_checked = vis.get(key, (key != "deepseek"))
            var = tk.BooleanVar(value=is_checked)
            self.provider_visibility_vars[key] = var

            row = ctk.CTkFrame(p_card, fg_color="transparent")
            row.pack(fill="x", padx=16, pady=(3, 6))
            row.grid_columnconfigure(1, weight=1)

            sw = create_cyber_switch(
                row,
                text=label,
                variable=var,
                command=lambda k=key, v=var: self.on_toggle_provider_visibility(k, v),
                font=self.font(size=12, weight="bold")
            )
            sw.grid(row=0, column=0, sticky="w")

            ctk.CTkLabel(
                row,
                text=f"— {desc}",
                font=self.font(size=11),
                text_color=COLOR["text_secondary"],
                anchor="w",
                justify="left",
                wraplength=620,
            ).grid(row=0, column=1, sticky="w", padx=(10, 0))

        ctk.CTkButton(
            self.settings_frame,
            text="💾 Сохранить настройки",
            font=self.font(size=13, weight="bold"),
            fg_color="#a96e2c",
            hover_color="#c88635",
            corner_radius=12,
            height=42,
            command=self.save_settings_action,
        ).pack(anchor="w", padx=8, pady=(10, 20))

    def on_toggle_provider_visibility(self, key, var):
        if "providers_visibility" not in self.config_data:
            self.config_data["providers_visibility"] = {}
        self.config_data["providers_visibility"][key] = var.get()
        self.save_config()
        self.rebuild_sidebar_nav()

    def on_strategy_change(self, val):
        self.update_strategy_description(val)

    def update_strategy_description(self, strat):
        descs = {
            "hybrid": "⭐ Рекомендуется: сохраняет контекст сессии на одном аккаунте, но плавно ротирует при исчерпании лимитов.",
            "sticky": "📌 Последовательная: работает с одним аккаунтом до полного отказа, затем переходит к следующему.",
            "round-robin": "🔄 Равномерная: распределяет каждый новый запрос по очереди между всеми аккаунтами.",
        }
        self.strategy_desc.configure(text=descs.get(strat, ""))

    def on_close_choice_remember_changed(self):
        enabled = self.close_choice_remember_var.get()
        self.config_data["close_choice_remembered"] = enabled
        if not enabled:
            self.config_data.pop("close_choice", None)
        self.save_config()

    def save_settings_action(self):
        self.config_data["account_selection_strategy"] = self.strategy_var.get()
        self.config_data["switch_on_first_rate_limit"] = self.rate_limit_var.get()

        ok, msg = self.save_config()
        if ok:
            messagebox.showinfo("Успешно", "Настройки сохранены!")
        else:
            messagebox.showerror("Ошибка", msg)

    # =========================================================================
    # SYSTEM VIEW
    # =========================================================================
    def create_system_view(self):
        self.system_frame = ctk.CTkScrollableFrame(
            self.content_area, fg_color=COLOR["bg"], corner_radius=0,
        )
        self.system_frame.grid_columnconfigure(0, weight=1)

        self._add_section_header(
            self.system_frame, "Система", "Управление OpenCode и диагностика локальной установки",
        )

        c1 = ctk.CTkFrame(self.system_frame, fg_color=COLOR["card_bg"], corner_radius=16, border_width=1, border_color=COLOR["border"])
        c1.pack(fill="x", padx=8, pady=7)
        ctk.CTkLabel(c1, text="Управление OpenCode", font=self.font(size=14, weight="bold"), text_color=COLOR["text_primary"]).pack(anchor="w", padx=16, pady=(12, 6))

        row = ctk.CTkFrame(c1, fg_color="transparent")
        row.pack(fill="x", padx=16, pady=(0, 14))

        ctk.CTkButton(row, text="🔄 Перезапустить", fg_color="#2563eb", command=self.restart_opencode_action).pack(side="left", padx=(0, 8))
        ctk.CTkButton(row, text="⏹ Остановить", fg_color="#ef4444", command=self.stop_opencode_action).pack(side="left", padx=(0, 8))
        ctk.CTkButton(row, text="▶ Запустить", fg_color="#10b981", command=self.start_opencode_action).pack(side="left")

        c2 = ctk.CTkFrame(self.system_frame, fg_color=COLOR["card_bg"], corner_radius=16, border_width=1, border_color=COLOR["border"])
        c2.pack(fill="x", padx=8, pady=7)
        ctk.CTkLabel(c2, text="Быстрый доступ к папкам", font=self.font(size=14, weight="bold"), text_color=COLOR["text_primary"]).pack(anchor="w", padx=16, pady=(12, 6))

        r2 = ctk.CTkFrame(c2, fg_color="transparent")
        r2.pack(fill="x", padx=16, pady=(0, 14))
        ctk.CTkButton(r2, text="📂 Конфиги (~/.config/opencode)", fg_color=COLOR["subbox_bg"], text_color=COLOR["text_primary"], command=lambda: os.startfile(CONFIG_DIR) if CONFIG_DIR.exists() else None).pack(side="left", padx=(0, 8))
        ctk.CTkButton(r2, text="📂 Логи", fg_color=COLOR["subbox_bg"], text_color=COLOR["text_primary"], command=lambda: os.startfile(LOG_DIR) if LOG_DIR.exists() else None).pack(side="left")

        # OpenCode Session Title Model Card
        c_title = ctk.CTkFrame(self.system_frame, fg_color=COLOR["card_bg"], corner_radius=16, border_width=1, border_color=COLOR["border"])
        c_title.pack(fill="x", padx=8, pady=7)
        ctk.CTkLabel(c_title, text="Подпись сессий OpenCode", font=self.font(size=14, weight="bold"), text_color=COLOR["text_primary"]).pack(anchor="w", padx=16, pady=(12, 4))
        ctk.CTkLabel(
            c_title,
            text="Именование новых сессий закреплено за бесплатной встроенной моделью Big Pickle (opencode/big-pickle).\n"
                 "Хаб автоматически проверяет и поддерживает эту настройку при запуске, обновлениях и перезапуске OpenCode, исключая расход лимитов основных моделей.",
            font=self.font(size=11),
            text_color=COLOR["text_secondary"],
            anchor="w",
            justify="left",
            wraplength=720,
        ).pack(fill="x", padx=16, pady=(0, 8))

        row_title = ctk.CTkFrame(c_title, fg_color="transparent")
        row_title.pack(fill="x", padx=16, pady=(0, 14))

        self.lbl_title_model_status = ctk.CTkLabel(
            row_title,
            text="Проверка...",
            font=self.font(size=12, weight="bold"),
            text_color=COLOR["text_primary"],
        )
        self.lbl_title_model_status.pack(side="left", padx=(0, 12))

        ctk.CTkButton(
            row_title,
            text="🩺 Проверить и исправить",
            font=self.font(size=11, weight="bold"),
            fg_color=("#0969da", "#c88635"),
            hover_color=("#0550ae", "#e09a43"),
            height=30,
            command=self.manual_fix_session_title_action,
        ).pack(side="left")

        self.update_session_title_status()

    def update_session_title_status(self):
        try:
            valid, msg = opencode_config.check_session_title_config()
            if hasattr(self, "lbl_title_model_status"):
                if valid:
                    self.lbl_title_model_status.configure(
                        text="✅ Активна: opencode/big-pickle",
                        text_color="#16a34a",
                    )
                else:
                    self.lbl_title_model_status.configure(
                        text="⚠️ Требуется исправление",
                        text_color="#d97706",
                    )
        except Exception:
            pass

    def manual_fix_session_title_action(self):
        try:
            modified, msg = opencode_config.ensure_session_title_config()
            self.update_session_title_status()
            messagebox.showinfo("Подпись сессий OpenCode", msg)
        except Exception as e:
            messagebox.showerror("Ошибка", str(e))

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
            text_color=COLOR["accent_cyan"],
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

            if self.countdown_seconds % 3 == 0:
                self.update_opencode_status()

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
                    run_silent_cmd([node_exe, cli_js, "quota", "--refresh", "--json"], timeout=25,
                                   env=provider_route_environment())
                try:
                    openai_manager.refresh_all_openai_accounts()
                except Exception:
                    pass
                try:
                    claude_service.refresh_claude_sessions_silent()
                except Exception:
                    pass
                try:
                    opencode_config.ensure_session_title_config()
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
        openai_accounts = []
        claude_accounts = []
        rotate_msg = None
        try:
            node_exe = get_node_executable()
            cli_js = get_cli_js()
            if os.path.exists(node_exe) and os.path.exists(cli_js):
                cmd = [node_exe, cli_js, "quota", "--refresh", "--json"]
                result = run_silent_cmd(cmd, timeout=20, env=provider_route_environment())
                if result.returncode == 0 and result.stdout.strip():
                    try:
                        data = json.loads(result.stdout)
                        google_accounts = data.get("accounts", [])
                    except Exception:
                        pass
                if not google_accounts:
                    cmd = [node_exe, cli_js, "quota", "--json"]
                    result = run_silent_cmd(cmd, timeout=10, env=provider_route_environment())
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

        try:
            openai_accounts, rotate_msg = openai_manager.refresh_all_openai_accounts()
        except Exception as e:
            print(f"Error fetching OpenAI quotas: {e}")
            try:
                openai_accounts = openai_manager.load_openai_accounts()
            except Exception:
                openai_accounts = []

        try:
            claude_accounts = claude_service.load_accounts()
        except Exception as e:
            print(f"Error fetching Claude accounts: {e}")

        try:
            xpiki_manager.refresh_xpiki_quota_silent()
        except Exception as e:
            print(f"Error refreshing Xpiki quota: {e}")

        try:
            opencode_config.ensure_session_title_config()
            self.after(0, self.update_session_title_status)
        except Exception as e:
            print(f"Error checking session title config: {e}")

        try:
            self.after(0, lambda: self._on_quotas_fetched(google_accounts, openai_accounts, claude_accounts, rotate_msg))
        except Exception as e:
            print(f"Callback dispatch error: {e}")
            self.is_loading = False

    def _on_quotas_fetched(self, google_accounts, openai_accounts, claude_accounts=None, rotate_msg=None):
        try:
            if google_accounts:
                self.accounts_data = google_accounts
            if openai_accounts is not None:
                self.openai_accounts_data = openai_accounts
            if claude_accounts is not None:
                self.claude_accounts_data = claude_accounts
            else:
                self.claude_accounts_data = claude_service.load_accounts()
            self.render_accounts()
        except Exception as e:
            print(f"Render accounts error: {e}")
        finally:
            self.is_loading = False
            self.btn_refresh.configure(state="normal", text="🔄 Квоты")
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
                repair_error = repair_legacy_google_account_file()
                if repair_error:
                    raise RuntimeError(repair_error)
                node_exe = get_node_executable()
                cli_js = get_cli_js()
                cmd = [node_exe, cli_js, "login"]
                proc = run_silent_cmd(cmd, timeout=300)
                success = proc.returncode == 0
                output = proc.stdout + proc.stderr
                if success:
                    repair_error = repair_legacy_google_account_file()
                    if repair_error:
                        success = False
                        output += "\nНе удалось подготовить файл аккаунтов к миграции:\n" + repair_error
                    else:
                        migration = run_silent_cmd([node_exe, cli_js, "migrate", "--offline", "--yes"], timeout=30)
                        if migration.returncode != 0:
                            success = False
                            output += "\nМиграция аккаунта не завершилась:\n" + (migration.stderr or migration.stdout or "Неизвестная ошибка")
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

    def add_claude_account_action(self):
        dialog = ctk.CTkToplevel(self)
        dialog.title("Подключение аккаунта Claude (Anthropic Pro / Claude Code)")
        dialog.geometry("620x640")
        dialog.resizable(False, False)
        dialog.transient(self)
        dialog.grab_set()

        ctk.CTkLabel(
            dialog,
            text="🟠 Авторизация Claude Pro / Team / Claude Code",
            font=self.font(size=16, weight="bold"),
            text_color=COLOR["text_primary"],
        ).pack(anchor="w", padx=20, pady=(16, 4))

        # Important Security & Tunnel Warning Box
        warn_box = ctk.CTkFrame(
            dialog,
            fg_color=COLOR["subbox_bg"],
            corner_radius=8,
            border_width=1,
            border_color="#d29922",
        )
        warn_box.pack(fill="x", padx=20, pady=(0, 10))
        ctk.CTkLabel(
            warn_box,
            text=(
                "⚠️ Важное предупреждение о блокировках Claude:\n"
                "Сервис claude.ai заблокирован в РФ. Авторизация в браузере должна производиться строго с того же IP / VPN-туннеля, через который OpenCode будет отправлять запросы, иначе Anthropic может заблокировать аккаунт при смене гео-локации!"
            ),
            font=self.font(size=10),
            text_color="#d29922",
            justify="left",
            wraplength=570,
        ).pack(fill="x", padx=12, pady=8)

        # 1-Click Browser Options Container
        opts_box = ctk.CTkFrame(dialog, fg_color="transparent")
        opts_box.pack(fill="x", padx=20, pady=(0, 10))

        def _do_login(mode: str):
            if mode == "tunnel":
                if not vless_service.is_running():
                    if not messagebox.askyesno(
                        "VLESS-туннель не запущен",
                        "VLESS-туннель сейчас остановлен!\n\n"
                        "Для безопасной авторизации Claude рекомендуется сначала запустить VLESS в разделе «Сеть, DNS & VLESS».\n\n"
                        "Продолжить вход с текущим подключением (или системным VPN)?",
                        icon="warning"
                    ):
                        return
            elif mode == "default":
                if not messagebox.askyesno(
                    "Проверка VPN / Прокси",
                    "Вы выбрали авторизацию через системный браузер.\n\n"
                    "Убедитесь, что в вашем браузере или системе включен VPN / прокси той страны, с которой вы будете работать в OpenCode.\n\n"
                    "Открыть системный браузер для входа?",
                    icon="info"
                ):
                    return

            btn_tunnel_auth.configure(state="disabled")
            btn_default_auth.configure(state="disabled")
            btn_submit.configure(state="disabled")
            lbl_status.configure(text="Запуск браузера... Выполните вход на claude.ai", text_color=COLOR["accent_cyan"])

            def _prog(msg):
                dialog.after(0, lambda m=msg: lbl_status.configure(text=m, text_color=COLOR["accent_cyan"]))

            def _worker():
                ok, msg, acc = claude_service.login_claude_browser(mode=mode, timeout=300, progress_callback=_prog)
                def _done():
                    btn_tunnel_auth.configure(state="normal")
                    btn_default_auth.configure(state="normal")
                    btn_submit.configure(state="normal")
                    if ok and acc:
                        key_entry.delete(0, "end")
                        key_entry.insert(0, acc.get("session_key", ""))
                        lbl_status.configure(text=f"✔ {msg}", text_color="#3fb950")
                        self.claude_accounts_data = claude_service.load_accounts()
                        self.show_flash(f"Аккаунт Claude {acc.get('email')} успешно подключен!")
                        self.render_accounts()
                        self.after(1400, lambda: [dialog.grab_release(), dialog.destroy()])
                    else:
                        lbl_status.configure(text=f"❌ {msg}", text_color="#ef4444")
                dialog.after(0, _done)

            threading.Thread(target=_worker, daemon=True).start()

        # Two Main 1-Click Buttons
        row1 = ctk.CTkFrame(opts_box, fg_color="transparent")
        row1.pack(fill="x", pady=(0, 6))

        btn_tunnel_auth = ctk.CTkButton(
            row1,
            text="🛡️ Вход через VLESS-туннель (Встроенный браузер)",
            font=self.font(size=11, weight="bold"),
            fg_color="#a96e2c",
            hover_color="#c88635",
            height=34,
            command=lambda: _do_login("tunnel"),
        )
        btn_tunnel_auth.pack(side="left", fill="x", expand=True, padx=(0, 6))

        btn_default_auth = ctk.CTkButton(
            row1,
            text="🌐 Вход через дефолтный браузер (VPN / Прокси)",
            font=self.font(size=11, weight="bold"),
            fg_color=("#0969da", "#c88635"),
            hover_color=("#0550ae", "#e09a43"),
            height=34,
            command=lambda: _do_login("default"),
        )
        btn_default_auth.pack(side="left", fill="x", expand=True)

        # Secondary Actions Row (CLI & Manual URL open)
        row2 = ctk.CTkFrame(opts_box, fg_color="transparent")
        row2.pack(fill="x")

        def _launch_claude_code():
            try:
                subprocess.Popen(
                    ["cmd.exe", "/c", "start", "Claude Code Auth", "cmd.exe", "/k", "npx --yes @anthropic-ai/claude-code setup-token"]
                )
            except Exception as err:
                messagebox.showerror("Ошибка запуска", f"Не удалось запустить Claude Code CLI: {err}")

        btn_cli_auth = ctk.CTkButton(
            row2,
            text="⚡ Claude Code CLI (setup-token)",
            font=self.font(size=11),
            fg_color=COLOR["subbox_bg"],
            hover_color=("#eaeef2", "#21262d"),
            text_color=COLOR["text_primary"],
            border_width=1,
            border_color=COLOR["border"],
            height=30,
            command=_launch_claude_code,
        )
        btn_cli_auth.pack(side="left", fill="x", expand=True, padx=(0, 6))

        btn_open_browser = ctk.CTkButton(
            row2,
            text="🌐 Просто открыть claude.ai",
            font=self.font(size=11),
            fg_color=COLOR["subbox_bg"],
            hover_color=("#eaeef2", "#21262d"),
            text_color=COLOR["text_primary"],
            border_width=1,
            border_color=COLOR["border"],
            height=30,
            command=lambda: open_url_in_browser("https://claude.ai"),
        )
        btn_open_browser.pack(side="left", fill="x", expand=True)

        # Instructions Box
        guide_box = ctk.CTkFrame(dialog, fg_color=COLOR["subbox_bg"], corner_radius=8, border_width=1, border_color=COLOR["border"])
        guide_box.pack(fill="x", padx=20, pady=(0, 10))
        ctk.CTkLabel(
            guide_box,
            text=(
                f"• Вариант 1 (VLESS): Hub запускает встроенный браузер через ваш локальный VLESS-туннель ({DEFAULT_HTTP_PORT}), перехватывает sessionKey и настраивает фоновое авто-продление сессии.\n"
                "• Вариант 2 (Дефолтный браузер): Hub откроет ваш системный браузер (Yandex / Chrome / Edge). Убедитесь, что в системе включен VPN.\n"
                "• Вариант 3 (Claude Code CLI): Нажмите «⚡ Claude Code CLI», скопируйте выданный токен setup-token и вставьте ниже.\n"
                "• Вариант 4 (Вручную): Откройте claude.ai, скопируйте cookie 'sessionKey' (sk-ant-sid01-...) и вставьте ниже."
            ),
            font=self.font(size=10),
            text_color=COLOR["text_secondary"],
            justify="left",
            wraplength=570,
        ).pack(fill="x", padx=12, pady=8)

        ctk.CTkLabel(dialog, text="Токен Claude Code или sessionKey:", font=self.font(size=11, weight="bold"), text_color=COLOR["text_primary"]).pack(anchor="w", padx=20, pady=(2, 2))
        key_entry = ctk.CTkEntry(
            dialog,
            placeholder_text="sk-ant-sid01-... (sessionKey) или токен Claude Code",
            font=self.font(size=11),
            height=34,
            fg_color=COLOR["subbox_bg"],
            border_color=COLOR["border"],
        )
        key_entry.pack(fill="x", padx=20, pady=(0, 6))

        lbl_status = ctk.CTkLabel(dialog, text="", font=self.font(size=11), text_color="#10b981", wraplength=570, justify="left")
        lbl_status.pack(anchor="w", padx=20, pady=(0, 6))

        btn_submit = ctk.CTkButton(
            dialog,
            text="✔ Проверить и подключить аккаунт вручную",
            font=self.font(size=12, weight="bold"),
            fg_color=("#f6f8fa", "#21262d"),
            hover_color=("#eaeef2", "#30363d"),
            text_color=COLOR["text_primary"],
            border_width=1,
            border_color=COLOR["border"],
            height=36,
            corner_radius=6,
        )
        btn_submit.pack(fill="x", padx=20, pady=(4, 16))

        def _do_verify():
            key = key_entry.get().strip()
            if not key:
                lbl_status.configure(text="❌ Введите sessionKey или токен Claude Code", text_color="#ef4444")
                return

            btn_submit.configure(state="disabled", text="⏳ Проверка сессии...")
            lbl_status.configure(text="Подключение к claude.ai...", text_color=COLOR["accent_cyan"])

            def _worker():
                ok, msg, acc = claude_service.verify_and_add_account(key)
                def _done():
                    btn_submit.configure(state="normal", text="✔ Проверить и подключить аккаунт вручную")
                    if ok:
                        self.claude_accounts_data = claude_service.load_accounts()
                        self.show_flash(f"Аккаунт {acc.get('email')} успешно подключен!")
                        self.render_accounts()
                        self.after(1400, lambda: [dialog.grab_release(), dialog.destroy()])
                    else:
                        lbl_status.configure(text=f"❌ {msg}", text_color="#ef4444")
                        messagebox.showerror("Ошибка подключения", msg)
                self.after(0, _done)

            threading.Thread(target=_worker, daemon=True).start()

        btn_submit.configure(command=_do_verify)

    def activate_claude_account_action(self, email):
        if claude_service.set_active_account(email):
            self.claude_accounts_data = claude_service.load_accounts()
            self.show_flash(f"Активный аккаунт Claude: {email}")
            self.render_accounts()
        else:
            messagebox.showerror("Ошибка", "Не удалось активировать аккаунт Claude.")

    def delete_claude_account_action(self, acc):
        email = acc.get("email", "unknown")
        if not messagebox.askyesno("Удаление", f"Удалить аккаунт Claude {email} из пула?"):
            return
        if claude_service.delete_account(email):
            self.claude_accounts_data = claude_service.load_accounts()
            self.show_flash(f"Аккаунт {email} удален")
            self.render_accounts()

    def test_claude_account_action(self, acc):
        email = acc.get("email", "unknown")
        self.set_status(f"🩺 Проверка аккаунта Claude {email}...")

        def _worker():
            start = time.time()
            ok, msg, _ = claude_service.verify_and_add_account(acc.get("session_key", ""))
            latency = int((time.time() - start) * 1000)

            def _done():
                self.set_status("Готово")
                if ok:
                    messagebox.showinfo(
                        "Проверка Claude",
                        f"Аккаунт: {email}\n\n• Статус: ✅ Активен ({acc.get('plan', 'pro').upper()})\n• Пинг: 🟢 {latency} мс\n• Модели: Claude 3.7 Sonnet, Thinking, Opus"
                    )
                else:
                    messagebox.showerror(
                        "Проверка Claude",
                        f"Аккаунт: {email}\n\n• Ошибка: ❌ {msg}\nСессия могла истечь. Обновите sessionKey."
                    )
            self.after(0, _done)

        threading.Thread(target=_worker, daemon=True).start()

    def test_google_account_action(self, acc):
        email = acc.get("email", "unknown")
        self.set_status(f"🩺 Проверка {email}...")

        def _do_test():
            def reload_account():
                exported = export_google_accounts()
                return next((a for a in exported if a.get("email") == email), None)

            def refresh_account(_account):
                return refresh_google_health_account(
                    _account, run_google_route_cmd, get_node_executable(), get_cli_js(),
                )

            target_dict = reload_account() or acc
            res = health_checker.test_google_account_health(target_dict, refresh_account=refresh_account)
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

            if imp_g or imp_o:
                messagebox.showinfo("Импорт завершен", f"Импортировано:\n• Google: {imp_g}\n• OpenAI: {imp_o}")
            else:
                has_generation_store = any(Path(os.path.expanduser("~/.config/opencode")).glob("*.generation"))
                google_detail = (
                    "В этом профиле уже создано новое хранилище Antigravity, а плагин не поддерживает прямой импорт refresh token в него. "
                    "Для каждого Google-аккаунта используйте «Добавить Google» и войдите через браузер."
                    if g_list and has_generation_store else
                    "Проверьте формат резервной копии и сообщение об ошибке в консоли Hub."
                )
                messagebox.showwarning(
                    "Импорт не выполнен",
                    "Ни один аккаунт не был импортирован. " + google_detail,
                )
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
                            text="◉ OpenCode: Фоновый сервис",
                            text_color="#d97706",
                            fg_color=("#fef3c7", "#78350f"),
                        )
                    elif desktop_running:
                        self.opencode_badge.configure(
                            text="◉ OpenCode: Запущен в фоне",
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

    def check_provider_routing_risk(self) -> bool:
        """Require explicit confirmation before launching without a working VLESS tunnel."""
        tunnel_alive = vless_service.is_running()
        if tunnel_alive:
            probe = vless_service.test_connection(timeout=3)
            tunnel_alive = probe.get("ok", False)

        if tunnel_alive:
            return True

        routes = self.config_data.get("provider_routes", {})
        if not isinstance(routes, dict):
            routes = {}
        route_names = {
            "vless": "VLESS",
            "dns": "DNS-прокси Hub",
            "proxy": "внешний прокси",
            "direct": "напрямую",
            "google-smart": "Google SmartDNS",
        }
        openai_route = route_names.get(routes.get("openai", "direct"), "напрямую")
        google_route = route_names.get(routes.get("google", "direct"), "напрямую")
        active_claude = claude_service.get_active_account()
        claude_note = (
            f"\nПодключённый аккаунт Claude: {active_claude.get('email', '')}."
            if active_claude else ""
        )
        answer = messagebox.askyesno(
            "⚠️ Запуск OpenCode без VLESS",
            "VLESS-туннель сейчас отключён или недоступен. Перед запуском проверьте индивидуальные маршруты провайдеров:\n\n"
            f"• OpenAI: {openai_route}\n"
            f"• Google Cloud Code / Antigravity: {google_route}\n\n"
            "Подмена DNS не заменяет VPN или прокси: OpenAI и Google Cloud Code могут не работать "
            "через DNS-маршрут. Неверная маршрутизация может раскрыть реальный IP, привести к отказам "
            "в доступе или ограничениям/блокировке аккаунта."
            f"{claude_note}\n\n"
            "Продолжая, вы подтверждаете, что проверили настройки и принимаете риск. "
            "Автор приложения не несёт ответственности за последствия неверной маршрутизации, "
            "отказы сервисов или ограничения аккаунтов.\n\n"
            "Запустить OpenCode без VLESS?",
            icon="warning",
            default="no",
        )
        return answer

    def sync_opencode_routes_from_config(self):
        """Apply saved Hub routes to opencode.json without touching NetworkView widgets."""
        try:
            opencode_cfg_path = Path.home() / ".config" / "opencode" / "opencode.json"
            if not opencode_cfg_path.exists():
                return
            oc_data = json.loads(opencode_cfg_path.read_text(encoding="utf-8"))
            from proxy_config import sync_provider_routes
            sync_provider_routes(oc_data, self.config_data, get_http_port(),
                                 self.config_data.get("provider_routes", {}))
            opencode_cfg_path.write_text(
                json.dumps(oc_data, indent=4, ensure_ascii=False),
                encoding="utf-8",
            )
            return True
        except Exception as e:
            print(f"Warning: Failed to sync routes to opencode.json: {e}")
            return False

    def prepare_opencode_launch_env(self):
        launch_env = os.environ.copy()
        vless_enabled = self.config_data.get("vless_enabled", False)
        vless_url = (self.config_data.get("vless_url") or "").strip()
        http_port = get_http_port()
        if not self.sync_opencode_routes_from_config():
            raise RuntimeError("Не удалось сохранить маршруты провайдеров в opencode.json")
        try:
            from cloudcode_route_patch import patch_auth_plugin_transport
            if not patch_auth_plugin_transport():
                raise RuntimeError("Не найден auth-плагин OpenCode для настройки маршрута Cloud Code")
        except Exception as e:
            raise RuntimeError(f"Не удалось настроить Cloud Code через Hub: {e}") from e
        # Start the VLESS core when enabled; provider_proxy routes only selected
        # provider hosts through it and sends other hosts via their own route.
        if vless_enabled and vless_url and not vless_service.is_running():
            custom_core = self.config_data.get("vless_core_path")
            vless_service.start_tunnel(vless_url, custom_core_path=custom_core)

        try:
            import provider_proxy
            router_ready = provider_proxy.start()
        except Exception as e:
            router_error = f"Provider route proxy failed to start: {e}"
            print(router_error)
            router_ready = False

        if not router_ready:
            # Do not launch OpenCode with a global proxy: that silently bypasses
            # per-provider routing and can send Cloud Code through the wrong route.
            raise RuntimeError(router_error if 'router_error' in locals() else
                               "Provider route proxy is unavailable on 127.0.0.1:10880")

        route_proxy = f"http://127.0.0.1:{provider_proxy.PORT}"
        for var in ("HTTPS_PROXY", "HTTP_PROXY", "ALL_PROXY", "https_proxy", "http_proxy", "all_proxy"):
            launch_env[var] = route_proxy
        launch_env["NO_PROXY"] = "localhost,127.0.0.1,::1"
        launch_env["no_proxy"] = launch_env["NO_PROXY"]

        return launch_env

    def restart_opencode_action(self):
        if not self.check_provider_routing_risk():
            self.set_status("⚠️ Запуск OpenCode отменён: VLESS отключён")
            return

        # Гарантируем корректность бесплатной модели подписи сессий перед запуском
        try:
            opencode_config.ensure_session_title_config()
        except Exception:
            pass

        self.set_status("Перезапуск OpenCode...")

        def _do_restart():
            run_silent_cmd(["taskkill", "/f", "/im", "OpenCode.exe"], timeout=5)
            run_silent_cmd(["taskkill", "/f", "/im", "opencode-cli.exe"], timeout=5)
            time.sleep(1)
            cleanup_opencode_locks()
            time.sleep(1)
            exe = get_opencode_exe()
            if os.path.exists(exe):
                try:
                    launch_env = self.prepare_opencode_launch_env()
                    subprocess.Popen([exe], cwd=os.path.dirname(exe), env=launch_env)
                except Exception as e:
                    message = f"Запуск OpenCode отменён: {e}"
                    print(message)
                    self.after(0, lambda: self.set_status(message))
                    return
            time.sleep(2)
            self.after(0, self.update_opencode_status)
            self.after(0, lambda: self.set_status("OpenCode перезапущен!"))

        threading.Thread(target=_do_restart, daemon=True).start()

    def stop_opencode_action(self):
        run_silent_cmd(["taskkill", "/f", "/im", "OpenCode.exe"], timeout=5)
        run_silent_cmd(["taskkill", "/f", "/im", "opencode-cli.exe"], timeout=5)
        cleanup_opencode_locks()
        self.update_opencode_status()
        self.set_status("OpenCode остановлен")

    def start_opencode_action(self):
        if not self.check_provider_routing_risk():
            self.set_status("⚠️ Запуск OpenCode отменён: VLESS отключён")
            return

        # Гарантируем корректность бесплатной модели подписи сессий перед запуском
        try:
            opencode_config.ensure_session_title_config()
        except Exception:
            pass

        cleanup_opencode_locks()
        exe = get_opencode_exe()
        if os.path.exists(exe):
            try:
                launch_env = self.prepare_opencode_launch_env()
                subprocess.Popen([exe], cwd=os.path.dirname(exe), env=launch_env)
                self.set_status("OpenCode запущен")
            except Exception as e:
                messagebox.showerror("Ошибка запуска OpenCode", str(e), parent=self)
        self.after(2000, self.update_opencode_status)


if __name__ == "__main__":
    if not acquire_single_instance():
        sys.exit(0)
    set_windows_taskbar_identity()
    try:
        # Reuse this module when the WebView backend imports its helpers.
        sys.modules["antigravity_manager"] = sys.modules[__name__]
        import webview_backend
        webview_backend.run_webview_app()
    except Exception as exc:
        print(f"WebView2 UI initialization failed, falling back to CustomTkinter: {exc}")
        app = AntigravityManagerApp()
        app.mainloop()
