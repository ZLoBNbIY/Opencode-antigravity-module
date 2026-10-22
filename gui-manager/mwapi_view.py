"""MWAPI (Cloud Code / CCS) setup and model selection for Antigravity Hub."""
import threading
import webbrowser
from tkinter import messagebox

import customtkinter as ctk
import mwapi_manager


class MwapiView(ctk.CTkScrollableFrame):
    def __init__(self, parent, app, colors):
        super().__init__(parent, fg_color=colors["bg"], corner_radius=0)
        self.app = app
        self.colors = colors
        self.models = []
        self.checkboxes = []

        ctk.CTkLabel(
            self,
            text="MWAPI (Cloud Code / CCS)",
            font=app.font(22, "bold"),
            anchor="w",
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
        saved_key = mwapi_manager.load_api_key()
        if saved_key:
            self.key_entry.insert(0, saved_key)

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

        self.status = ctk.CTkLabel(
            self,
            text="Ключ хранится локально в защищённом виде.",
            anchor="w",
            justify="left",
            wraplength=760,
        )
        self.status.pack(fill="x", pady=(0, 8))

        self.model_list = ctk.CTkScrollableFrame(self, height=320, fg_color=colors["card_bg"])
        self.model_list.pack(fill="both", expand=True, pady=(0, 8))

        ctk.CTkLabel(
            self,
            text="Баланс и расход токенов",
            font=app.font(16, "bold"),
            anchor="w",
        ).pack(fill="x", pady=(16, 6))

        ctk.CTkLabel(
            self,
            text=(
                "Баланс доступен только через личный кабинет MWAPI (sk-ключ его не показывает). "
                "Войдите на https://api.mwapi.dev, откройте DevTools → вкладка Network, выполните вход "
                "и найдите запрос login — в его ответе будет поле access_token. Скопируйте его значение "
                "ниже и нажмите «Показать баланс»."
            ),
            anchor="w",
            justify="left",
            wraplength=760,
            font=app.font(13),
        ).pack(fill="x", pady=(0, 8))

        self._instruction_link(
            "Открыть личный кабинет MWAPI для входа.",
            "https://api.mwapi.dev/dashboard",
        )

        self.token_entry = ctk.CTkEntry(self, placeholder_text="access_token из кабинета MWAPI…", show="•", height=38)
        self.token_entry.pack(fill="x", pady=(8, 8))
        saved_token = mwapi_manager.load_dashboard_token()
        if saved_token:
            self.token_entry.insert(0, saved_token)

        balance_actions = ctk.CTkFrame(self, fg_color="transparent")
        balance_actions.pack(fill="x", pady=(0, 10))

        self.balance_button = ctk.CTkButton(
            balance_actions,
            text="Показать баланс",
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
            text="Баланс ещё не запрошен.",
            anchor="w",
            justify="left",
            wraplength=760,
        )
        self.balance_status.pack(fill="x", pady=(0, 8))

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
            return models

        self._run(operation, self._models_loaded)

    def _models_loaded(self, models):
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
