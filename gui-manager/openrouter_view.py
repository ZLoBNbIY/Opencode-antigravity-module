"""OpenRouter Free setup and model selection for Antigravity Hub."""
import threading
import webbrowser
from tkinter import messagebox

import customtkinter as ctk
import openrouter_manager


class OpenRouterView(ctk.CTkScrollableFrame):
    def __init__(self, parent, app, colors):
        super().__init__(parent, fg_color=colors["bg"], corner_radius=0)
        self.app = app
        self.colors = colors
        self.models = []
        self.checkboxes = []
        ctk.CTkLabel(self, text="OpenRouter Free", font=app.font(22, "bold"), anchor="w").pack(fill="x", pady=(0, 12))
        ctk.CTkLabel(self, text="Чтобы подключить бесплатные модели OpenRouter:", anchor="w", font=app.font(13)).pack(fill="x")
        self._instruction_link("1. Зарегистрируйтесь или войдите на openrouter.ai.", "https://openrouter.ai/")
        ctk.CTkLabel(
            self,
            text="2. Откройте страницу API-ключей и создайте ключ (Create API Key). Создание ключа бесплатно; бесплатные модели доступны в пределах квот OpenRouter.",
            anchor="w", justify="left", wraplength=760, font=app.font(13),
        ).pack(fill="x", pady=(4, 0))
        self._instruction_link("Открыть страницу API-ключей OpenRouter", "https://openrouter.ai/settings/keys")
        ctk.CTkLabel(
            self,
            text=(
                "3. Вставьте ключ ниже и нажмите «Проверить ключ и загрузить модели».\n"
                "4. Отметьте нужные бесплатные модели и нажмите «Добавить выбранные в OpenCode».\n\n"
                "Выбранные модели появятся в отдельном провайдере OpenRouter Free. Встроенный провайдер "
                "OpenRouter отключится, чтобы его общий каталог платных моделей не отображался; при отключении "
                "интеграции встроенный провайдер включится снова. Доступность, бесплатные квоты и состав каталога "
                "задаёт OpenRouter, и они могут меняться."
            ),
            anchor="w", justify="left", wraplength=760, font=app.font(13),
        ).pack(fill="x", pady=(4, 14))

        self.key_entry = ctk.CTkEntry(self, placeholder_text="sk-or-v1-…", show="•", height=38)
        self.key_entry.pack(fill="x", pady=(0, 8))
        saved_key = openrouter_manager.load_api_key()
        if saved_key:
            self.key_entry.insert(0, saved_key)

        actions = ctk.CTkFrame(self, fg_color="transparent")
        actions.pack(fill="x", pady=(0, 10))
        self.connect_button = ctk.CTkButton(actions, text="Проверить ключ и загрузить модели", command=self.load_models)
        self.connect_button.pack(side="left", padx=(0, 8))
        self.apply_button = ctk.CTkButton(actions, text="Добавить выбранные в OpenCode", command=self.apply_models, state="disabled")
        self.apply_button.pack(side="left", padx=(0, 8))
        self.disconnect_button = ctk.CTkButton(actions, text="Отключить", command=self.disconnect, fg_color="#b91c1c", hover_color="#991b1b")
        self.disconnect_button.pack(side="left")

        self.status = ctk.CTkLabel(self, text="Ключ хранится локально в защищённом виде.", anchor="w", justify="left", wraplength=760)
        self.status.pack(fill="x", pady=(0, 8))
        self.model_list = ctk.CTkScrollableFrame(self, height=320, fg_color=colors["card_bg"])
        self.model_list.pack(fill="both", expand=True, pady=(0, 8))

    def _instruction_link(self, text, url):
        link = ctk.CTkLabel(
            self, text=text, anchor="w", text_color=("#1769aa", "#67b7ff"),
            cursor="hand2", font=self.app.font(13, underline=True),
        )
        link.pack(fill="x", pady=(4, 0))
        link.bind("<Button-1>", lambda _event, address=url: webbrowser.open(address))

    def _busy(self, state, message=None):
        self.connect_button.configure(state="disabled" if state else "normal")
        self.apply_button.configure(state="disabled" if state or not self.checkboxes else "normal")
        self.disconnect_button.configure(state="disabled" if state else "normal")
        self.key_entry.configure(state="disabled" if state else "normal")
        if message:
            self.status.configure(text=message)

    def _run(self, operation, success):
        self._busy(True, "Подключение к OpenRouter…")

        def worker():
            try:
                result = operation()
                self.app.after(0, lambda value=result: success(value))
            except Exception as error:
                error_text = str(error).strip() or type(error).__name__
                self.app.after(0, lambda message=error_text: self._failed(message))

        threading.Thread(target=worker, name="hub-openrouter", daemon=True).start()

    def _failed(self, message):
        self._busy(False)
        self.status.configure(text=message)
        messagebox.showerror("OpenRouter", message, parent=self.app)

    def load_models(self):
        key = self.key_entry.get().strip()
        if not key:
            messagebox.showwarning("OpenRouter", "Сначала вставьте API-ключ OpenRouter.", parent=self.app)
            return

        def operation():
            models = openrouter_manager.fetch_free_models(key)
            if not models:
                raise ValueError("В каталоге OpenRouter сейчас не найдены бесплатные текстовые модели.")
            openrouter_manager.sync_opencode_credential(key)
            openrouter_manager.save_api_key(key)
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
        self._busy(False, f"Ключ OpenRouter проверен. Найдено бесплатных текстовых моделей: {len(models)}. Снимите отметки с ненужных.")

    def apply_models(self):
        selected = [model for model, checkbox in self.checkboxes if checkbox.get()]
        if not selected:
            messagebox.showwarning("OpenRouter", "Выберите хотя бы одну модель.", parent=self.app)
            return

        def operation():
            openrouter_manager.configure_models(selected)
            return len(selected)

        self._run(operation, lambda count: self._applied(count))

    def _applied(self, count):
        self._busy(False, f"В OpenCode добавлено моделей: {count}. Перезапустите OpenCode или обновите список моделей.")

    def disconnect(self):
        if not messagebox.askyesno("OpenRouter", "Удалить сохранённый ключ OpenRouter из Hub и OpenCode?", parent=self.app):
            return
        self._run(openrouter_manager.disconnect, lambda _result: self._disconnected())

    def _disconnected(self):
        self.key_entry.configure(state="normal")
        self.key_entry.delete(0, "end")
        for widget in self.model_list.winfo_children():
            widget.destroy()
        self.checkboxes.clear()
        self._busy(False, "OpenRouter отключён. Определения моделей в конфигурации OpenCode оставлены без ключа.")
