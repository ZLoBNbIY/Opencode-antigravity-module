"""
Antigravity Hub - Native Desktop Manager for Google Antigravity Accounts & Quotas
"""

import os
import sys
import json
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
    npm_dir = Path.home() / ".cache" / "opencode" / "npm"
    if npm_dir.exists():
        matches = list(npm_dir.glob("**/@cortexkit/opencode-antigravity-auth/dist/cli.js"))
        if matches and matches[0].exists():
            return str(matches[0])
        matches_multi = list(npm_dir.glob("**/opencode-antigravity-multi-auth/dist/cli.js"))
        if matches_multi and matches_multi[0].exists():
            return str(matches_multi[0])

    local_cli = Path(__file__).resolve().parent.parent / "plugin" / "dist" / "cli.js"
    if local_cli.exists():
        return str(local_cli)

    cache_cli = Path.home() / ".cache" / "opencode" / "packages" / "@cortexkit" / "opencode-antigravity-auth@latest" / "node_modules" / "@cortexkit" / "opencode-antigravity-auth" / "dist" / "cli.js"
    if cache_cli.exists():
        return str(cache_cli)
    return str(local_cli)

def get_opencode_exe():
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
    """Removes stale OpenCode server locks and service.json files on Windows to prevent EPERM collisions."""
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

DEFAULT_CONFIG = {
    "$schema": "https://raw.githubusercontent.com/cortexkit/opencode-antigravity-auth/main/schema.json",
    "account_selection_strategy": "hybrid",
    "soft_quota_threshold_percent": 100,
    "switch_on_first_rate_limit": True,
    "max_account_switches": 10,
    "quota_style_fallback": True,
    "debug": False,
}

def run_silent_cmd(cmd, timeout=30):
    """Executes external commands completely silently without spawning console windows."""
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
        )
        stdout_str = proc.stdout.decode("utf-8", errors="replace") if proc.stdout else ""
        stderr_str = proc.stderr.decode("utf-8", errors="replace") if proc.stderr else ""
    except Exception as e:
        stdout_str = ""
        stderr_str = str(e)
        return type("SilentResult", (), {"returncode": 1, "stdout": "", "stderr": stderr_str})()

    return type("SilentResult", (), {"returncode": proc.returncode, "stdout": stdout_str, "stderr": stderr_str})()

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
                print(f"Error reading generation accounts for export: {e}")

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

                # Find matching account ID
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
                print(f"Error deleting account from generation store: {e}")

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


def get_google_account_emails() -> list[str]:
    config_dir = Path(os.path.expanduser("~/.config/opencode"))
    gen_dirs = list(config_dir.glob("*.generation"))
    emails = []
    if gen_dirs:
        cfg_file = gen_dirs[0] / "config.json"
        state_file = gen_dirs[0] / "state.json"
        if cfg_file.exists() and state_file.exists():
            try:
                cfg = json.loads(cfg_file.read_text(encoding="utf-8"))
                state = json.loads(state_file.read_text(encoding="utf-8"))
                for acc in cfg.get("accounts", []):
                    aid = acc.get("id")
                    meta = state.get("accounts", {}).get(aid, {}).get("commonAuthProviderState", {}).get("metadata", {})
                    email = meta.get("email")
                    if email:
                        emails.append(email)
            except Exception:
                pass
    return emails


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

    # If generation directories exist, directly update/insert into generation store
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

                # Update migration.json manifest if present
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

                # Ensure legacy file is absent so cli.js does not report "legacy source recreated"
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
        # Fresh PC with no generation store yet: write legacy file and run migration
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

ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")


class AntigravityManagerApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("Antigravity Hub — Google & ChatGPT Менеджер аккаунтов")
        self.geometry("980x740")
        self.minsize(860, 640)

        icon_file = Path(__file__).resolve().parent / "icon.ico"
        if icon_file.exists():
            try:
                self.iconbitmap(str(icon_file))
            except Exception:
                pass

        # State
        self.accounts_data = []
        self.openai_accounts_data = []
        self.current_provider_view = "google"
        self.is_loading = False
        self.config_data = self.load_config()

        # Periodic auto-refresh (every 10 minutes)
        self.auto_refresh_enabled = True
        self.auto_refresh_interval_min = 10
        self.countdown_seconds = self.auto_refresh_interval_min * 60

        # Grid setup
        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=1)

        self.create_header()
        self.create_tabs()
        self.create_statusbar()

        # Initial background load
        self.refresh_all_async()
        self.update_opencode_status()
        self.start_countdown_timer()

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

    # --- UI Components ---
    def create_header(self):
        header_frame = ctk.CTkFrame(self, corner_radius=0, fg_color="#18181b")
        header_frame.grid(row=0, column=0, sticky="ew", padx=0, pady=0)
        header_frame.grid_columnconfigure(1, weight=1)

        # Title & Logo
        title_box = ctk.CTkFrame(header_frame, fg_color="transparent")
        title_box.grid(row=0, column=0, padx=20, pady=14, sticky="w")

        title_label = ctk.CTkLabel(
            title_box,
            text="⚡ Antigravity Hub",
            font=ctk.CTkFont(size=22, weight="bold"),
            text_color="#f4f4f5",
        )
        title_label.pack(anchor="w")

        subtitle_label = ctk.CTkLabel(
            title_box,
            text="Мульти-аккаунты Google и OpenAI / ChatGPT, живые квоты и управление для OpenCode",
            font=ctk.CTkFont(size=12),
            text_color="#a1a1aa",
        )
        subtitle_label.pack(anchor="w")

        # OpenCode status and actions
        status_box = ctk.CTkFrame(header_frame, fg_color="transparent")
        status_box.grid(row=0, column=2, padx=20, pady=14, sticky="e")

        self.opencode_badge = ctk.CTkLabel(
            status_box,
            text="Проверка OpenCode...",
            font=ctk.CTkFont(size=12, weight="bold"),
            fg_color="#27272a",
            text_color="#d4d4d8",
            corner_radius=8,
            padx=12,
            pady=4,
        )
        self.opencode_badge.pack(side="left", padx=8)

        restart_btn = ctk.CTkButton(
            status_box,
            text="🔄 Перезапустить OpenCode",
            width=160,
            height=32,
            font=ctk.CTkFont(size=12, weight="bold"),
            fg_color="#3b82f6",
            hover_color="#2563eb",
            command=self.restart_opencode_action,
        )
        restart_btn.pack(side="left")

    def create_tabs(self):
        self.tabview = ctk.CTkTabview(self, corner_radius=12, fg_color="#18181b")
        self.tabview.grid(row=1, column=0, sticky="nsew", padx=20, pady=(10, 10))

        self.tab_accounts = self.tabview.add("👤 Аккаунты и Квоты")
        self.tab_settings = self.tabview.add("⚙️ Настройки автопереключения")
        self.tab_system = self.tabview.add("🛠 OpenCode & Диагностика")

        self.setup_tab_accounts()
        self.setup_tab_settings()
        self.setup_tab_system()

    # --- Tab 1: Accounts & Quotas ---
    def setup_tab_accounts(self):
        self.tab_accounts.grid_columnconfigure(0, weight=1)
        self.tab_accounts.grid_rowconfigure(1, weight=1)

        # Controls bar
        top_bar = ctk.CTkFrame(self.tab_accounts, fg_color="transparent")
        top_bar.grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 15))
        top_bar.grid_columnconfigure(5, weight=1)

        # Provider Selector Segmented Button
        self.provider_seg = ctk.CTkSegmentedButton(
            top_bar,
            values=["🌐 Google (Antigravity)", "🟢 OpenAI (ChatGPT)"],
            font=ctk.CTkFont(size=12, weight="bold"),
            command=self.on_provider_view_change,
        )
        self.provider_seg.set("🌐 Google (Antigravity)")
        self.provider_seg.grid(row=0, column=0, padx=(0, 10))

        self.btn_add_account = ctk.CTkButton(
            top_bar,
            text="➕ Добавить аккаунт Google",
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color="#10b981",
            hover_color="#059669",
            height=36,
            command=self.add_account_action,
        )
        self.btn_add_account.grid(row=0, column=1, padx=(0, 8))

        self.btn_refresh = ctk.CTkButton(
            top_bar,
            text="🔄 Обновить",
            font=ctk.CTkFont(size=13),
            fg_color="#3f3f46",
            hover_color="#52525b",
            height=36,
            width=110,
            command=self.refresh_all_async,
        )
        self.btn_refresh.grid(row=0, column=2, padx=(0, 8))

        self.btn_export = ctk.CTkButton(
            top_bar,
            text="📤 Экспорт",
            font=ctk.CTkFont(size=12, weight="bold"),
            fg_color="#2563eb",
            hover_color="#1d4ed8",
            height=36,
            width=95,
            command=self.export_accounts_action,
        )
        self.btn_export.grid(row=0, column=3, padx=(0, 8))

        self.btn_import = ctk.CTkButton(
            top_bar,
            text="📥 Импорт",
            font=ctk.CTkFont(size=12, weight="bold"),
            fg_color="#7c3aed",
            hover_color="#6d28d9",
            height=36,
            width=95,
            command=self.import_accounts_action,
        )
        self.btn_import.grid(row=0, column=4, padx=(0, 10))

        self.lbl_accounts_count = ctk.CTkLabel(
            top_bar,
            text="Загрузка...",
            font=ctk.CTkFont(size=13),
            text_color="#a1a1aa",
        )
        self.lbl_accounts_count.grid(row=0, column=5, sticky="e")

        # Scrollable container for account cards
        self.accounts_scroll = ctk.CTkScrollableFrame(
            self.tab_accounts,
            fg_color="#121214",
            corner_radius=10,
        )
        self.accounts_scroll.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 10))
        self.accounts_scroll.grid_columnconfigure(0, weight=1)

    def on_provider_view_change(self, val):
        if "Google" in val:
            self.current_provider_view = "google"
            self.btn_add_account.configure(
                text="➕ Добавить аккаунт Google",
                command=self.add_account_action,
                fg_color="#10b981",
                hover_color="#059669",
            )
        else:
            self.current_provider_view = "openai"
            self.btn_add_account.configure(
                text="➕ Добавить аккаунт OpenAI",
                command=self.add_openai_account_action,
                fg_color="#10a37f",
                hover_color="#0e8a6c",
            )
        self.render_accounts()

    def render_accounts(self):
        # Save scroll position if canvas exists so UI doesn't jump
        scroll_pos = 0.0
        try:
            scroll_pos = self.accounts_scroll._parent_canvas.yview()[0]
        except Exception:
            pass

        # Clear existing widgets
        for widget in self.accounts_scroll.winfo_children():
            widget.destroy()

        if self.current_provider_view == "google":
            self.render_google_accounts()
        else:
            self.render_openai_accounts()

        # Restore scroll position smoothly
        try:
            if scroll_pos > 0.0:
                self.after(30, lambda: self.accounts_scroll._parent_canvas.yview_moveto(scroll_pos))
        except Exception:
            pass

    def render_google_accounts(self):
        if not self.accounts_data:
            empty_box = ctk.CTkFrame(self.accounts_scroll, fg_color="transparent")
            empty_box.pack(pady=80)
            ctk.CTkLabel(
                empty_box,
                text="📭",
                font=ctk.CTkFont(size=48),
            ).pack()
            ctk.CTkLabel(
                empty_box,
                text="Нет подключенных Google аккаунтов",
                font=ctk.CTkFont(size=16, weight="bold"),
                text_color="#f4f4f5",
            ).pack(pady=(10, 4))
            ctk.CTkLabel(
                empty_box,
                text="Нажмите кнопку '+ Добавить аккаунт Google' вверху, чтобы авторизоваться через браузер.",
                font=ctk.CTkFont(size=13),
                text_color="#71717a",
            ).pack()
            self.lbl_accounts_count.configure(text="Google: 0 аккаунтов")
            return

        total = len(self.accounts_data)
        active_idx = get_active_google_account_index()
        active_email = ""
        if 0 <= active_idx < len(self.accounts_data):
            active_email = self.accounts_data[active_idx].get("email", "")

        if active_email:
            self.lbl_accounts_count.configure(
                text=f"Google: {total} акк. • 🟢 Текущий: #{active_idx + 1}"
            )
        else:
            self.lbl_accounts_count.configure(text=f"Google аккаунтов: {total}")

        for acc in self.accounts_data:
            self.create_account_card(acc, active_idx)

    def render_openai_accounts(self):
        if not self.openai_accounts_data:
            empty_box = ctk.CTkFrame(self.accounts_scroll, fg_color="transparent")
            empty_box.pack(pady=80)
            ctk.CTkLabel(
                empty_box,
                text="🤖",
                font=ctk.CTkFont(size=48),
            ).pack()
            ctk.CTkLabel(
                empty_box,
                text="Нет подключенных аккаунтов OpenAI (ChatGPT)",
                font=ctk.CTkFont(size=16, weight="bold"),
                text_color="#f4f4f5",
            ).pack(pady=(10, 4))
            ctk.CTkLabel(
                empty_box,
                text="Нажмите кнопку '+ Добавить аккаунт OpenAI' вверху, чтобы войти через браузер (OAuth).",
                font=ctk.CTkFont(size=13),
                text_color="#71717a",
            ).pack()
            self.lbl_accounts_count.configure(text="OpenAI: 0 аккаунтов")
            return

        total = len(self.openai_accounts_data)
        self.lbl_accounts_count.configure(text=f"OpenAI аккаунтов: {total}")

        for idx, acc in enumerate(self.openai_accounts_data, start=1):
            self.create_openai_card(acc, idx)

    def create_openai_card(self, acc, index):
        email = acc.get("email", "unknown@chatgpt.com")
        is_active = acc.get("is_active", False)
        plan_type = (acc.get("plan_type") or "plus").upper()
        account_id = acc.get("accountId") or acc.get("id") or ""
        quota = acc.get("quota") or {}

        primary_quota = quota.get("primary") or {}
        secondary_quota = quota.get("secondary") or {}

        card = ctk.CTkFrame(self.accounts_scroll, fg_color="#1e1e24", corner_radius=12)
        card.pack(fill="x", pady=8, padx=4)

        # Card Header
        header_row = ctk.CTkFrame(card, fg_color="transparent")
        header_row.pack(fill="x", padx=16, pady=(14, 10))
        header_row.grid_columnconfigure(1, weight=1)

        # Avatar / Index circle
        idx_badge = ctk.CTkLabel(
            header_row,
            text=f"#{index}",
            width=32,
            height=32,
            corner_radius=16,
            fg_color="#10a37f",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color="#ffffff",
        )
        idx_badge.grid(row=0, column=0, padx=(0, 12))

        # Email + Plan box
        info_col = ctk.CTkFrame(header_row, fg_color="transparent")
        info_col.grid(row=0, column=1, sticky="w")

        title_row = ctk.CTkFrame(info_col, fg_color="transparent")
        title_row.pack(anchor="w")

        email_label = ctk.CTkLabel(
            title_row,
            text=email,
            font=ctk.CTkFont(size=16, weight="bold"),
            text_color="#f4f4f5",
        )
        email_label.pack(side="left")

        # Plan badge
        plan_lbl = ctk.CTkLabel(
            title_row,
            text=f" {plan_type} ",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color="#38bdf8",
            fg_color="#0c4a6e",
            corner_radius=6,
            padx=6,
            pady=2,
        )
        plan_lbl.pack(side="left", padx=(8, 0))

        # Actions on right
        actions_box = ctk.CTkFrame(header_row, fg_color="transparent")
        actions_box.grid(row=0, column=2, sticky="e")

        if is_active:
            status_lbl = ctk.CTkLabel(
                actions_box,
                text="● Активен в OpenCode",
                font=ctk.CTkFont(size=12, weight="bold"),
                text_color="#10b981",
                fg_color="#064e3b",
                corner_radius=8,
                padx=10,
                pady=4,
            )
            status_lbl.pack(side="left", padx=(0, 10))
        else:
            activate_btn = ctk.CTkButton(
                actions_box,
                text="⭐ Использовать в OpenCode",
                font=ctk.CTkFont(size=11, weight="bold"),
                fg_color="#3b82f6",
                hover_color="#2563eb",
                height=28,
                width=165,
                command=lambda aid=account_id: self.activate_openai_account_action(aid),
            )
            activate_btn.pack(side="left", padx=(0, 10))

        del_btn = ctk.CTkButton(
            actions_box,
            text="🗑",
            font=ctk.CTkFont(size=13),
            fg_color="#ef4444",
            hover_color="#dc2626",
            height=28,
            width=32,
            command=lambda a=acc: self.delete_openai_account_action(a),
        )
        del_btn.pack(side="left")

        # Divider
        divider = ctk.CTkFrame(card, height=1, fg_color="#2e2e38")
        divider.pack(fill="x", padx=16, pady=4)

        # Quotas Section
        quotas_container = ctk.CTkFrame(card, fg_color="transparent")
        quotas_container.pack(fill="x", padx=16, pady=(10, 16))
        quotas_container.grid_columnconfigure(0, weight=1)
        quotas_container.grid_columnconfigure(1, weight=1)

        # 1. Primary Window Box
        self.create_openai_quota_box(
            quotas_container,
            col=0,
            title="Основное окно (3-5 часов)",
            badge_text="GPT-5.5 / GPT-6 / Codex",
            window_info=primary_quota,
        )

        # 2. Secondary Window Box
        self.create_openai_quota_box(
            quotas_container,
            col=1,
            title="Недельный лимит (7 дней)",
            badge_text="Rolling 7-day Window",
            window_info=secondary_quota,
        )

    def create_openai_quota_box(self, parent, col, title, badge_text, window_info):
        box = ctk.CTkFrame(parent, fg_color="#26262e", corner_radius=10)
        box.grid(row=0, column=col, sticky="nsew", padx=6 if col == 1 else 0, pady=2)
        box.grid_columnconfigure(0, weight=1)

        header = ctk.CTkFrame(box, fg_color="transparent")
        header.pack(fill="x", padx=12, pady=(10, 4))
        header.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            header,
            text=title,
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color="#e4e4e7",
        ).grid(row=0, column=0, sticky="w")

        ctk.CTkLabel(
            header,
            text=badge_text,
            font=ctk.CTkFont(size=10),
            text_color="#a1a1aa",
            fg_color="#1e1e24",
            corner_radius=6,
            padx=6,
            pady=2,
        ).grid(row=0, column=1, sticky="e")

        rem_pct = float(window_info.get("remaining_percent", 100.0))
        used_pct = float(window_info.get("used_percent", 0.0))
        rem_pct = round(rem_pct, 1)

        val_row = ctk.CTkFrame(box, fg_color="transparent")
        val_row.pack(fill="x", padx=12, pady=(4, 6))

        pct_color = "#10b981" if rem_pct > 50 else ("#f59e0b" if rem_pct > 20 else "#ef4444")

        ctk.CTkLabel(
            val_row,
            text=f"{rem_pct}%",
            font=ctk.CTkFont(size=20, weight="bold"),
            text_color=pct_color,
        ).pack(side="left")

        ctk.CTkLabel(
            val_row,
            text=f"доступно (расход: {used_pct}%)",
            font=ctk.CTkFont(size=12),
            text_color="#a1a1aa",
        ).pack(side="left", padx=8)

        bar = ctk.CTkProgressBar(box, height=10, corner_radius=5)
        bar.pack(fill="x", padx=12, pady=(0, 8))
        bar.set(max(0.0, min(1.0, rem_pct / 100.0)))
        bar.configure(progress_color=pct_color, fg_color="#18181b")

        reset_label = window_info.get("reset_label", "неизвестно")
        ctk.CTkLabel(
            box,
            text=f"Сброс квоты: {reset_label}",
            font=ctk.CTkFont(size=11),
            text_color="#71717a",
        ).pack(anchor="w", padx=12, pady=(0, 10))

    def create_account_card(self, acc, active_idx=0):
        email = acc.get("email", "unknown@gmail.com")
        index = acc.get("index", 1)
        status = acc.get("status", "ok")
        groups = acc.get("groups", [])

        zero_idx = int(index) - 1
        is_current = (zero_idx == active_idx)

        # Parse quotas
        gemini_group = next((g for g in groups if g.get("name") == "gemini"), None)
        nongemini_group = next((g for g in groups if g.get("name") == "non-gemini"), None)

        card = ctk.CTkFrame(
            self.accounts_scroll,
            fg_color="#1e1e24",
            corner_radius=12,
            border_width=2 if is_current else 1,
            border_color="#10b981" if is_current else "#27272a",
        )
        card.pack(fill="x", pady=8, padx=4)
        card.grid_columnconfigure(1, weight=1)

        # Card Header
        header_row = ctk.CTkFrame(card, fg_color="transparent")
        header_row.pack(fill="x", padx=16, pady=(14, 10))
        header_row.grid_columnconfigure(1, weight=1)

        # Avatar / Index circle
        idx_badge = ctk.CTkLabel(
            header_row,
            text=f"⚡ #{index}" if is_current else f"#{index}",
            width=38 if is_current else 32,
            height=32,
            corner_radius=16,
            fg_color="#10b981" if is_current else "#3b82f6",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color="#ffffff",
        )
        idx_badge.grid(row=0, column=0, padx=(0, 12))

        # Email and info
        email_label = ctk.CTkLabel(
            header_row,
            text=email,
            font=ctk.CTkFont(size=16, weight="bold"),
            text_color="#f4f4f5",
        )
        email_label.grid(row=0, column=1, sticky="w")

        # Actions and status on right
        actions_box = ctk.CTkFrame(header_row, fg_color="transparent")
        actions_box.grid(row=0, column=2, sticky="e")

        if is_current:
            status_lbl = ctk.CTkLabel(
                actions_box,
                text="🟢 Используется сейчас",
                font=ctk.CTkFont(size=12, weight="bold"),
                text_color="#10b981",
                fg_color="#064e3b",
                corner_radius=8,
                padx=10,
                pady=4,
            )
            status_lbl.pack(side="left", padx=(0, 8))
        else:
            status_lbl = ctk.CTkLabel(
                actions_box,
                text="🔄 В пуле ротации (Резерв)",
                font=ctk.CTkFont(size=12, weight="bold"),
                text_color="#38bdf8",
                fg_color="#0c4a6e",
                corner_radius=8,
                padx=10,
                pady=4,
            )
            status_lbl.pack(side="left", padx=(0, 8))

            activate_btn = ctk.CTkButton(
                actions_box,
                text="⭐ Сделать текущим",
                font=ctk.CTkFont(size=11, weight="bold"),
                fg_color="#3b82f6",
                hover_color="#2563eb",
                height=28,
                width=150,
                command=lambda aidx=zero_idx: self.activate_google_account_action(aidx),
            )
            activate_btn.pack(side="left", padx=(0, 8))

        del_btn = ctk.CTkButton(
            actions_box,
            text="🗑",
            font=ctk.CTkFont(size=13),
            fg_color="#ef4444",
            hover_color="#dc2626",
            height=28,
            width=32,
            command=lambda a=acc: self.delete_google_account_action(a),
        )
        del_btn.pack(side="left")

        # Divider
        divider = ctk.CTkFrame(card, height=1, fg_color="#2e2e38")
        divider.pack(fill="x", padx=16, pady=4)

        # Quotas Section
        quotas_container = ctk.CTkFrame(card, fg_color="transparent")
        quotas_container.pack(fill="x", padx=16, pady=(10, 16))
        quotas_container.grid_columnconfigure(0, weight=1)
        quotas_container.grid_columnconfigure(1, weight=1)

        # 1. Gemini Quota Box
        self.create_quota_box(
            quotas_container,
            col=0,
            title="Gemini Flash & Pro",
            badge_text="2.5, 3.7, 3.8",
            quota_info=gemini_group,
        )

        # 2. Non-Gemini Quota Box
        self.create_quota_box(
            quotas_container,
            col=1,
            title="Claude & Другие",
            badge_text="Sonnet 4.6, Opus 4.6",
            quota_info=nongemini_group,
        )

    def create_quota_box(self, parent, col, title, badge_text, quota_info):
        box = ctk.CTkFrame(parent, fg_color="#26262e", corner_radius=10)
        box.grid(row=0, column=col, sticky="nsew", padx=6 if col == 1 else 0, pady=2)
        box.grid_columnconfigure(0, weight=1)

        # Header of quota box
        header = ctk.CTkFrame(box, fg_color="transparent")
        header.pack(fill="x", padx=12, pady=(10, 4))
        header.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            header,
            text=title,
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color="#e4e4e7",
        ).grid(row=0, column=0, sticky="w")

        ctk.CTkLabel(
            header,
            text=badge_text,
            font=ctk.CTkFont(size=10),
            text_color="#a1a1aa",
            fg_color="#1e1e24",
            corner_radius=6,
            padx=6,
            pady=2,
        ).grid(row=0, column=1, sticky="e")

        # Quota values
        rem_pct = quota_info.get("remainingPercent", 100.0) if quota_info else 100.0
        rem_pct = round(float(rem_pct), 1)

        val_row = ctk.CTkFrame(box, fg_color="transparent")
        val_row.pack(fill="x", padx=12, pady=(4, 6))

        pct_color = "#10b981" if rem_pct > 50 else ("#f59e0b" if rem_pct > 20 else "#ef4444")

        ctk.CTkLabel(
            val_row,
            text=f"{rem_pct}%",
            font=ctk.CTkFont(size=20, weight="bold"),
            text_color=pct_color,
        ).pack(side="left")

        ctk.CTkLabel(
            val_row,
            text="квоты доступно",
            font=ctk.CTkFont(size=12),
            text_color="#a1a1aa",
        ).pack(side="left", padx=8)

        # Progress bar
        bar = ctk.CTkProgressBar(box, height=10, corner_radius=5)
        bar.pack(fill="x", padx=12, pady=(0, 8))
        bar.set(max(0.0, min(1.0, rem_pct / 100.0)))
        bar.configure(progress_color=pct_color, fg_color="#18181b")

        # Reset time info
        reset_str = quota_info.get("resetTime", "") if quota_info else ""
        reset_label_text = self.format_reset_time(reset_str)

        ctk.CTkLabel(
            box,
            text=reset_label_text,
            font=ctk.CTkFont(size=11),
            text_color="#71717a",
        ).pack(anchor="w", padx=12, pady=(0, 10))

    def format_reset_time(self, iso_str):
        if not iso_str:
            return "Сброс квоты: неизвестно"
        try:
            # ISO UTC
            dt = datetime.datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
            local_dt = dt.astimezone()
            now = datetime.datetime.now(datetime.timezone.utc).astimezone()
            diff = local_dt - now

            if diff.total_seconds() <= 0:
                return "Сброс квоты: сейчас"

            days = diff.days
            hours = int(diff.seconds // 3600)
            minutes = int((diff.seconds % 3600) // 60)

            if days > 0:
                time_str = f"через {days} дн. {hours} ч."
            elif hours > 0:
                time_str = f"через {hours} ч. {minutes} мин."
            else:
                time_str = f"через {minutes} мин."

            return f"Сброс: {time_str} ({local_dt.strftime('%d.%m %H:%M')})"
        except Exception:
            return f"Сброс: {iso_str}"

    # --- Tab 2: Auto-Switch Settings ---
    def setup_tab_settings(self):
        self.tab_settings.grid_columnconfigure(0, weight=1)

        scroll = ctk.CTkScrollableFrame(self.tab_settings, fg_color="transparent")
        scroll.pack(fill="both", expand=True, padx=10, pady=10)
        scroll.grid_columnconfigure(0, weight=1)

        # 1. Rotation Strategy
        c1 = ctk.CTkFrame(scroll, fg_color="#1e1e24", corner_radius=12)
        c1.pack(fill="x", pady=6)
        c1.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            c1,
            text="1. Стратегия выбора и ротации аккаунтов",
            font=ctk.CTkFont(size=15, weight="bold"),
            text_color="#f4f4f5",
        ).pack(anchor="w", padx=16, pady=(14, 4))

        ctk.CTkLabel(
            c1,
            text="Определяет как плагин распределяет запросы между вашими Google аккаунтами:",
            font=ctk.CTkFont(size=12),
            text_color="#a1a1aa",
        ).pack(anchor="w", padx=16, pady=(0, 10))

        current_strat = self.config_data.get("account_selection_strategy", "hybrid")
        self.strategy_var = tk.StringVar(value=current_strat)

        self.strategy_seg = ctk.CTkSegmentedButton(
            c1,
            values=["hybrid", "sticky", "round-robin"],
            variable=self.strategy_var,
            font=ctk.CTkFont(size=13, weight="bold"),
            height=34,
            command=self.on_strategy_change,
        )
        self.strategy_seg.pack(anchor="w", padx=16, pady=(0, 8))

        self.strategy_desc = ctk.CTkLabel(
            c1,
            text="",
            font=ctk.CTkFont(size=12),
            text_color="#38bdf8",
        )
        self.strategy_desc.pack(anchor="w", padx=16, pady=(0, 14))
        self.update_strategy_description(current_strat)

        # 2. Soft Quota Threshold Slider
        c2 = ctk.CTkFrame(scroll, fg_color="#1e1e24", corner_radius=12)
        c2.pack(fill="x", pady=6)

        ctk.CTkLabel(
            c2,
            text="2. Порог упреждающего переключения квоты (Soft Quota Threshold)",
            font=ctk.CTkFont(size=15, weight="bold"),
            text_color="#f4f4f5",
        ).pack(anchor="w", padx=16, pady=(14, 4))

        ctk.CTkLabel(
            c2,
            text="Автоматически переключаться на следующий аккаунт, если на текущем осталось меньше X% квоты:",
            font=ctk.CTkFont(size=12),
            text_color="#a1a1aa",
        ).pack(anchor="w", padx=16, pady=(0, 10))

        slider_row = ctk.CTkFrame(c2, fg_color="transparent")
        slider_row.pack(fill="x", padx=16, pady=(0, 8))
        slider_row.grid_columnconfigure(0, weight=1)

        init_thresh = self.config_data.get("soft_quota_threshold_percent", 90)
        self.thresh_var = tk.DoubleVar(value=init_thresh)

        self.thresh_slider = ctk.CTkSlider(
            slider_row,
            from_=5,
            to=100,
            number_of_steps=19,
            variable=self.thresh_var,
            command=self.on_thresh_slider_change,
        )
        self.thresh_slider.grid(row=0, column=0, sticky="ew", padx=(0, 16))

        self.thresh_val_label = ctk.CTkLabel(
            slider_row,
            text=f"{int(init_thresh)}%",
            font=ctk.CTkFont(size=16, weight="bold"),
            text_color="#38bdf8",
            width=50,
        )
        self.thresh_val_label.grid(row=0, column=1)

        ctk.CTkLabel(
            c2,
            text="💡 Значение 90-100% гарантирует, что запросы плавно перейдут на запасной аккаунт до получения жесткого отказа.",
            font=ctk.CTkFont(size=11),
            text_color="#71717a",
        ).pack(anchor="w", padx=16, pady=(0, 14))

        # 3. Rate Limit Switch
        c3 = ctk.CTkFrame(scroll, fg_color="#1e1e24", corner_radius=12)
        c3.pack(fill="x", pady=6)

        header_switch_row = ctk.CTkFrame(c3, fg_color="transparent")
        header_switch_row.pack(fill="x", padx=16, pady=14)
        header_switch_row.grid_columnconfigure(0, weight=1)

        info_box = ctk.CTkFrame(header_switch_row, fg_color="transparent")
        info_box.grid(row=0, column=0, sticky="w")

        ctk.CTkLabel(
            info_box,
            text="3. Мгновенное переключение при Rate Limit (429)",
            font=ctk.CTkFont(size=15, weight="bold"),
            text_color="#f4f4f5",
        ).pack(anchor="w")

        ctk.CTkLabel(
            info_box,
            text="Переключаться на следующий аккаунт сразу при первом превышении скорости запросов (RPM/TPM).",
            font=ctk.CTkFont(size=12),
            text_color="#a1a1aa",
        ).pack(anchor="w", pady=(2, 0))

        self.rate_limit_var = tk.BooleanVar(
            value=self.config_data.get("switch_on_first_rate_limit", True)
        )
        self.rate_limit_switch = ctk.CTkSwitch(
            header_switch_row,
            text="",
            variable=self.rate_limit_var,
            onvalue=True,
            offvalue=False,
        )
        self.rate_limit_switch.grid(row=0, column=1, sticky="e")

        # 4. Max Account Switches Slider
        c4 = ctk.CTkFrame(scroll, fg_color="#1e1e24", corner_radius=12)
        c4.pack(fill="x", pady=6)

        ctk.CTkLabel(
            c4,
            text="4. Максимальное число переключений на один запрос",
            font=ctk.CTkFont(size=15, weight="bold"),
            text_color="#f4f4f5",
        ).pack(anchor="w", padx=16, pady=(14, 4))

        ctk.CTkLabel(
            c4,
            text="Предотвращает бесконечные циклы переключения в случае глобальных сбоев сервиса:",
            font=ctk.CTkFont(size=12),
            text_color="#a1a1aa",
        ).pack(anchor="w", padx=16, pady=(0, 10))

        switches_row = ctk.CTkFrame(c4, fg_color="transparent")
        switches_row.pack(fill="x", padx=16, pady=(0, 8))
        switches_row.grid_columnconfigure(0, weight=1)

        init_switches = self.config_data.get("max_account_switches", 10)
        self.switches_var = tk.DoubleVar(value=init_switches)

        self.switches_slider = ctk.CTkSlider(
            switches_row,
            from_=1,
            to=20,
            number_of_steps=19,
            variable=self.switches_var,
            command=self.on_switches_slider_change,
        )
        self.switches_slider.grid(row=0, column=0, sticky="ew", padx=(0, 16))

        self.switches_val_label = ctk.CTkLabel(
            switches_row,
            text=f"{int(init_switches)} акк.",
            font=ctk.CTkFont(size=16, weight="bold"),
            text_color="#38bdf8",
            width=60,
        )
        self.switches_val_label.grid(row=0, column=1)

        # 5. Quota Style Fallback Switch
        c5 = ctk.CTkFrame(scroll, fg_color="#1e1e24", corner_radius=12)
        c5.pack(fill="x", pady=6)

        fallback_row = ctk.CTkFrame(c5, fg_color="transparent")
        fallback_row.pack(fill="x", padx=16, pady=14)
        fallback_row.grid_columnconfigure(0, weight=1)

        fb_info = ctk.CTkFrame(fallback_row, fg_color="transparent")
        fb_info.grid(row=0, column=0, sticky="w")

        ctk.CTkLabel(
            fb_info,
            text="5. Резервный протокол квот (Antigravity ↔ Gemini-CLI)",
            font=ctk.CTkFont(size=15, weight="bold"),
            text_color="#f4f4f5",
        ).pack(anchor="w")

        ctk.CTkLabel(
            fb_info,
            text="Позволяет использовать альтернативный пул квот, если основной временно недоступен.",
            font=ctk.CTkFont(size=12),
            text_color="#a1a1aa",
        ).pack(anchor="w", pady=(2, 0))

        self.fallback_var = tk.BooleanVar(
            value=self.config_data.get("quota_style_fallback", True)
        )
        self.fallback_switch = ctk.CTkSwitch(
            fallback_row,
            text="",
            variable=self.fallback_var,
            onvalue=True,
            offvalue=False,
        )
        self.fallback_switch.grid(row=0, column=1, sticky="e")

        # 6. Periodic Auto-Refresh
        c6 = ctk.CTkFrame(scroll, fg_color="#1e1e24", corner_radius=12)
        c6.pack(fill="x", pady=6)

        ar_row = ctk.CTkFrame(c6, fg_color="transparent")
        ar_row.pack(fill="x", padx=16, pady=14)
        ar_row.grid_columnconfigure(0, weight=1)

        ar_info = ctk.CTkFrame(ar_row, fg_color="transparent")
        ar_info.grid(row=0, column=0, sticky="w")

        ctk.CTkLabel(
            ar_info,
            text="6. Периодическое автообновление квот (раз в 10 минут)",
            font=ctk.CTkFont(size=15, weight="bold"),
            text_color="#f4f4f5",
        ).pack(anchor="w")

        ctk.CTkLabel(
            ar_info,
            text="Автоматически опрашивает Google API и обновляет остаток квот в фоновом режиме каждые 10 минут.",
            font=ctk.CTkFont(size=12),
            text_color="#a1a1aa",
        ).pack(anchor="w", pady=(2, 0))

        self.ar_switch_var = tk.BooleanVar(value=self.auto_refresh_enabled)
        self.ar_switch = ctk.CTkSwitch(
            ar_row,
            text="",
            variable=self.ar_switch_var,
            onvalue=True,
            offvalue=False,
            command=self.on_auto_refresh_toggle,
        )
        self.ar_switch.grid(row=0, column=1, sticky="e")

        # Save Button
        save_box = ctk.CTkFrame(scroll, fg_color="transparent")
        save_box.pack(fill="x", pady=(15, 20))

        self.btn_save_settings = ctk.CTkButton(
            save_box,
            text="💾 Сохранить и применить настройки",
            font=ctk.CTkFont(size=14, weight="bold"),
            fg_color="#3b82f6",
            hover_color="#2563eb",
            height=40,
            command=self.save_settings_action,
        )
        self.btn_save_settings.pack(side="left")

        self.lbl_save_status = ctk.CTkLabel(
            save_box,
            text="",
            font=ctk.CTkFont(size=13),
            text_color="#10b981",
        )
        self.lbl_save_status.pack(side="left", padx=16)

    def on_strategy_change(self, val):
        self.update_strategy_description(val)

    def update_strategy_description(self, strat):
        descs = {
            "hybrid": "⭐ Рекомендуется: сохраняет контекст сессии на одном аккаунте, но автоматически ротирует при исчерпании лимитов.",
            "sticky": "📌 Последовательная: работает с одним аккаунтом до полного исчерпания квоты, затем берет следующий.",
            "round-robin": "🔄 Равномерная: распределяет каждый новый запрос по очереди между всеми аккаунтами (хорошо для множества параллельных задач).",
        }
        self.strategy_desc.configure(text=descs.get(strat, ""))

    def on_thresh_slider_change(self, val):
        self.thresh_val_label.configure(text=f"{int(val)}%")

    def on_switches_slider_change(self, val):
        self.switches_val_label.configure(text=f"{int(val)} акк.")

    def save_settings_action(self):
        self.config_data["account_selection_strategy"] = self.strategy_var.get()
        self.config_data["soft_quota_threshold_percent"] = int(self.thresh_var.get())
        self.config_data["switch_on_first_rate_limit"] = self.rate_limit_var.get()
        self.config_data["max_account_switches"] = int(self.switches_var.get())
        self.config_data["quota_style_fallback"] = self.fallback_var.get()

        ok, msg = self.save_config()
        if ok:
            self.lbl_save_status.configure(text="✅ " + msg, text_color="#10b981")
            self.set_status("Настройки сохранены в ~/.config/opencode/antigravity.json")
            self.after(4000, lambda: self.lbl_save_status.configure(text=""))
        else:
            self.lbl_save_status.configure(text="❌ " + msg, text_color="#ef4444")

    # --- Tab 3: System & OpenCode ---
    def setup_tab_system(self):
        self.tab_system.grid_columnconfigure(0, weight=1)

        scroll = ctk.CTkScrollableFrame(self.tab_system, fg_color="transparent")
        scroll.pack(fill="both", expand=True, padx=10, pady=10)

        # OpenCode Controls
        c1 = ctk.CTkFrame(scroll, fg_color="#1e1e24", corner_radius=12)
        c1.pack(fill="x", pady=6)

        ctk.CTkLabel(
            c1,
            text="Управление процессом OpenCode Desktop",
            font=ctk.CTkFont(size=15, weight="bold"),
            text_color="#f4f4f5",
        ).pack(anchor="w", padx=16, pady=(14, 4))

        ctk.CTkLabel(
            c1,
            text="OpenCode считывает auth.json и квоты на лету при каждом запросе. Перезапуск приложения НЕ требуется при смене аккаунтов или стратегий (перезапуск нужен только при полном сбое процессов):",
            font=ctk.CTkFont(size=12),
            text_color="#a1a1aa",
        ).pack(anchor="w", padx=16, pady=(0, 12))

        btn_row = ctk.CTkFrame(c1, fg_color="transparent")
        btn_row.pack(fill="x", padx=16, pady=(0, 16))

        ctk.CTkButton(
            btn_row,
            text="🔄 Перезапустить OpenCode",
            fg_color="#3b82f6",
            hover_color="#2563eb",
            command=self.restart_opencode_action,
        ).pack(side="left", padx=(0, 10))

        ctk.CTkButton(
            btn_row,
            text="⏹ Остановить OpenCode",
            fg_color="#ef4444",
            hover_color="#dc2626",
            command=self.stop_opencode_action,
        ).pack(side="left", padx=(0, 10))

        ctk.CTkButton(
            btn_row,
            text="▶ Запустить OpenCode",
            fg_color="#10b981",
            hover_color="#059669",
            command=self.start_opencode_action,
        ).pack(side="left")

        # Quick Links
        c2 = ctk.CTkFrame(scroll, fg_color="#1e1e24", corner_radius=12)
        c2.pack(fill="x", pady=6)

        ctk.CTkLabel(
            c2,
            text="Быстрый доступ к файлам конфигурации",
            font=ctk.CTkFont(size=15, weight="bold"),
            text_color="#f4f4f5",
        ).pack(anchor="w", padx=16, pady=(14, 10))

        links_box = ctk.CTkFrame(c2, fg_color="transparent")
        links_box.pack(fill="x", padx=16, pady=(0, 16))

        ctk.CTkButton(
            links_box,
            text="📂 Открыть конфиг (~/.config/opencode)",
            fg_color="#3f3f46",
            hover_color="#52525b",
            command=lambda: os.startfile(CONFIG_DIR) if CONFIG_DIR.exists() else None,
        ).pack(side="left", padx=(0, 10))

        ctk.CTkButton(
            links_box,
            text="📂 Папка логов OpenCode",
            fg_color="#3f3f46",
            hover_color="#52525b",
            command=lambda: os.startfile(LOG_DIR) if LOG_DIR.exists() else None,
        ).pack(side="left")

    def create_statusbar(self):
        status_frame = ctk.CTkFrame(self, height=28, corner_radius=0, fg_color="#111113")
        status_frame.grid(row=2, column=0, sticky="ew")

        self.lbl_status = ctk.CTkLabel(
            status_frame,
            text="Готов",
            font=ctk.CTkFont(size=11),
            text_color="#71717a",
        )
        self.lbl_status.pack(side="left", padx=16)

        self.lbl_auto_refresh = ctk.CTkLabel(
            status_frame,
            text="⏱ Автообновление квот: через 10:00",
            font=ctk.CTkFont(size=11),
            text_color="#38bdf8",
        )
        self.lbl_auto_refresh.pack(side="right", padx=16)

    def set_status(self, text):
        self.lbl_status.configure(text=text)

    # --- Periodic Auto-Refresh Methods ---
    def on_auto_refresh_toggle(self):
        self.auto_refresh_enabled = self.ar_switch_var.get()
        if self.auto_refresh_enabled:
            self.countdown_seconds = self.auto_refresh_interval_min * 60
            self.lbl_auto_refresh.configure(
                text=f"⏱ Автообновление квот: через {self.auto_refresh_interval_min}:00",
                text_color="#38bdf8",
            )
            self.set_status(f"Автообновление квот включено (раз в {self.auto_refresh_interval_min} минут)")
        else:
            self.lbl_auto_refresh.configure(
                text="⏱ Автообновление: выключено",
                text_color="#71717a",
            )
            self.set_status("Автообновление квот приостановлено")

    def start_countdown_timer(self):
        self._countdown_tick()

    def _countdown_tick(self):
        if self.auto_refresh_enabled:
            if self.countdown_seconds <= 0:
                self.countdown_seconds = self.auto_refresh_interval_min * 60
                if not self.is_loading:
                    self.set_status(f"Запуск автообновления квот (раз в {self.auto_refresh_interval_min} мин)...")
                    self.refresh_all_async()
            else:
                self.countdown_seconds -= 1

            mins = self.countdown_seconds // 60
            secs = self.countdown_seconds % 60
            self.lbl_auto_refresh.configure(
                text=f"⏱ Автообновление квот: через {mins:02d}:{secs:02d}",
                text_color="#38bdf8",
            )

            # Check OpenCode running status periodically
            if self.countdown_seconds % 3 == 0:
                self.update_opencode_status()

        self.after(1000, self._countdown_tick)

    # --- Actions & Background Tasks ---
    def refresh_all_async(self):
        if self.is_loading:
            return
        self.is_loading = True
        self.btn_refresh.configure(state="disabled", text="⏳ Загрузка...")
        self.set_status("Получение актуальных данных о квотах...")
        self.countdown_seconds = self.auto_refresh_interval_min * 60

        threading.Thread(target=self._worker_refresh_quotas, daemon=True).start()

    def _worker_refresh_quotas(self):
        # 1. Google Antigravity quotas (silent execution)
        try:
            node_exe = get_node_executable()
            cli_js = get_cli_js()
            if (os.path.exists(node_exe) or shutil.which(node_exe)) and os.path.exists(cli_js):
                cmd = [node_exe, cli_js, "quota", "--json"]
                result = run_silent_cmd(cmd, timeout=25)
                if result.returncode == 0 and result.stdout.strip():
                    data = json.loads(result.stdout)
                    google_accounts = data.get("accounts", [])
                else:
                    google_accounts = []
            else:
                google_accounts = []
        except Exception as e:
            print(f"Error fetching Google quotas: {e}")
            google_accounts = []

        # 2. OpenAI / ChatGPT quotas with auto-rotation
        try:
            openai_accounts, rotate_msg = openai_manager.refresh_all_openai_accounts()
        except Exception as e:
            print(f"Error fetching OpenAI quotas: {e}")
            openai_accounts = openai_manager.load_openai_accounts()
            rotate_msg = None

        self.after(0, lambda: self._on_quotas_fetched(google_accounts, openai_accounts, rotate_msg))

    def _on_quotas_fetched(self, google_accounts, openai_accounts, rotate_msg=None):
        # Enrich Google account emails if cli.js returned placeholder labels ("Account 1", etc.)
        try:
            known_emails = get_google_account_emails()
            for idx, acc in enumerate(google_accounts):
                curr_email = acc.get("email", "")
                if (not curr_email or curr_email.startswith("Account ")) and idx < len(known_emails):
                    acc["email"] = known_emails[idx]
        except Exception as e:
            print(f"Error enriching Google emails: {e}")

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
            self.set_status(f"Квоты обновлены в {now_str} (без перезапуска OpenCode)")
        self.update_opencode_status()

    def add_account_action(self):
        self.btn_add_account.configure(state="disabled", text="⏳ Открываем браузер...")
        self.set_status("Ожидание входа в Google через браузер...")

        threading.Thread(target=self._worker_add_account, daemon=True).start()

    def _worker_add_account(self):
        try:
            node_exe = get_node_executable()
            cli_js = get_cli_js()
            if not os.path.exists(node_exe) and not shutil.which(node_exe):
                raise FileNotFoundError(
                    "Node.js не найден в системе. Установите Node.js (https://nodejs.org) или перезапустите Antigravity Hub."
                )
            if not os.path.exists(cli_js):
                raise FileNotFoundError(f"Файл cli.js не найден по пути: {cli_js}")
            cmd = [node_exe, cli_js, "login"]
            proc = run_silent_cmd(cmd, timeout=300)
            success = proc.returncode == 0
            output = proc.stdout + proc.stderr
            if success:
                # Automatically complete offline migration into store generation
                run_silent_cmd([node_exe, cli_js, "migrate", "--offline", "--yes"], timeout=30)
        except Exception as e:
            success = False
            output = str(e)

        self.after(0, lambda: self._on_account_added(success, output))

    def _on_account_added(self, success, output):
        self.btn_add_account.configure(state="normal", text="➕ Добавить аккаунт Google")
        if success:
            messagebox.showinfo(
                "Успешно!",
                "Google аккаунт успешно авторизован, мигрирован в пул Antigravity и готов к работе!\n\n💡 Если OpenCode был открыт, нажмите «🔄 Перезапустить OpenCode» вверху окна, чтобы применить новый аккаунт.",
            )
            self.refresh_all_async()
        else:
            messagebox.showerror(
                "Ошибка входа",
                f"Не удалось завершить вход:\n{output[:300]}",
            )
            self.set_status("Ошибка авторизации")

    def activate_google_account_action(self, target_idx: int):
        ok = set_active_google_account_index(target_idx)
        if ok:
            now_str = datetime.datetime.now().strftime("%H:%M:%S")
            self.set_status(f"Активный Google аккаунт переключен на #{target_idx + 1} в {now_str} (на лету)")
            self.render_accounts()
            messagebox.showinfo(
                "Аккаунт активирован на лету!",
                f"Google аккаунт #{target_idx + 1} выбран как основной для запросов.\n\n⚡ Перезапуск OpenCode НЕ ТРЕБУЕТСЯ:\nПлагин Antigravity автоматически направляет следующий запрос через этот аккаунт.",
            )
        else:
            messagebox.showerror("Ошибка", "Не удалось сменить активный аккаунт Google.")

    def delete_google_account_action(self, acc):
        email = acc.get("email", "unknown")
        if not messagebox.askyesno(
            "Удаление Google аккаунта",
            f"Вы уверены, что хотите удалить Google аккаунт:\n{email}?\n\nОн будет удален из хранилища и исключен из пула ротации в OpenCode.",
            icon="warning"
        ):
            return
        ok = delete_google_account(email)
        if ok:
            self.set_status(f"Google аккаунт {email} удален.")
            self.refresh_all_async()
            messagebox.showinfo("Удалено", f"Аккаунт {email} успешно удален из пула Antigravity.")
        else:
            messagebox.showerror("Ошибка", f"Не удалось удалить аккаунт {email}.")

    # --- OpenAI / ChatGPT Actions ---
    def add_openai_account_action(self):
        self.btn_add_account.configure(state="disabled", text="⏳ Открываем браузер...")
        self.set_status("Ожидание входа в ChatGPT / OpenAI через браузер...")

        threading.Thread(target=self._worker_add_openai_account, daemon=True).start()

    def _worker_add_openai_account(self):
        try:
            success, message, new_acc = openai_manager.login_openai_browser(timeout=300)
        except Exception as e:
            success = False
            message = str(e)
            new_acc = None

        self.after(0, lambda: self._on_openai_account_added(success, message, new_acc))

    def _on_openai_account_added(self, success, message, new_acc):
        self.btn_add_account.configure(state="normal", text="➕ Добавить аккаунт OpenAI")
        if success and new_acc:
            messagebox.showinfo(
                "Успешно!",
                f"Аккаунт OpenAI ({new_acc.get('email', '')}) успешно добавлен и подключен к OpenCode!",
            )
            self.refresh_all_async()
        else:
            messagebox.showerror(
                "Ошибка входа",
                f"Не удалось завершить вход в OpenAI:\n{message}",
            )
            self.set_status("Ошибка авторизации OpenAI")

    def activate_openai_account_action(self, account_id):
        ok = openai_manager.set_active_openai_account(account_id)
        if ok:
            self.set_status("Активный аккаунт OpenAI переключен на лету")
            self.openai_accounts_data = openai_manager.load_openai_accounts()
            self.render_accounts()
            messagebox.showinfo(
                "Аккаунт активирован на лету!",
                "Выбранный аккаунт OpenAI теперь используется в OpenCode.\n\n⚡ Перезапуск OpenCode НЕ ТРЕБУЕТСЯ:\nOpenCode перечитывает auth.json на лету при каждом новом запросе.",
            )
        else:
            messagebox.showerror("Ошибка", "Не удалось активировать аккаунт.")

    def delete_openai_account_action(self, acc):
        email = acc.get("email", "unknown")
        if not messagebox.askyesno("Удаление аккаунта", f"Вы уверены, что хотите удалить аккаунт OpenAI:\n{email}?"):
            return
        openai_manager.remove_openai_account(acc.get("accountId") or acc.get("id"))
        self.openai_accounts_data = openai_manager.load_openai_accounts()
        self.render_accounts()
        self.set_status(f"Аккаунт {email} удален.")

    # --- Backup Export & Import (Cross-PC Migration) ---
    def export_accounts_action(self):
        file_path = filedialog.asksaveasfilename(
            title="Экспорт аккаунтов Antigravity & ChatGPT",
            defaultextension=".json",
            initialfile="antigravity_accounts_backup.json",
            filetypes=[("JSON Backup (*.json)", "*.json"), ("Все файлы (*.*)", "*.*")],
        )
        if not file_path:
            return

        try:
            google_accs = export_google_accounts()
            openai_accs = openai_manager.load_openai_accounts()

            backup_data = {
                "schemaVersion": 2,
                "exported_at": datetime.datetime.now().isoformat(),
                "app": "Antigravity Hub",
                "google_accounts": google_accs,
                "openai_accounts": openai_accs,
                "config": self.config_data,
            }

            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(backup_data, f, indent=2, ensure_ascii=False)

            self.set_status(f"Экспорт сохранен в {Path(file_path).name}")
            messagebox.showinfo(
                "Экспорт завершен",
                f"Успешно экспортировано:\n"
                f"• Google (Antigravity): {len(google_accs)} акк.\n"
                f"• OpenAI (ChatGPT): {len(openai_accs)} акк.\n\n"
                f"Файл сохранен:\n{file_path}\n\n"
                "Вы можете перенести этот файл на другой компьютер и нажать «📥 Импорт» в Antigravity Hub."
            )
        except Exception as e:
            messagebox.showerror("Ошибка экспорта", f"Не удалось экспортировать аккаунты:\n{e}")

    def import_accounts_action(self):
        file_path = filedialog.askopenfilename(
            title="Импорт аккаунтов для переноса",
            filetypes=[("JSON Backup (*.json)", "*.json"), ("Все файлы (*.*)", "*.*")],
        )
        if not file_path:
            return

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            imported_google = 0
            imported_openai = 0

            # 1. Google accounts
            google_list = []
            if isinstance(data, dict):
                if "google_accounts" in data and isinstance(data["google_accounts"], list):
                    google_list = data["google_accounts"]
                elif "accounts" in data and isinstance(data["accounts"], list):
                    google_list = data["accounts"]
            elif isinstance(data, list):
                google_list = data

            for g_acc in google_list:
                if isinstance(g_acc, dict) and ("refreshToken" in g_acc or "refresh" in g_acc):
                    if import_google_account(g_acc):
                        imported_google += 1

            # 2. OpenAI accounts
            openai_list = []
            if isinstance(data, dict) and "openai_accounts" in data and isinstance(data["openai_accounts"], list):
                openai_list = data["openai_accounts"]
            elif isinstance(data, list) and any("chatgpt" in str(x).lower() or "openai" in str(x).lower() for x in data):
                openai_list = data

            if openai_list:
                imported_openai = openai_manager.import_openai_accounts(openai_list)

            # 3. Config
            if isinstance(data, dict) and "config" in data and isinstance(data["config"], dict):
                try:
                    merged_cfg = {**self.config_data, **data["config"]}
                    self.config_data = merged_cfg
                    with open(CONFIG_FILE, "w", encoding="utf-8") as cf:
                        json.dump(merged_cfg, cf, indent=2, ensure_ascii=False)
                except Exception:
                    pass

            self.set_status(f"Импортировано: Google: {imported_google}, OpenAI: {imported_openai}")
            self.refresh_all_async()

            messagebox.showinfo(
                "Импорт завершен",
                f"Успешно импортировано:\n"
                f"• Google (Antigravity): {imported_google} акк.\n"
                f"• OpenAI (ChatGPT): {imported_openai} акк.\n\n"
                "Все аккаунты активированы и готовы к работе в OpenCode!"
            )
        except Exception as e:
            messagebox.showerror("Ошибка импорта", f"Не удалось импортировать аккаунты:\n{e}")

    def update_opencode_status(self):
        def check():
            try:
                res = run_silent_cmd(
                    ["tasklist", "/nh", "/fi", "IMAGENAME eq opencode*"],
                    timeout=3
                )
                stdout_lower = (res.stdout or "").lower()
                is_running = ("opencode.exe" in stdout_lower) or ("opencode-cli.exe" in stdout_lower)
            except Exception:
                is_running = False

            self.after(0, lambda: self._set_opencode_badge(is_running))

        threading.Thread(target=check, daemon=True).start()

    def _set_opencode_badge(self, is_running):
        if is_running:
            self.opencode_badge.configure(
                text="🟢 OpenCode: Запущен",
                text_color="#10b981",
                fg_color="#064e3b",
            )
        else:
            self.opencode_badge.configure(
                text="⚪ OpenCode: Остановлен",
                text_color="#a1a1aa",
                fg_color="#27272a",
            )

    def restart_opencode_action(self):
        self.set_status("Перезапуск OpenCode...")

        def _do_restart():
            run_silent_cmd(["taskkill", "/f", "/im", "OpenCode.exe"], timeout=5)
            run_silent_cmd(["taskkill", "/f", "/im", "opencode-cli.exe"], timeout=5)
            time.sleep(1)
            cleanup_opencode_locks()
            time.sleep(1)
            exe = get_opencode_exe()
            try:
                if sys.platform == "win32" and os.path.exists(exe):
                    os.startfile(exe)
                elif os.path.exists(exe):
                    subprocess.Popen([exe], cwd=os.path.dirname(exe))
                else:
                    self.after(0, lambda: self.set_status(f"OpenCode.exe не найден: {exe}"))
                    return
            except Exception as e:
                print(f"Error starting OpenCode: {e}")
            time.sleep(3)
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
        cleanup_opencode_locks()
        exe = get_opencode_exe()
        if not os.path.exists(exe):
            self.set_status(f"OpenCode.exe не найден: {exe}")
            return
        try:
            if sys.platform == "win32":
                os.startfile(exe)
            else:
                subprocess.Popen([exe], cwd=os.path.dirname(exe))
            self.set_status("OpenCode запущен")
        except Exception as e:
            self.set_status(f"Ошибка запуска OpenCode: {e}")
        self.after(3000, self.update_opencode_status)


if __name__ == "__main__":
    app = AntigravityManagerApp()
    app.mainloop()
