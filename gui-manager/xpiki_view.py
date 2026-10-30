"""
Xpiki Claude API View for Antigravity Hub.
Provides configuration for third-party Claude API endpoints (api.xpiki.com),
OpenCode provider integration, real-time quota limit display (matching Google cards),
and 1-click Claude Code CLI / Claude Desktop setup.
Follows Concept 2: Linear Minimal (Graphite Glass) design.
"""

import os
import sys
import threading
import subprocess
from tkinter import messagebox

import customtkinter as ctk
import xpiki_manager


class XpikiView(ctk.CTkScrollableFrame):
    def __init__(self, parent, app, colors):
        super().__init__(parent, fg_color=colors["bg"], corner_radius=0)
        self.app = app
        self.colors = colors
        self.grid_columnconfigure(0, weight=1)

        self.config_data = xpiki_manager.load_xpiki_config()
        self.model_vars = {}

        self._render_header()
        self._render_warning_banner()
        self._render_quota_card()
        self._render_settings_card()
        self._render_models_card()
        if self.config_data.get("connected") and self.config_data.get("api_key"):
            self.after(100, self.refresh_quota_action)

    def _render_header(self):
        hdr = ctk.CTkFrame(self, fg_color="transparent")
        hdr.pack(fill="x", padx=16, pady=(16, 8))

        ctk.CTkLabel(
            hdr,
            text="🟠 Claude API (Xpiki / Шлюз)",
            font=self.app.font(20, "bold"),
            text_color=self.colors["text_primary"],
            anchor="w",
        ).pack(fill="x")

        ctk.CTkLabel(
            hdr,
            text="Подключение коммерческого шлюза Claude API с пулом токенов и моделями Opus 5, Sonnet 5 и Haiku 4.5.",
            font=self.app.font(12),
            text_color=self.colors["text_secondary"],
            anchor="w",
        ).pack(fill="x", pady=(2, 0))

    def _render_warning_banner(self):
        warn_card = ctk.CTkFrame(
            self,
            fg_color=self.colors["subbox_bg"],
            corner_radius=10,
            border_width=1,
            border_color="#d29922",
        )
        warn_card.pack(fill="x", padx=16, pady=(0, 12))

        ctk.CTkLabel(
            warn_card,
            text="⚠️ Важное примечание о безопасности (из инструкции Teletype)",
            font=self.app.font(12, "bold"),
            text_color="#d29922",
            anchor="w",
        ).pack(fill="x", padx=14, pady=(10, 2))

        ctk.CTkLabel(
            warn_card,
            text=(
                "«ОБЯЗАТЕЛЬНО ИСПОЛЬЗОВАТЬ КАЧЕСТВЕННЫЙ VPN!» — для работы с серверами Claude и шлюзом api.xpiki.com "
                "требуется активный туннель. Рекомендуется включить встроенный VLESS-туннель Hub (раздел «Сеть, DNS & VLESS») "
                "или включить системный VPN перед отправкой запросов."
            ),
            font=self.app.font(11),
            text_color=self.colors["text_secondary"],
            justify="left",
            wraplength=760,
            anchor="w",
        ).pack(fill="x", padx=14, pady=(0, 10))

    def _render_quota_card(self):
        """Renders the real-time quota limit card matching the exact design of Google accounts."""
        is_connected = self.config_data.get("connected", False) and bool(self.config_data.get("api_key"))

        if not is_connected:
            self.quota_card = ctk.CTkFrame(
                self,
                fg_color=self.colors["card_bg"],
                corner_radius=12,
                border_width=1,
                border_color=self.colors["border"],
            )
            self.quota_card.pack(fill="x", padx=16, pady=(0, 12))
            ctk.CTkLabel(
                self.quota_card,
                text="📭",
                font=self.app.font(size=28),
            ).pack(pady=(16, 4))
            ctk.CTkLabel(
                self.quota_card,
                text="Claude API (Xpiki) не подключен",
                font=self.app.font(size=14, weight="bold"),
                text_color=self.colors["text_primary"],
            ).pack()
            ctk.CTkLabel(
                self.quota_card,
                text="Введите API-ключ в форме ниже и нажмите «Подключить в OpenCode». После подключения здесь появится карточка с лимитами и остатком токенов.",
                font=self.app.font(size=11),
                text_color=self.colors["text_secondary"],
                justify="center",
            ).pack(pady=(4, 16))
            return

        quota = self.config_data.get("cached_quota") or xpiki_manager.load_xpiki_config().get("cached_quota") or {
            "status": "unavailable",
        }
        rpm = quota.get("effective_rpm")
        rpm_label = f"{rpm} RPM доступно" if rpm is not None else "не получен"

        self.quota_card = ctk.CTkFrame(
            self,
            fg_color=self.colors["card_active_bg"],
            corner_radius=12,
            border_width=1,
            border_color=self.colors["border_active"],
        )
        self.quota_card.pack(fill="x", padx=16, pady=(0, 12))

        # 1. Header row
        header = ctk.CTkFrame(self.quota_card, fg_color="transparent")
        header.pack(fill="x", padx=14, pady=(14, 6))
        header.grid_columnconfigure(0, weight=1)

        title_box = ctk.CTkFrame(header, fg_color="transparent")
        title_box.grid(row=0, column=0, sticky="w")

        prefix = "⭐ " if is_connected else ""
        key_preview = self.config_data.get("api_key", "")
        short_key = (f"{key_preview[:8]}...{key_preview[-4:]}") if len(key_preview) > 14 else "Xpiki Claude Gateway"

        ctk.CTkLabel(
            title_box,
            text=f"{prefix}Xpiki Claude API ({short_key})",
            font=self.app.font(size=13, weight="bold"),
            text_color=self.colors["text_primary"],
        ).pack(anchor="w")

        status_sub = "Подключен к OpenCode" if is_connected else "Не подключен"
        ctk.CTkLabel(
            title_box,
            text=f"{status_sub} • RPM: {rpm if rpm is not None else '—'} • ID: xpiki-api",
            font=self.app.font(size=11),
            text_color=self.colors["text_muted"],
        ).pack(anchor="w", pady=(1, 0))

        # Badges box
        badges_box = ctk.CTkFrame(header, fg_color="transparent")
        badges_box.grid(row=0, column=1, sticky="e")

        if is_connected:
            ctk.CTkLabel(
                badges_box,
                text="● Активен",
                font=self.app.font(size=11, weight="bold"),
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
                font=self.app.font(size=11, weight="bold"),
                fg_color=self.colors["subbox_bg"],
                text_color=self.colors["text_muted"],
                border_width=1,
                border_color=self.colors["border"],
                corner_radius=6,
                padx=8,
                pady=2,
            ).pack(side="left", padx=(0, 6))

        ctk.CTkLabel(
            badges_box,
            text=(
                f"{round(quota.get('quota_limit', 0) / 1000000, 1)}M ЛИМИТ"
                if quota.get("quota_limit") is not None
                else "ЛИМИТ НЕ ПОЛУЧЕН"
            ),
            font=self.app.font(size=11, weight="bold"),
            fg_color=self.colors["subbox_bg"],
            text_color=self.colors["accent_cyan"],
            border_width=1,
            border_color=self.colors["border"],
            corner_radius=6,
            padx=7,
            pady=2,
        ).pack(side="left")

        # 2. Sleek Inset Quotas Box (identical to Google account cards)
        quotas_container = ctk.CTkFrame(
            self.quota_card,
            fg_color=self.colors["subbox_bg"],
            corner_radius=8,
            border_width=1,
            border_color=self.colors["border"],
        )
        quotas_container.pack(fill="x", padx=14, pady=(4, 8), ipadx=4, ipady=4)

        # Title
        t_row = ctk.CTkFrame(quotas_container, fg_color="transparent")
        t_row.pack(fill="x", padx=8, pady=(4, 2))
        ctk.CTkLabel(
            t_row,
            text="Claude Opus 5 / Sonnet 5 (Лимиты шлюза Xpiki)",
            font=self.app.font(size=12, weight="bold"),
            text_color=self.colors["text_primary"],
        ).pack(side="left")

        # Row 1: Rate limit (RPM)
        r1_row = ctk.CTkFrame(quotas_container, fg_color="transparent")
        r1_row.pack(fill="x", padx=8, pady=(2, 1))

        ctk.CTkLabel(
            r1_row,
            text=f"⚡ Лимит {rpm if rpm is not None else '—'} RPM",
            font=self.app.font(size=10, weight="bold"),
            fg_color=self.colors["quota_5h_bg"],
            text_color=self.colors["quota_5h"][1],
            corner_radius=4,
            padx=6,
            pady=1,
        ).pack(side="left")

        ctk.CTkLabel(
            r1_row,
            text=f"{rpm_label}",
            font=self.app.font(size=11, weight="bold"),
            text_color=self.colors["quota_5h"][1],
        ).pack(side="right")

        b_rpm = ctk.CTkProgressBar(quotas_container, height=4, corner_radius=2)
        b_rpm.pack(fill="x", padx=8, pady=(2, 6))
        b_rpm.set(1.0)
        b_rpm.configure(progress_color=self.colors["quota_5h"][1], fg_color=self.colors["bar_bg"])

        # Row 2: Token Pool Balance
        r2_row = ctk.CTkFrame(quotas_container, fg_color="transparent")
        r2_row.pack(fill="x", padx=8, pady=(2, 1))

        ctk.CTkLabel(
            r2_row,
            text="📅 Квота токенов",
            font=self.app.font(size=10, weight="bold"),
            fg_color=self.colors["quota_weekly_bg"],
            text_color=self.colors["quota_weekly"][1],
            corner_radius=4,
            padx=6,
            pady=1,
        ).pack(side="left")

        total_tok = quota.get("quota_limit")
        rem_tok = quota.get("remaining_tokens")
        pct_tok = quota.get("remaining_percent")
        quota_available = total_tok is not None and rem_tok is not None and pct_tok is not None
        col_tok = "#f85149" if quota_available and pct_tok <= 20 else self.colors["quota_weekly"][1]

        if quota_available:
            rem_m = round(rem_tok / 1000000, 1)
            tot_m = round(total_tok / 1000000, 1)
            tok_str = f"{rem_m}M / {tot_m}M ({int(pct_tok)}%)"
        else:
            tok_str = "Не удалось получить квоту"

        ctk.CTkLabel(
            r2_row,
            text=tok_str,
            font=self.app.font(size=11, weight="bold"),
            text_color=col_tok,
        ).pack(side="right")

        b_tok = ctk.CTkProgressBar(quotas_container, height=4, corner_radius=2)
        b_tok.pack(fill="x", padx=8, pady=(2, 4))
        b_tok.set(max(0.0, min(1.0, (pct_tok or 0) / 100.0)))
        b_tok.configure(progress_color=col_tok, fg_color=self.colors["bar_bg"])

        # 3. Card Footer Actions
        divider = ctk.CTkFrame(self.quota_card, height=1, fg_color=self.colors["border"])
        divider.pack(fill="x", padx=14, pady=(4, 8))

        footer = ctk.CTkFrame(self.quota_card, fg_color="transparent")
        footer.pack(fill="x", padx=14, pady=(0, 10))
        footer.grid_columnconfigure(0, weight=1)

        actions_pill = ctk.CTkFrame(footer, fg_color="transparent")
        actions_pill.grid(row=0, column=0, sticky="w")

        ctk.CTkButton(
            actions_pill,
            text="🩺 Тест",
            font=self.app.font(size=11, weight="bold"),
            fg_color=("#f6f8fa", "#21262d"),
            hover_color=("#eaeef2", "#30363d"),
            text_color=self.colors["text_primary"],
            border_width=1,
            border_color=self.colors["border"],
            width=58,
            height=28,
            corner_radius=6,
            command=self.test_connection_action,
        ).pack(side="left", padx=(0, 4))

        ctk.CTkButton(
            actions_pill,
            text="🔄 Баланс",
            font=self.app.font(size=11, weight="bold"),
            fg_color=("#0969da", "#c88635"),
            hover_color=("#0550ae", "#e09a43"),
            text_color="#ffffff",
            width=76,
            height=28,
            corner_radius=6,
            command=self.refresh_quota_action,
        ).pack(side="left", padx=(0, 4))

        ctk.CTkButton(
            actions_pill,
            text="📋",
            font=self.app.font(size=13, weight="bold"),
            fg_color=("#f6f8fa", "#21262d"),
            hover_color=("#eaeef2", "#30363d"),
            text_color=self.colors["text_primary"],
            border_width=1,
            border_color=self.colors["border"],
            width=30,
            height=28,
            corner_radius=6,
            command=lambda: self.app.copy_to_clipboard(self.config_data.get("api_key", ""), "Ключ скопирован"),
        ).pack(side="left", padx=(0, 4))

        ctk.CTkButton(
            actions_pill,
            text="🔍",
            font=self.app.font(size=12, weight="bold"),
            fg_color=("#f6f8fa", "#21262d"),
            hover_color=("#eaeef2", "#30363d"),
            text_color=self.colors["text_primary"],
            border_width=1,
            border_color=self.colors["border"],
            width=30,
            height=28,
            corner_radius=6,
            command=self.open_balance_page,
        ).pack(side="left", padx=(0, 4))

        ctk.CTkButton(
            actions_pill,
            text="🗑",
            font=self.app.font(size=13, weight="bold"),
            fg_color=("#f6f8fa", "#21262d"),
            hover_color=("#ffebe9", "#3c1e1e"),
            text_color=("#cf222e", "#f85149"),
            border_width=1,
            border_color=self.colors["border"],
            width=30,
            height=28,
            corner_radius=6,
            command=self.disconnect_action,
        ).pack(side="left")

        right_box = ctk.CTkFrame(footer, fg_color="transparent")
        right_box.grid(row=0, column=1, sticky="e")

        pool_var = ctk.BooleanVar(value=is_connected)
        ctk.CTkSwitch(
            right_box,
            text="В пуле",
            variable=pool_var,
            font=self.app.font(size=11),
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
            command=lambda: self.toggle_pool_action(pool_var.get()),
        ).pack(side="right")

    def _render_settings_card(self):
        card = ctk.CTkFrame(
            self,
            fg_color=self.colors["card_bg"],
            corner_radius=12,
            border_width=1,
            border_color=self.colors["border"],
        )
        card.pack(fill="x", padx=16, pady=(0, 12))

        ctk.CTkLabel(
            card,
            text="Параметры подключения Claude API",
            font=self.app.font(14, "bold"),
            text_color=self.colors["text_primary"],
            anchor="w",
        ).pack(fill="x", padx=16, pady=(14, 8))

        # API Key
        ctk.CTkLabel(
            card,
            text="API-ключ Claude (sk-...):",
            font=self.app.font(11, "bold"),
            text_color=self.colors["text_secondary"],
            anchor="w",
        ).pack(fill="x", padx=16, pady=(2, 2))

        self.key_entry = ctk.CTkEntry(
            card,
            placeholder_text="sk-...",
            font=self.app.font(12),
            height=34,
            show="•",
            fg_color=self.colors["subbox_bg"],
            border_color=self.colors["border"],
            text_color=self.colors["text_primary"],
        )
        self.key_entry.pack(fill="x", padx=16, pady=(0, 8))
        if self.config_data.get("api_key"):
            self.key_entry.insert(0, self.config_data["api_key"])

        # Base URL
        ctk.CTkLabel(
            card,
            text="Base URL API-шлюза:",
            font=self.app.font(11, "bold"),
            text_color=self.colors["text_secondary"],
            anchor="w",
        ).pack(fill="x", padx=16, pady=(2, 2))

        self.url_entry = ctk.CTkEntry(
            card,
            placeholder_text="https://api.xpiki.com/v1",
            font=self.app.font(12),
            height=34,
            fg_color=self.colors["subbox_bg"],
            border_color=self.colors["border"],
            text_color=self.colors["text_primary"],
        )
        self.url_entry.pack(fill="x", padx=16, pady=(0, 10))
        self.url_entry.insert(0, self.config_data.get("base_url") or xpiki_manager.DEFAULT_BASE_URL)

        # Status Label
        self.status_lbl = ctk.CTkLabel(
            card,
            text="",
            font=self.app.font(11),
            text_color="#10b981",
            wraplength=740,
            justify="left",
            anchor="w",
        )
        self.status_lbl.pack(fill="x", padx=16, pady=(0, 8))

        # Action Buttons
        btn_row = ctk.CTkFrame(card, fg_color="transparent")
        btn_row.pack(fill="x", padx=16, pady=(0, 14))

        self.btn_save = ctk.CTkButton(
            btn_row,
            text="💾 Подключить в OpenCode",
            font=self.app.font(12, "bold"),
            fg_color="#a96e2c",
            hover_color="#c88635",
            height=34,
            corner_radius=6,
            command=self.save_and_apply_action,
        )
        self.btn_save.pack(side="left", padx=(0, 6))

        self.btn_test = ctk.CTkButton(
            btn_row,
            text="🩺 Проверить подключение",
            font=self.app.font(12, "bold"),
            fg_color=("#0969da", "#c88635"),
            hover_color=("#0550ae", "#e09a43"),
            height=34,
            corner_radius=6,
            command=self.test_connection_action,
        )
        self.btn_test.pack(side="left", padx=(0, 6))

        self.btn_check_balance = ctk.CTkButton(
            btn_row,
            text="🔍 Баланс токенов (xpiki.com/key)",
            font=self.app.font(11),
            fg_color=self.colors["subbox_bg"],
            hover_color=("#eaeef2", "#21262d"),
            text_color=self.colors["accent_cyan"],
            border_width=1,
            border_color=self.colors["border"],
            height=34,
            corner_radius=6,
            command=self.open_balance_page,
        )
        self.btn_check_balance.pack(side="left", padx=(0, 6))

    def _render_models_card(self):
        card = ctk.CTkFrame(
            self,
            fg_color=self.colors["card_bg"],
            corner_radius=12,
            border_width=1,
            border_color=self.colors["border"],
        )
        card.pack(fill="x", padx=16, pady=(0, 20))

        ctk.CTkLabel(
            card,
            text="Каталог моделей Xpiki Claude API",
            font=self.app.font(14, "bold"),
            text_color=self.colors["text_primary"],
            anchor="w",
        ).pack(fill="x", padx=16, pady=(14, 4))

        ctk.CTkLabel(
            card,
            text="Отметьте модели, которые должны отображаться в выпадающем списке OpenCode (префикс xpiki/...).",
            font=self.app.font(11),
            text_color=self.colors["text_secondary"],
            anchor="w",
        ).pack(fill="x", padx=16, pady=(0, 10))

        enabled_set = set(self.config_data.get("enabled_models", list(xpiki_manager.XPIKI_MODELS.keys())))

        for mid, info in xpiki_manager.XPIKI_MODELS.items():
            row = ctk.CTkFrame(card, fg_color=self.colors["subbox_bg"], corner_radius=8, border_width=1, border_color=self.colors["border"])
            row.pack(fill="x", padx=16, pady=3)

            var = ctk.BooleanVar(value=mid in enabled_set)
            self.model_vars[mid] = var

            sw = ctk.CTkSwitch(
                row,
                text=info["name"],
                variable=var,
                font=self.app.font(11, "bold"),
                width=40,
                height=20,
                switch_width=32,
                switch_height=16,
                progress_color="#238636",
            )
            sw.pack(side="left", padx=12, pady=8)

            ctk.CTkLabel(
                row,
                text=f"— {info['description']} (контекст 200k)",
                font=self.app.font(10),
                text_color=self.colors["text_muted"],
            ).pack(side="left", padx=4)

    def refresh_quota_action(self):
        key = self.key_entry.get().strip()
        url = self.url_entry.get().strip() or xpiki_manager.DEFAULT_BASE_URL
        if not key:
            self.status_lbl.configure(text="❌ Сначала введите API-ключ", text_color="#ef4444")
            return

        self.status_lbl.configure(text="Запрос баланса токенов...", text_color=self.colors["accent_cyan"])

        def _worker():
            quota = xpiki_manager.fetch_xpiki_quota(key, url)
            def _done():
                self.config_data = xpiki_manager.load_xpiki_config()
                self.quota_card.destroy()
                self._render_quota_card()
                if quota.get("status") == "ok":
                    self.status_lbl.configure(text="✔ Квота токенов успешно обновлена!", text_color="#3fb950")
                elif quota.get("status") == "stale":
                    self.status_lbl.configure(text="⚠ Не удалось обновить квоту; показаны последние сохранённые данные.", text_color="#d29922")
                else:
                    self.status_lbl.configure(text=f"❌ Квота не получена: {quota.get('error', 'сервер не вернул данные')}", text_color="#ef4444")
            self.after(0, _done)

        threading.Thread(target=_worker, daemon=True).start()

    def test_connection_action(self):
        key = self.key_entry.get().strip()
        url = self.url_entry.get().strip()
        if not key:
            self.status_lbl.configure(text="❌ Введите API-ключ для проверки", text_color="#ef4444")
            return

        self.btn_test.configure(state="disabled", text="⏳ Проверка...")
        self.status_lbl.configure(text="Отправка тестового запроса к Claude API...", text_color=self.colors["accent_cyan"])

        def _worker():
            ok, msg, data = xpiki_manager.test_xpiki_connection(key, url)
            def _done():
                self.btn_test.configure(state="normal", text="🩺 Проверить подключение")
                if ok:
                    self.status_lbl.configure(text=f"✔ {msg}", text_color="#3fb950")
                    messagebox.showinfo("Успешное подключение", f"Соединение с {url} успешно!\nКлюч действителен.")
                else:
                    self.status_lbl.configure(text=f"❌ {msg}", text_color="#ef4444")
                    messagebox.showerror("Ошибка подключения", msg)
            self.after(0, _done)

        threading.Thread(target=_worker, daemon=True).start()

    def save_and_apply_action(self):
        key = self.key_entry.get().strip()
        url = self.url_entry.get().strip() or xpiki_manager.DEFAULT_BASE_URL
        if not key:
            self.status_lbl.configure(text="❌ Введите API-ключ", text_color="#ef4444")
            return

        selected_models = [mid for mid, v in self.model_vars.items() if v.get()]
        if not selected_models:
            selected_models = list(xpiki_manager.XPIKI_MODELS.keys())

        cfg = {
            "api_key": key,
            "base_url": url,
            "enabled_models": selected_models,
            "connected": True,
        }
        xpiki_manager.save_xpiki_config(cfg)
        ok = xpiki_manager.configure_opencode(key, url, selected_models)
        if ok:
            self.status_lbl.configure(text="✔ Провайдер Claude API (Xpiki) успешно добавлен в OpenCode!", text_color="#3fb950")
            self.app.show_flash("Xpiki Claude API успешно подключен в OpenCode!")
            self.config_data = xpiki_manager.load_xpiki_config()
            if hasattr(self, "quota_card"):
                self.quota_card.destroy()
                self._render_quota_card()
                self.after(100, self.refresh_quota_action)
            messagebox.showinfo("Готово", "Провайдер Claude API (Xpiki) успешно подключен в OpenCode!\nМодели доступны с префиксом xpiki/...\n\nЛимит аккаунта загружается автоматически.")
        else:
            self.status_lbl.configure(text="❌ Не удалось обновить opencode.json", text_color="#ef4444")

    def toggle_pool_action(self, enabled: bool):
        key = self.key_entry.get().strip()
        url = self.url_entry.get().strip() or xpiki_manager.DEFAULT_BASE_URL
        selected_models = [mid for mid, v in self.model_vars.items() if v.get()]
        if enabled:
            if not key:
                messagebox.showwarning("Внимание", "Сначала укажите API-ключ")
                return
            xpiki_manager.configure_opencode(key, url, selected_models)
            self.config_data["connected"] = True
            xpiki_manager.save_xpiki_config(self.config_data)
            self.app.show_flash("Xpiki Claude API включен в пул.")
        else:
            xpiki_manager.disconnect_xpiki()
            self.config_data["connected"] = False
            self.app.show_flash("Xpiki Claude API исключен из пула.")

    def open_balance_page(self):
        try:
            if sys.platform == "win32":
                os.startfile(xpiki_manager.BALANCE_URL)
                return
        except Exception:
            pass
        try:
            import webbrowser
            webbrowser.open(xpiki_manager.BALANCE_URL)
        except Exception:
            pass

    def disconnect_action(self):
        if not messagebox.askyesno("Отключение", "Отключить провайдер Claude API (Xpiki) от OpenCode?"):
            return
        if xpiki_manager.disconnect_xpiki():
            self.key_entry.delete(0, "end")
            self.status_lbl.configure(text="Провайдер отключен от OpenCode.", text_color=self.colors["text_muted"])
            self.app.show_flash("Xpiki Claude API отключен.")
            self.config_data["connected"] = False
            if hasattr(self, "quota_card"):
                self.quota_card.destroy()
                self._render_quota_card()
        else:
            messagebox.showerror("Ошибка", "Не удалось удалить провайдер из opencode.json")
