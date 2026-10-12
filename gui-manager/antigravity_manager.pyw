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
from pathlib import Path
import tkinter as tk
from tkinter import messagebox

import shutil
import customtkinter as ctk

# --- Paths & Dynamic Resolution ---
def get_node_executable():
    node = shutil.which("node")
    if node and os.path.exists(node):
        return node
    candidates = [
        Path.home() / "AppData/Local/Programs/Python/Python312/Lib/site-packages/playwright/driver/node.exe",
        Path.home() / "AppData/Local/Programs/Python/Python311/Lib/site-packages/playwright/driver/node.exe",
        Path("C:/Program Files/nodejs/node.exe"),
        Path("C:/Program Files (x86)/nodejs/node.exe"),
    ]
    for c in candidates:
        if c.exists():
            return str(c)
    return "node"

def get_cli_js():
    local_cli = Path(__file__).resolve().parent.parent / "plugin" / "dist" / "cli.js"
    if local_cli.exists():
        return str(local_cli)
    cache_cli = Path.home() / ".cache" / "opencode" / "packages" / "@cortexkit" / "opencode-antigravity-auth@latest" / "node_modules" / "@cortexkit" / "opencode-antigravity-auth" / "dist" / "cli.js"
    if cache_cli.exists():
        return str(cache_cli)
    return str(local_cli)

def get_opencode_exe():
    appdata_exe = Path.home() / "AppData" / "Local" / "Programs" / "@opencode-aidesktop" / "OpenCode.exe"
    if appdata_exe.exists():
        return str(appdata_exe)
    which_opencode = shutil.which("opencode")
    if which_opencode:
        return which_opencode
    return str(appdata_exe)

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

ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")


class AntigravityManagerApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("Google Antigravity — Менеджер аккаунтов и квот")
        self.geometry("980x740")
        self.minsize(860, 640)

        # State
        self.accounts_data = []
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
            text="Мульти-аккаунты Google, живые квоты и автопереключение для OpenCode",
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
        top_bar.grid_columnconfigure(2, weight=1)

        self.btn_add_account = ctk.CTkButton(
            top_bar,
            text="➕ Добавить аккаунт Google",
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color="#10b981",
            hover_color="#059669",
            height=36,
            command=self.add_account_action,
        )
        self.btn_add_account.grid(row=0, column=0, padx=(0, 10))

        self.btn_refresh = ctk.CTkButton(
            top_bar,
            text="🔄 Обновить квоты",
            font=ctk.CTkFont(size=13),
            fg_color="#3f3f46",
            hover_color="#52525b",
            height=36,
            command=self.refresh_all_async,
        )
        self.btn_refresh.grid(row=0, column=1, padx=(0, 10))

        self.lbl_accounts_count = ctk.CTkLabel(
            top_bar,
            text="Загрузка...",
            font=ctk.CTkFont(size=13),
            text_color="#a1a1aa",
        )
        self.lbl_accounts_count.grid(row=0, column=2, sticky="e")

        # Scrollable container for account cards
        self.accounts_scroll = ctk.CTkScrollableFrame(
            self.tab_accounts,
            fg_color="#121214",
            corner_radius=10,
        )
        self.accounts_scroll.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 10))
        self.accounts_scroll.grid_columnconfigure(0, weight=1)

    def render_accounts(self):
        # Clear existing widgets
        for widget in self.accounts_scroll.winfo_children():
            widget.destroy()

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
            self.lbl_accounts_count.configure(text="0 аккаунтов")
            return

        total = len(self.accounts_data)
        self.lbl_accounts_count.configure(text=f"Всего аккаунтов: {total}")

        for acc in self.accounts_data:
            self.create_account_card(acc)

    def create_account_card(self, acc):
        email = acc.get("email", "unknown@gmail.com")
        index = acc.get("index", 1)
        status = acc.get("status", "ok")
        groups = acc.get("groups", [])

        # Parse quotas
        gemini_group = next((g for g in groups if g.get("name") == "gemini"), None)
        nongemini_group = next((g for g in groups if g.get("name") == "non-gemini"), None)

        card = ctk.CTkFrame(self.accounts_scroll, fg_color="#1e1e24", corner_radius=12)
        card.pack(fill="x", pady=8, padx=4)
        card.grid_columnconfigure(1, weight=1)

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
            fg_color="#3b82f6",
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

        # Status badge
        is_ok = status.lower() in ("ok", "active")
        status_color = "#10b981" if is_ok else "#ef4444"
        status_text = "● Активен" if is_ok else f"● {status}"

        status_lbl = ctk.CTkLabel(
            header_row,
            text=status_text,
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=status_color,
            fg_color="#27272a",
            corner_radius=8,
            padx=10,
            pady=3,
        )
        status_lbl.grid(row=0, column=2, sticky="e")

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
            text="При изменении аккаунтов или стратегии перезапустите приложение для применения настроек:",
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
        try:
            cmd = [NODE_EXE, CLI_JS, "quota", "--json"]
            flags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
            result = subprocess.run(
                cmd, capture_output=True, text=True, encoding="utf-8", timeout=25, creationflags=flags
            )
            if result.returncode == 0 and result.stdout.strip():
                data = json.loads(result.stdout)
                accounts = data.get("accounts", [])
            else:
                accounts = []
        except Exception as e:
            print(f"Error fetching quotas: {e}")
            accounts = []

        self.after(0, lambda: self._on_quotas_fetched(accounts))

    def _on_quotas_fetched(self, accounts):
        self.accounts_data = accounts
        self.render_accounts()
        self.is_loading = False
        self.btn_refresh.configure(state="normal", text="🔄 Обновить квоты")
        now_str = datetime.datetime.now().strftime("%H:%M:%S")
        self.countdown_seconds = self.auto_refresh_interval_min * 60
        self.set_status(f"Квоты обновлены в {now_str} (следующее автообновление через {self.auto_refresh_interval_min} мин)")
        self.update_opencode_status()

    def add_account_action(self):
        self.btn_add_account.configure(state="disabled", text="⏳ Открываем браузер...")
        self.set_status("Ожидание входа в Google через браузер...")

        threading.Thread(target=self._worker_add_account, daemon=True).start()

    def _worker_add_account(self):
        try:
            cmd = [NODE_EXE, CLI_JS, "login"]
            flags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
            proc = subprocess.run(
                cmd, capture_output=True, text=True, encoding="utf-8", timeout=300, creationflags=flags
            )
            success = proc.returncode == 0
            output = proc.stdout + proc.stderr
        except Exception as e:
            success = False
            output = str(e)

        self.after(0, lambda: self._on_account_added(success, output))

    def _on_account_added(self, success, output):
        self.btn_add_account.configure(state="normal", text="➕ Добавить аккаунт Google")
        if success:
            messagebox.showinfo(
                "Успешно!",
                "Google аккаунт успешно авторизован и добавлен в пул ротации Antigravity!",
            )
            self.refresh_all_async()
        else:
            messagebox.showerror(
                "Ошибка входа",
                f"Не удалось завершить вход:\n{output[:300]}",
            )
            self.set_status("Ошибка авторизации")

    def update_opencode_status(self):
        def check():
            try:
                res = subprocess.run(
                    ["powershell", "-NoProfile", "-Command", "Get-Process -Name '*OpenCode*' -ErrorAction SilentlyContinue | Measure-Object | Select-Object -ExpandProperty Count"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                count = int(res.stdout.strip()) if res.stdout.strip().isdigit() else 0
                is_running = count > 0
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
            subprocess.run(
                ["powershell", "-NoProfile", "-Command", "Stop-Process -Name OpenCode -Force -ErrorAction SilentlyContinue"],
                capture_output=True,
            )
            time.sleep(2)
            subprocess.run(
                ["powershell", "-NoProfile", "-Command", f'Start-Process -FilePath "{OPENCODE_EXE}"'],
                capture_output=True,
            )
            time.sleep(3)
            self.after(0, self.update_opencode_status)
            self.after(0, lambda: self.set_status("OpenCode перезапущен!"))

        threading.Thread(target=_do_restart, daemon=True).start()

    def stop_opencode_action(self):
        subprocess.run(
            ["powershell", "-NoProfile", "-Command", "Stop-Process -Name OpenCode -Force -ErrorAction SilentlyContinue"],
            capture_output=True,
        )
        self.update_opencode_status()
        self.set_status("OpenCode остановлен")

    def start_opencode_action(self):
        subprocess.run(
            ["powershell", "-NoProfile", "-Command", f'Start-Process -FilePath "{OPENCODE_EXE}"'],
            capture_output=True,
        )
        self.after(3000, self.update_opencode_status)
        self.set_status("OpenCode запущен")


if __name__ == "__main__":
    app = AntigravityManagerApp()
    app.mainloop()
