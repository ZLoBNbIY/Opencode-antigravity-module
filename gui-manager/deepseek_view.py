"""Single-button web-chat connection; installed Chrome/Edge, no runtime installer."""
import queue
import threading
import time
from tkinter import messagebox
import customtkinter as ctk
from deepseek_manager import DeepSeekManager, MODELS, PROVIDER_ID


class DeepSeekView(ctk.CTkScrollableFrame):
    def __init__(self, parent, app, colors):
        super().__init__(parent, fg_color=colors["bg"], corner_radius=0)
        self.app, self.manager = app, DeepSeekManager()
        self.events = queue.Queue()
        self.busy = self.closed = False
        self.operation = None
        self.buttons = []
        self._poll_id = None
        self._next_status_refresh = 0
        ctk.CTkLabel(self, text="DeepSeek · chat.deepseek.com", font=app.font(22, "bold"), anchor="w").pack(fill="x", pady=(0, 12))
        ctk.CTkLabel(self, text="Используется веб-сессия, не платный API и не аккаунт Harness.\n"
                     "Браузер нужен только для разового входа; после сохранения сессии Hub его закроет.\n"
                     "Запросы идут напрямую по HTTPS и появятся в истории chat.deepseek.com.",
                     anchor="w", justify="left", wraplength=760).pack(fill="x", pady=(0, 14))
        self.status_label = ctk.CTkLabel(self, text="", font=app.font(16, "bold"), anchor="w", justify="left", wraplength=760)
        self.status_label.pack(fill="x", pady=(0, 12))
        self.add_row([
            ("+ Войти в DeepSeek Web", self.login_action),
            ("Открыть веб-чат", lambda: self.run_action(self.manager.show_chat, "browser")),
            ("Отключить", self.logout_action),
        ])
        self.cancel_button = ctk.CTkButton(self, text="Отменить вход", command=self.cancel_action, state="disabled")
        self.cancel_button.pack(anchor="w", pady=(0, 12))
        ctk.CTkLabel(self, text="Модели OpenCode: DeepSeek Web Instant / Expert. Ограничения определяет веб-чат.\n"
                     "Tool calling эмулируется; сложные агентные цепочки могут работать менее надёжно.\n"
                     "Каждый запрос создаёт веб-диалог и передаёт его текст (включая контекст файлов) в DeepSeek.",
                     anchor="w", justify="left", wraplength=760).pack(fill="x", pady=(0, 12))
        self.result_label = ctk.CTkLabel(self, text=self.manager.storage_warning or "Войдите один раз; затем Hub закроет окно браузера и будет обращаться напрямую.", anchor="w", justify="left", wraplength=760)
        self.result_label.pack(fill="x", pady=(0, 14))
        ctk.CTkButton(self, text="Диагностика", command=self.toggle_diagnostics).pack(anchor="w", pady=(0, 8))
        self.diagnostics = ctk.CTkFrame(self, fg_color=colors["card_bg"])
        self.browser_menu = ctk.CTkOptionMenu(self.diagnostics, values=["Системный браузер", "Автоматически", "Chrome", "Edge"])
        self.browser_menu.set({"auto": "Автоматически", "default": "Системный браузер", "chrome": "Chrome", "edge": "Edge"}[self.manager.state["browser"]])
        self.browser_menu.pack(anchor="w", padx=12, pady=12)
        self.model_menu = ctk.CTkOptionMenu(self.diagnostics, values=list(MODELS))
        self.model_menu.pack(anchor="w", padx=12, pady=(0, 12))
        self.add_row([
            ("Проверить сохранённую сессию", lambda: self.run_action(self.manager.refresh_details, "check")),
            ("Тест генерации", lambda: self.test_action(False)),
            ("Тест инструментов", lambda: self.test_action(True)),
        ], self.diagnostics)
        self.add_row([
            ("Повторить подключение OpenCode", lambda: self.run_action(self.manager.restore, "configure")),
            ("Модель по умолчанию", self.default_model_action),
            ("Лог", self.show_logs),
        ], self.diagnostics)
        self.logs = ctk.CTkTextbox(self.diagnostics, height=140, wrap="word")
        self.logs.pack(fill="x", padx=12, pady=12)
        self.logs.configure(state="disabled")
        self.update_status()
        self._poll_id = self.after(150, self.poll_events)
        if self.manager.needs_restore():
            self.after(0, lambda: self.run_action(self.manager.restore, "configure"))

    def add_row(self, actions, parent=None):
        row = ctk.CTkFrame(parent or self, fg_color="transparent")
        row.pack(fill="x", pady=(0, 8), padx=12 if parent else 0)
        for index, (label, command) in enumerate(actions):
            row.grid_columnconfigure(index, weight=1)
            button = ctk.CTkButton(row, text=label, command=command, height=36)
            button.grid(row=0, column=index, sticky="ew", padx=(0, 8))
            self.buttons.append(button)

    def update_status(self):
        state = self.manager.snapshot()
        if not state["signedIn"]:
            text = "Веб-сессия не подключена. Данные Harness не используются."
        else:
            text = "Веб-сессия сохранена · " + ("браузер открыт для входа" if state["browserRunning"] else "общение идёт напрямую по HTTPS")
            text += "\n" + ("Канал OpenCode работает" if state["connected"] else "Канал пока не запущен")
        if state["lastError"]:
            text += "\n" + state["lastError"]
        self.status_label.configure(text=text)

    def login_action(self):
        if self.busy or self.closed:
            return
        selected = {"Системный браузер": "default", "Автоматически": "auto", "Chrome": "chrome", "Edge": "edge"}[self.browser_menu.get()]
        try:
            self.manager.set_browser(selected)
        except ValueError as error:
            messagebox.showerror("DeepSeek Web", str(error), parent=self.app)
            return
        cancel = self.manager.prepare_login()
        self.run_action(lambda: self.manager.login(lambda text: self.events.put(("progress", text)), cancel=cancel), "login")

    def cancel_action(self):
        cancelled = self.manager.cancel_login()
        self.result_label.configure(text="Вход отменяется." if cancelled else "Вход уже сохранён.")
        self.cancel_button.configure(state="disabled")

    def logout_action(self):
        if messagebox.askyesno("DeepSeek Web", "Отключить веб-сессию от OpenCode и закрыть браузерный профиль Hub?\nОбычные окна браузера и сохранённые данные не удаляются.", parent=self.app):
            self.run_action(self.manager.logout, "logout")

    def default_model_action(self):
        model = self.model_menu.get()
        if messagebox.askyesno("OpenCode", f"Использовать {PROVIDER_ID}/{model} по умолчанию для новых сессий?", parent=self.app):
            self.run_action(lambda: self.manager.configure_opencode(model), "configure")

    def test_action(self, tools):
        if messagebox.askyesno("DeepSeek Web", "Тест отправит короткое сообщение в веб-чат и расходует его лимит. Инструменты на ПК не выполняются. Продолжить?", parent=self.app):
            model = self.model_menu.get()
            self.run_action(lambda: self.manager.test_generation(model, tools), "test")

    def run_action(self, operation, label):
        if self.busy or self.closed:
            return
        self.busy, self.operation = True, label
        for control in [*self.buttons, self.model_menu, self.browser_menu]:
            control.configure(state="disabled")
        self.cancel_button.configure(state="normal" if label == "login" else "disabled")
        self.result_label.configure(text="Операция выполняется…")
        def worker():
            try:
                self.events.put(("done", operation()))
            except Exception as error:
                self.events.put(("error", str(error)))
        threading.Thread(target=worker, name="hub-deepseek-web", daemon=True).start()

    def poll_events(self):
        if self.closed:
            return
        while True:
            try:
                kind, text = self.events.get_nowait()
            except queue.Empty:
                break
            self.result_label.configure(text=text)
            self.update_status()
            if self.manager.login_committed:
                self.cancel_button.configure(state="disabled")
            if kind != "progress":
                self.busy, self.operation = False, None
                self.cancel_button.configure(state="disabled")
                for control in [*self.buttons, self.model_menu, self.browser_menu]:
                    control.configure(state="normal")
                if kind == "error":
                    messagebox.showerror("DeepSeek Web", text, parent=self.app)
        if time.monotonic() >= self._next_status_refresh:
            self.update_status()
            self._next_status_refresh = time.monotonic() + 5
        self._poll_id = self.after(150, self.poll_events)

    def toggle_diagnostics(self):
        if self.diagnostics.winfo_manager():
            self.diagnostics.pack_forget()
        else:
            self.diagnostics.pack(fill="x", pady=(0, 12))

    def show_logs(self):
        text = self.manager.log_file.read_text(encoding="utf-8")[-16000:] if self.manager.log_file.exists() else "Логов пока нет."
        self.logs.configure(state="normal")
        self.logs.delete("1.0", "end")
        self.logs.insert("1.0", text)
        self.logs.configure(state="disabled")

    def shutdown(self):
        self.closed = True
        if self._poll_id is not None:
            self.after_cancel(self._poll_id)
        self.manager.shutdown()
