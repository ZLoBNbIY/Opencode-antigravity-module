"""Claude Cloud Code (MWAPI) setup, limits and model selection for Antigravity Hub."""
import threading
import time
import webbrowser
from datetime import datetime
from tkinter import messagebox

import customtkinter as ctk
import mwapi_manager

AUTO_REFRESH_SECONDS = 60


class MwapiView(ctk.CTkScrollableFrame):
    def __init__(self, parent, app, colors):
        super().__init__(parent, fg_color=colors["bg"], corner_radius=0)
        self.app = app
        self.colors = colors
        self.models = []
        self.checkboxes = []
        self._last_usage_refresh = 0.0
        self._usage_loading = False

        ctk.CTkLabel(
            self,
            text="Claude (Cloud Code)",
            font=app.font(22, "bold"),
            anchor="w",
        ).pack(fill="x", pady=(0, 4))

        ctk.CTkLabel(
            self,
            text="MWAPI Gateway · Claude Opus / Sonnet, лимиты и расход аккаунта.",
            anchor="w",
            font=app.font(12),
            text_color=colors["text_secondary"],
        ).pack(fill="x", pady=(0, 12))

        ctk.CTkLabel(
            self,
            text="Чтобы подключить модели Cloud Code через MWAPI Gateway:",
            anchor="w",
            font=app.font(13),
        ).pack(fill="x")

        self._instruction_link(
            "1. Откройте панель управления MWAPI (https://api.mwapi.dev/dashboard).",
            "https://api.mwapi.dev/dashboard",
        )
        self._instruction_link(
            "2. Перейдите в раздел токенов и скопируйте ваш API-ключ (sk-...).",
            "https://api.mwapi.dev/token",
        )

        ctk.CTkLabel(
            self,
            text=(
                "3. Вставьте API-ключ ниже и нажмите «Проверить ключ и загрузить модели».\n"
                "4. Отметьте нужные модели (например, Claude 3.7/3.5 Sonnet, Gemini Pro, GPT-4o) и нажмите «Добавить выбранные в OpenCode».\n\n"
                "Выбранные модели появятся в провайдере MWAPI в OpenCode. Запросы будут направляться на шлюз "
                "https://api.mwapi.dev/v1 с вашим лимитом на Cloud Code."
            ),
            anchor="w",
            justify="left",
            wraplength=760,
            font=app.font(13),
        ).pack(fill="x", pady=(4, 14))

        self.key_entry = ctk.CTkEntry(self, placeholder_text="sk-…", show="•", height=38)
        self.key_entry.pack(fill="x", pady=(0, 8))

        actions = ctk.CTkFrame(self, fg_color="transparent")
        actions.pack(fill="x", pady=(0, 10))

        self.connect_button = ctk.CTkButton(
            actions,
            text="Проверить ключ и загрузить модели",
            command=self.load_models,
        )
        self.connect_button.pack(side="left", padx=(0, 8))

        self.select_all_button = ctk.CTkButton(
            actions,
            text="Выбрать все",
            width=100,
            command=self.toggle_all_models,
            state="disabled",
            fg_color=("#e2e8f0", "#334155"),
            text_color=colors["text_primary"],
            hover_color=("#cbd5e1", "#475569"),
        )
        self.select_all_button.pack(side="left", padx=(0, 8))

        self.apply_button = ctk.CTkButton(
            actions,
            text="Добавить выбранные в OpenCode",
            command=self.apply_models,
            state="disabled",
        )
        self.apply_button.pack(side="left", padx=(0, 8))

        self.disconnect_button = ctk.CTkButton(
            actions,
            text="Отключить",
            command=self.disconnect,
            fg_color="#b91c1c",
            hover_color="#991b1b",
        )
        self.disconnect_button.pack(side="left")

        # --- Quota and Limits Card (via API key) ---
        self.quota_card = ctk.CTkFrame(
            self,
            fg_color=colors["card_bg"],
            corner_radius=8,
            border_width=1,
            border_color=colors["border"],
        )
        self.quota_card.pack(fill="x", pady=(0, 12))

        q_header = ctk.CTkFrame(self.quota_card, fg_color="transparent")
        q_header.pack(fill="x", padx=16, pady=(12, 8))

        ctk.CTkLabel(
            q_header,
            text="Лимиты и расход MWAPI",
            font=app.font(14, "bold"),
            text_color=colors["text_primary"],
        ).pack(side="left")

        self.quota_badge = ctk.CTkLabel(
            q_header,
            text="",
            font=app.font(11),
            text_color=colors["text_secondary"],
        )
        self.quota_badge.pack(side="left", padx=(10, 0))

        self.refresh_quota_button = ctk.CTkButton(
            q_header,
            text="Обновить лимиты",
            width=125,
            height=28,
            command=self.refresh_usage,
            fg_color=("#e2e8f0", "#334155"),
            text_color=colors["text_primary"],
            hover_color=("#cbd5e1", "#475569"),
            font=app.font(12),
        )
        self.refresh_quota_button.pack(side="right")

        bar_header = ctk.CTkFrame(self.quota_card, fg_color="transparent")
        bar_header.pack(fill="x", padx=16, pady=(0, 4))

        self.quota_bar_title = ctk.CTkLabel(
            bar_header,
            text="Остаток квоты",
            font=app.font(11, "bold"),
            text_color=colors["text_secondary"],
        )
        self.quota_bar_title.pack(side="left")

        self.quota_bar_pct = ctk.CTkLabel(
            bar_header,
            text="—",
            font=app.font(11, "bold"),
            text_color=colors["text_primary"],
        )
        self.quota_bar_pct.pack(side="right")

        self.quota_bar = ctk.CTkProgressBar(self.quota_card, height=8, corner_radius=4)
        self.quota_bar.pack(fill="x", padx=16, pady=(0, 12))
        self.quota_bar.set(0.0)
        self.quota_bar.configure(progress_color="#10b981", fg_color=colors["bar_bg"])

        metrics_container = ctk.CTkFrame(self.quota_card, fg_color="transparent")
        metrics_container.pack(fill="x", padx=16, pady=(0, 14))
        metrics_container.columnconfigure((0, 1, 2, 3), weight=1, uniform="stat_col")

        def make_col(col_idx, label):
            box = ctk.CTkFrame(metrics_container, fg_color=colors["subbox_bg"], corner_radius=6)
            box.grid(row=0, column=col_idx, padx=4, sticky="nsew")
            lbl = ctk.CTkLabel(box, text=label, font=app.font(11), text_color=colors["text_secondary"])
            lbl.pack(anchor="w", padx=10, pady=(8, 2))
            val = ctk.CTkLabel(box, text="—", font=app.font(16, "bold"), text_color=colors["text_primary"])
            val.pack(anchor="w", padx=10, pady=(0, 2))
            sub = ctk.CTkLabel(box, text="", font=app.font(10), text_color=colors["text_muted"])
            sub.pack(anchor="w", padx=10, pady=(0, 8))
            return val, sub

        self.val_remaining, self.sub_remaining = make_col(0, "Осталось")
        self.val_used, self.sub_used = make_col(1, "Израсходовано")
        self.val_limit, self.sub_limit = make_col(2, "Лимит аккаунта")
        self.val_activity, self.sub_activity = make_col(3, "Сегодня")

        # Subscription / last refresh line
        info_row = ctk.CTkFrame(self.quota_card, fg_color="transparent")
        info_row.pack(fill="x", padx=16, pady=(0, 8))
        self.quota_info = ctk.CTkLabel(
            info_row,
            text="Лимиты ещё не загружены.",
            font=app.font(11),
            text_color=colors["text_muted"],
            anchor="w",
            justify="left",
            wraplength=720,
        )
        self.quota_info.pack(side="left")

        # Per-model spend breakdown
        model_usage_header = ctk.CTkFrame(self.quota_card, fg_color="transparent")
        model_usage_header.pack(fill="x", padx=16, pady=(2, 4))

        ctk.CTkLabel(
            model_usage_header,
            text="Расход по моделям",
            font=app.font(11, "bold"),
            text_color=colors["text_secondary"],
        ).pack(side="left")

        self.model_usage_hint = ctk.CTkLabel(
            model_usage_header,
            text="",
            font=app.font(10),
            text_color=colors["text_muted"],
        )
        self.model_usage_hint.pack(side="right")

        table_head = ctk.CTkFrame(self.quota_card, fg_color="transparent")
        table_head.pack(fill="x", padx=24, pady=(0, 2))
        table_head.grid_columnconfigure(0, weight=1)

        for column, (text, width, anchor) in enumerate((
            ("Модель", 160, "w"),
            ("Запросы", 70, "e"),
            ("Токены", 110, "e"),
            ("Списано", 90, "e"),
        )):
            ctk.CTkLabel(
                table_head,
                text=text,
                font=app.font(10, "bold"),
                text_color=colors["text_muted"],
                width=width,
                anchor=anchor,
            ).grid(row=0, column=column, sticky=anchor)

        self.model_usage_list = ctk.CTkScrollableFrame(
            self.quota_card, height=140, fg_color=colors["subbox_bg"], corner_radius=6,
        )
        self.model_usage_list.pack(fill="x", padx=16, pady=(0, 12))

        self.status = ctk.CTkLabel(
            self,
            text="Ключ хранится локально в защищённом виде.",
            anchor="w",
            justify="left",
            wraplength=760,
        )
        self.status.pack(fill="x", pady=(0, 8))

        ctk.CTkLabel(
            self,
            text="Доступные модели MWAPI:",
            anchor="w",
            font=app.font(14, "bold"),
            text_color=colors["text_primary"],
        ).pack(fill="x", pady=(4, 6))

        self.model_list = ctk.CTkScrollableFrame(self, height=300, fg_color=colors["card_bg"])
        self.model_list.pack(fill="both", expand=True, pady=(0, 8))

        # --- Dashboard Session Section (Optional DevTools JWT Token) ---
        ctk.CTkLabel(
            self,
            text="Баланс профиля (через access_token кабинета)",
            font=app.font(15, "bold"),
            anchor="w",
        ).pack(fill="x", pady=(14, 4))

        ctk.CTkLabel(
            self,
            text=(
                "Опционально: если вы хотите увидеть состояние профиля пользователя напрямую из личного кабинета MWAPI, "
                "вы можете указать access_token из DevTools Network (запрос login):"
            ),
            anchor="w",
            justify="left",
            wraplength=760,
            font=app.font(12),
            text_color=colors["text_secondary"],
        ).pack(fill="x", pady=(0, 6))

        self.token_entry = ctk.CTkEntry(self, placeholder_text="access_token из кабинета MWAPI…", show="•", height=36)
        self.token_entry.pack(fill="x", pady=(0, 6))

        balance_actions = ctk.CTkFrame(self, fg_color="transparent")
        balance_actions.pack(fill="x", pady=(0, 6))

        self.balance_button = ctk.CTkButton(
            balance_actions,
            text="Показать баланс профиля",
            command=self.load_balance,
        )
        self.balance_button.pack(side="left", padx=(0, 8))

        self.forget_token_button = ctk.CTkButton(
            balance_actions,
            text="Забыть токен",
            width=120,
            command=self.forget_token,
            fg_color=("#e2e8f0", "#334155"),
            text_color=colors["text_primary"],
            hover_color=("#cbd5e1", "#475569"),
        )
        self.forget_token_button.pack(side="left")

        self.balance_status = ctk.CTkLabel(
            self,
            text="Баланс профиля ещё не запрошен.",
            anchor="w",
            justify="left",
            wraplength=760,
        )
        self.balance_status.pack(fill="x", pady=(0, 8))

        # Load saved secrets
        saved_key = mwapi_manager.load_api_key()
        if saved_key:
            self.key_entry.insert(0, saved_key)
            self.app.after(400, lambda: self.refresh_usage(silent=True))

        saved_token = mwapi_manager.load_dashboard_token()
        if saved_token:
            self.token_entry.insert(0, saved_token)

    @staticmethod
    def _format_currency(val, unit="USD"):
        if val is None:
            return "—"
        if unit == "USD":
            return f"${val:,.2f}"
        return f"{val:,.2f} {unit}"

    @staticmethod
    def _format_number(value):
        try:
            return f"{int(value):,}".replace(",", " ")
        except (TypeError, ValueError):
            return "—"

    def _clear_model_usage(self):
        for widget in self.model_usage_list.winfo_children():
            widget.destroy()
        self.model_usage_hint.configure(text="")

    def _render_model_usage(self, models):
        self._clear_model_usage()
        if not models:
            return
        unit = "USD"
        for model in models[:20]:
            row = ctk.CTkFrame(self.model_usage_list, fg_color="transparent")
            row.pack(fill="x", padx=6, pady=1)
            row.grid_columnconfigure(0, weight=1)

            ctk.CTkLabel(
                row, text=model.get("model", "—"), anchor="w",
                font=self.app.font(11), text_color=self.colors["text_primary"],
            ).grid(row=0, column=0, sticky="w")
            ctk.CTkLabel(
                row, text=self._format_number(model.get("requests", 0)), width=70, anchor="e",
                font=self.app.font(11), text_color=self.colors["text_secondary"],
            ).grid(row=0, column=1, sticky="e")
            ctk.CTkLabel(
                row, text=self._format_number(model.get("total_tokens", 0)), width=110, anchor="e",
                font=self.app.font(11), text_color=self.colors["text_secondary"],
            ).grid(row=0, column=2, sticky="e")
            ctk.CTkLabel(
                row, text=self._format_currency(model.get("actual_cost") or model.get("cost"), unit),
                width=90, anchor="e", font=self.app.font(11, "bold"),
                text_color=self.colors["text_primary"],
            ).grid(row=0, column=3, sticky="e")

        if len(models) > 20:
            self.model_usage_hint.configure(text=f"показано 20 из {len(models)}")
        else:
            self.model_usage_hint.configure(text=f"всего: {len(models)}")

    def update_quota_display(self, usage: dict):
        if not usage or not isinstance(usage, dict):
            self.quota_badge.configure(text="")
            self.quota_bar_pct.configure(text="—")
            self.quota_bar.set(0.0)
            self.val_remaining.configure(text="—", text_color=self.colors["text_primary"])
            self.sub_remaining.configure(text="")
            self.val_used.configure(text="—")
            self.sub_used.configure(text="")
            self.val_limit.configure(text="—")
            self.sub_limit.configure(text="")
            self.val_activity.configure(text="—")
            self.sub_activity.configure(text="")
            self.quota_info.configure(text="Лимиты ещё не загружены.")
            self._clear_model_usage()
            return

        unit = usage.get("unit", "USD")
        limit = usage.get("limit")
        used = usage.get("used")
        remaining = usage.get("remaining")
        rem_pct = usage.get("rem_pct")
        used_pct = usage.get("used_pct")
        mode = usage.get("mode") or ""
        status = usage.get("status") or "active"
        today = usage.get("today") or {}
        total = usage.get("total") or {}

        mode_label = f"тариф: {mode}" if mode else ""
        status_label = "Активен" if status == "active" else status
        self.quota_badge.configure(text=f"[{status_label}{(' · ' + mode_label) if mode_label else ''}]")

        rem_text = self._format_currency(remaining, unit)
        used_text = self._format_currency(used, unit)
        lim_text = self._format_currency(limit, unit) if limit is not None else "Безлимит"

        self.val_remaining.configure(text=rem_text)
        if rem_pct is not None:
            self.sub_remaining.configure(text=f"{rem_pct:.1f}% доступно")
            self.quota_bar_pct.configure(text=f"{rem_pct:.1f}% осталось")
            self.quota_bar.set(max(0.0, min(1.0, rem_pct / 100.0)))
            if rem_pct >= 30:
                bar_color = "#10b981"
                self.val_remaining.configure(text_color=("#059669", "#10b981"))
            elif rem_pct >= 10:
                bar_color = "#f59e0b"
                self.val_remaining.configure(text_color=("#d97706", "#f59e0b"))
            else:
                bar_color = "#ef4444"
                self.val_remaining.configure(text_color=("#dc2626", "#ef4444"))
            self.quota_bar.configure(progress_color=bar_color)
        else:
            self.sub_remaining.configure(text="")
            self.quota_bar_pct.configure(text="—")
            self.quota_bar.set(1.0 if remaining else 0.0)

        self.val_used.configure(text=used_text)
        if used_pct is not None:
            self.sub_used.configure(
                text=f"{used_pct:.1f}% лимита · {self._format_number(total.get('requests', 0))} запр."
            )
        else:
            self.sub_used.configure(text="")

        self.val_limit.configure(text=lim_text)
        if limit is not None:
            self.sub_limit.configure(text=mode or "Выделенный лимит")
        else:
            self.sub_limit.configure(text="Без фиксированного лимита")

        self.val_activity.configure(text=self._format_currency(today.get("actual_cost") or today.get("cost"), unit))
        self.sub_activity.configure(
            text=(
                f"{self._format_number(today.get('requests', 0))} запр. · "
                f"{self._format_number(today.get('total_tokens', 0))} токенов"
            )
        )

        details = [f"Обновлено: {datetime.now().strftime('%H:%M:%S')}"]
        if usage.get("expires_at"):
            details.append(f"действует до {str(usage['expires_at'])[:10]}")
        total_cost = total.get("actual_cost") or total.get("cost")
        if total_cost:
            details.append(f"всего списано: {self._format_currency(total_cost, unit)}")
        details.append(f"токенов за всё время: {self._format_number(total.get('total_tokens', 0))}")
        self.quota_info.configure(text="  ·  ".join(details))

        self._render_model_usage(usage.get("models") or [])

    def on_show(self):
        key = self.key_entry.get().strip()
        if not key:
            return
        if time.monotonic() - self._last_usage_refresh < AUTO_REFRESH_SECONDS:
            return
        self.refresh_usage(silent=True)

    def refresh_usage(self, silent=False):
        key = self.key_entry.get().strip()
        if not key:
            if not silent:
                messagebox.showwarning("MWAPI", "Сначала вставьте API-ключ MWAPI.", parent=self.app)
            return
        if self._usage_loading:
            return

        self._usage_loading = True
        self.refresh_quota_button.configure(state="disabled", text="Обновление…")
        self.quota_info.configure(text="Загрузка лимитов MWAPI…")

        def worker():
            try:
                usage = mwapi_manager.fetch_usage(key)
                self.app.after(0, lambda u=usage: self._usage_refreshed(u))
            except Exception as error:
                err_msg = str(error).strip() or type(error).__name__
                self.app.after(0, lambda m=err_msg: self._usage_refresh_failed(m, silent))

        threading.Thread(target=worker, name="hub-mwapi-usage", daemon=True).start()

    def _usage_refreshed(self, usage):
        self._usage_loading = False
        self._last_usage_refresh = time.monotonic()
        self.refresh_quota_button.configure(state="normal", text="Обновить лимиты")
        self.update_quota_display(usage)

    def _usage_refresh_failed(self, message, silent=False):
        self._usage_loading = False
        self.refresh_quota_button.configure(state="normal", text="Обновить лимиты")
        self.quota_info.configure(text=f"Не удалось загрузить лимиты: {message}")
        if not silent:
            messagebox.showwarning("MWAPI", f"Не удалось обновить данные лимитов: {message}", parent=self.app)

    def _instruction_link(self, text, url):
        link = ctk.CTkLabel(
            self,
            text=text,
            anchor="w",
            text_color=("#1769aa", "#67b7ff"),
            cursor="hand2",
            font=self.app.font(13, underline=True),
        )
        link.pack(fill="x", pady=(4, 0))
        link.bind("<Button-1>", lambda _event, address=url: webbrowser.open(address))

    def _busy(self, state, message=None):
        self.connect_button.configure(state="disabled" if state else "normal")
        self.apply_button.configure(state="disabled" if state or not self.checkboxes else "normal")
        self.select_all_button.configure(state="disabled" if state or not self.checkboxes else "normal")
        self.disconnect_button.configure(state="disabled" if state else "normal")
        self.refresh_quota_button.configure(state="disabled" if state else "normal")
        self.key_entry.configure(state="disabled" if state else "normal")
        self.balance_button.configure(state="disabled" if state else "normal")
        self.forget_token_button.configure(state="disabled" if state else "normal")
        self.token_entry.configure(state="disabled" if state else "normal")
        if message:
            self.status.configure(text=message)

    def _run(self, operation, success, busy_message="Подключение к MWAPI…", on_error=None):
        self._busy(True, busy_message)

        def worker():
            try:
                result = operation()
                self.app.after(0, lambda value=result: success(value))
            except Exception as error:
                error_text = str(error).strip() or type(error).__name__
                self.app.after(0, lambda message=error_text: (on_error or self._failed)(message))

        threading.Thread(target=worker, name="hub-mwapi", daemon=True).start()

    def _failed(self, message):
        self._busy(False)
        self.status.configure(text=message)
        messagebox.showerror("MWAPI", message, parent=self.app)

    def _balance_failed(self, message):
        self._busy(False)
        self.balance_status.configure(text=message)
        messagebox.showerror("MWAPI", message, parent=self.app)

    def load_models(self):
        key = self.key_entry.get().strip()
        if not key:
            messagebox.showwarning("MWAPI", "Сначала вставьте API-ключ MWAPI.", parent=self.app)
            return

        def operation():
            models = mwapi_manager.fetch_models(key)
            if not models:
                raise ValueError("В аккаунте MWAPI не найдены доступные модели.")
            mwapi_manager.sync_opencode_credential(key)
            mwapi_manager.save_api_key(key)
            usage = None
            try:
                usage = mwapi_manager.fetch_usage(key)
            except Exception:
                pass
            return {"models": models, "usage": usage}

        self._run(operation, self._models_loaded)

    def _models_loaded(self, data):
        if isinstance(data, dict):
            models = data.get("models", [])
            usage = data.get("usage")
        else:
            models = data
            usage = None

        if usage:
            self.update_quota_display(usage)

        self.models = models
        for widget in self.model_list.winfo_children():
            widget.destroy()
        self.checkboxes.clear()

        for model in models:
            label = f"{model['name']}  ·  {model['id']}  ·  контекст {model['context']:,}"
            checkbox = ctk.CTkCheckBox(self.model_list, text=label)
            checkbox.pack(anchor="w", fill="x", padx=10, pady=5)
            checkbox.select()
            self.checkboxes.append((model, checkbox))

        self.select_all_button.configure(state="normal", text="Снять все")
        self._busy(False, f"Ключ MWAPI проверен. Найдено моделей: {len(models)}. Выберите нужные для добавления.")

    def toggle_all_models(self):
        if not self.checkboxes:
            return
        all_selected = all(cb.get() for _, cb in self.checkboxes)
        for _, cb in self.checkboxes:
            if all_selected:
                cb.deselect()
            else:
                cb.select()
        self.select_all_button.configure(text="Выбрать все" if all_selected else "Снять все")

    def apply_models(self):
        selected = [model for model, checkbox in self.checkboxes if checkbox.get()]
        if not selected:
            messagebox.showwarning("MWAPI", "Выберите хотя бы одну модель.", parent=self.app)
            return

        key = self.key_entry.get().strip()

        def operation():
            mwapi_manager.configure_models(selected, api_key=key)
            return len(selected)

        self._run(operation, lambda count: self._applied(count))

    def _applied(self, count):
        self._busy(False, f"В OpenCode добавлено моделей MWAPI: {count}. Перезапустите OpenCode или обновите список моделей.")
        messagebox.showinfo(
            "MWAPI",
            f"Успешно настроено {count} моделей MWAPI!\nВ OpenCode выберите провайдер «MWAPI (Cloud Code)» или модели с префиксом mwapi/.",
            parent=self.app,
        )

    def disconnect(self):
        if not messagebox.askyesno("MWAPI", "Удалить настройки MWAPI, сохранённый ключ и токен баланса?", parent=self.app):
            return
        self._run(mwapi_manager.disconnect, lambda _result: self._disconnected())

    def _disconnected(self):
        self.key_entry.configure(state="normal")
        self.key_entry.delete(0, "end")
        self.token_entry.configure(state="normal")
        self.token_entry.delete(0, "end")
        for widget in self.model_list.winfo_children():
            widget.destroy()
        self.checkboxes.clear()
        self.select_all_button.configure(state="disabled", text="Выбрать все")
        self.update_quota_display({})
        self.balance_status.configure(text="Баланс ещё не запрошен.")
        self._busy(False, "MWAPI отключён. Конфигурация провайдера удалена из OpenCode.")

    def load_balance(self):
        token = self.token_entry.get().strip()
        if not token:
            messagebox.showwarning("MWAPI", "Сначала вставьте access_token из кабинета MWAPI.", parent=self.app)
            return

        def operation():
            info = mwapi_manager.fetch_balance(token)
            mwapi_manager.save_dashboard_token(token)
            return info

        self._run(
            operation,
            self._balance_loaded,
            busy_message="Запрашиваю баланс MWAPI…",
            on_error=self._balance_failed,
        )

    def _balance_loaded(self, info):
        text = (
            f"Баланс: {info['balance']:.2f} $"
            f"  ·  заморожено: {info['frozen_balance']:.2f} $"
            f"  ·  всего пополнено: {info['total_recharged']:.2f} $"
        )
        if info.get("email"):
            text += f"  ·  аккаунт: {info['email']}"
        self._busy(False, None)
        self.balance_status.configure(text=text)

    def forget_token(self):
        mwapi_manager.clear_dashboard_token()
        self.token_entry.configure(state="normal")
        self.token_entry.delete(0, "end")
        self.balance_status.configure(text="Токен удалён. Баланс ещё не запрошен.")
