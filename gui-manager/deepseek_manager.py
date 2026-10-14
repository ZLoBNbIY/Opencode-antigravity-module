"""DeepSeek Web through direct HTTPS; browser is used only for one-time sign-in."""
import json
from pathlib import Path
import secrets
import shutil
import threading
import time

from deepseek_browser import BrowserSession, WebError, browser_paths
from deepseek_bridge import WebBridge
from deepseek_config import config_path, parse_config, set_property
from deepseek_storage import atomic_write, protect_channel, protect_secret, unprotect_secret

MODELS = ("deepseek-chat", "deepseek-expert")
PROVIDER_ID = "deepseek-web"
PROVIDER_NAME = "DeepSeek Web (Antigravity Hub)"
REPO_ROOT = Path(__file__).resolve().parent.parent
OLD_PROVIDERS = {"deepseek-account": "DeepSeek Account (Antigravity Hub)", "local-deepseek": "DeepSeek (Hub, experimental)"}


class DeepSeekManager:
    def __init__(self, root=None, config_dir=None):
        self.root = Path(root) if root else Path.home() / ".local/share/antigravity-hub/deepseek"
        self.config_dir = Path(config_dir) if config_dir else Path.home() / ".config/opencode"
        self.state_file = self.root / "web-state.json"
        self.channel_file = self.root / "web-channel.json"
        self.session_file = self.root / "web-session.json"
        self.log_file = self.root / "logs/web.log"
        self._lock = threading.RLock()
        self._operation = threading.Lock()
        self._cancel = threading.Event()
        self._closed = threading.Event()
        self.login_committed = False
        self.storage_warning = None
        self.state = {"version": 3, "enabled": False, "browser": "auto"}
        if self.state_file.exists():
            try:
                state = json.loads(self.state_file.read_text(encoding="utf-8"))
                if state.get("version") != 3 or state.get("browser") not in ("auto", "default", "chrome", "edge"):
                    raise ValueError()
                self.state = state
            except (OSError, ValueError, AttributeError):
                self.storage_warning = "Настройки DeepSeek Web повреждены. Старые данные аккаунтов не изменены."
        if self.state.get("enabled") and not self.session_file.exists():
            # Older browser-proxy state did not contain an exportable HTTP session.
            self.state["enabled"] = False
            self.storage_warning = "После обновления нужен разовый вход для сохранения защищённой HTTPS-сессии."
        self.browser = BrowserSession(self.root, self.state["browser"])
        self.bridge = None
        self.web_client = None
        self.last_error = None

    def _log(self, stage, code="ok"):
        # All callers supply fixed identifiers; never log browser events or input.
        self.log_file.parent.mkdir(parents=True, exist_ok=True)
        with self.log_file.open("a", encoding="utf-8") as stream:
            stream.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {stage}: {code}\n")

    @property
    def signed_in(self):
        return bool(self.state.get("enabled"))

    def snapshot(self):
        return {"signedIn": self.signed_in, "browser": self.state["browser"], "browserRunning": self.browser.running,
                "connected": self.bridge is not None and not self.bridge.closed.is_set(), "signedInAt": self.state.get("signedInAt"),
                "lastError": self.last_error}

    def _web_client(self):
        if self.web_client is None:
            if not self.signed_in or not self.session_file.exists():
                raise WebError("login-required")
            try:
                record = json.loads(self.session_file.read_text(encoding="utf-8"))
                session = unprotect_secret(record, "deepseek-web-session")
            except (OSError, ValueError, TypeError):
                raise WebError("login-required") from None
            from deepseek_http import DeepSeekHttpClient
            self.web_client = DeepSeekHttpClient(session)
        return self.web_client

    def set_browser(self, value):
        if value not in ("auto", "default", "chrome", "edge"):
            raise ValueError("Выберите системный Chromium-браузер, Chrome или Edge")
        if (self.signed_in and value != self.state["browser"]) or (self.browser.running and value not in ("auto", self.browser.brand)):
            raise ValueError("Сначала отключите DeepSeek Web перед сменой браузера")
        self.browser.preference = value
        self.state["browser"] = value

    def _channel(self):
        with self._lock:
            if self._closed.is_set():
                raise WebError("cancelled")
            if self.bridge and not self.bridge.closed.is_set():
                return
            bridge = WebBridge(self.generate, MODELS)
            try:
                atomic_write(self.channel_file, json.dumps(protect_channel({"purpose": "deepseek-web-channel", "origin": bridge.origin, "key": bridge.key})))
            except Exception:
                bridge.close()
                raise
            self.bridge = bridge

    def needs_restore(self):
        if self.signed_in:
            return True
        try:
            _, _, data, _ = self._configuration()
            if any(data.get("providers", {}).get(key, {}).get("name") == name for key, name in OLD_PROVIDERS.items()):
                return True
            provider = data.get("providers", {}).get(PROVIDER_ID)
            if isinstance(provider, dict) and provider.get("name") == PROVIDER_NAME:
                return any(not provider.get("models", {}).get(model, {}).get("disabled", False) for model in MODELS)
            return False
        except (OSError, ValueError, AttributeError):
            return False

    def restore(self):
        if self.signed_in:
            self._channel()
        return self.configure_opencode()  # No browser or remote request on startup.

    def prepare_login(self):
        with self._lock:
            self._cancel = threading.Event()
            self.login_committed = False
            return self._cancel

    def login(self, progress=lambda text: None, cancel=None, timeout=600):
        if not self._operation.acquire(blocking=False):
            raise WebError("busy")
        try:
            self._configuration()
            cancel = cancel if cancel is not None else self.prepare_login()
            self._cancel = cancel
            if cancel.is_set() or self._closed.is_set():
                raise WebError("cancelled")
            progress("Откройте отдельный профиль системного браузера и войдите на chat.deepseek.com…")
            self.browser.show()
            progress("Войдите на chat.deepseek.com. После входа Hub сохранит защищённую сессию и закроет браузер.")
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                if cancel.is_set() or self._closed.is_set():
                    raise WebError("cancelled")
                if self.browser.session_ready():
                    session = self.browser.capture_session()
                    atomic_write(self.session_file, json.dumps(protect_secret("deepseek-web-session", session)))
                    with self._lock:
                        if cancel.is_set() or self._closed.is_set():
                            raise WebError("cancelled")
                        self.state.update({"enabled": True, "browser": self.browser.brand, "signedInAt": int(time.time() * 1000)})
                        atomic_write(self.state_file, json.dumps(self.state))
                        self.login_committed = True
                    from deepseek_http import DeepSeekHttpClient
                    self.web_client = DeepSeekHttpClient(session)
                    self.browser.close()
                    self._channel()
                    self.last_error = None
                    self._log("sign-in")
                    try:
                        self.configure_opencode()
                    except Exception:
                        return "Веб-сессия сохранена. Автоподключение OpenCode не удалось; нажмите «Повторить подключение» в диагностике."
                    return "Сессия сохранена. Браузер закрыт; запросы OpenCode отправляются напрямую в веб-чат DeepSeek по HTTPS."
                time.sleep(0.5)
            raise WebError("timeout")
        except WebError as error:
            self.last_error = str(error)
            self._log("sign-in", error.code)
            raise
        finally:
            self._operation.release()

    def cancel_login(self):
        with self._lock:
            if self.login_committed:
                return False
            self._cancel.set()
            return True

    def show_chat(self):
        if not self._operation.acquire(blocking=False):
            raise WebError("busy")
        try:
            self.browser.show()
            return "Открыт браузерный профиль Hub. Обычные вкладки Chrome/Edge не затрагиваются."
        finally:
            self._operation.release()

    def refresh_details(self):
        if not self._operation.acquire(blocking=False):
            raise WebError("busy")
        try:
            self._web_client()
            self.last_error = None
            return "Защищённая веб-сессия загружена. Связь проверяется тестовой генерацией; без отправки сообщения сайт не предоставляет проверки входа."
        finally:
            self._operation.release()

    def generate(self, prompt, model, cancel):
        if model not in MODELS:
            raise ValueError("Неизвестная веб-модель")
        if not self.signed_in:
            raise WebError("login-required")
        if not self._operation.acquire(blocking=False):
            raise WebError("busy")
        try:
            if self._closed.is_set():
                raise WebError("cancelled")
            result = self._web_client().generate(prompt, "default" if model == MODELS[0] else "expert", cancel)
            self.last_error = None
            return result
        except WebError as error:
            self.last_error = str(error)
            self._log("generation", error.code)
            raise
        finally:
            self._operation.release()

    def logout(self):
        self.cancel_login()
        self.state["enabled"] = False
        atomic_write(self.state_file, json.dumps(self.state))
        self.session_file.unlink(missing_ok=True)
        self.web_client = None
        self._stop()
        self.configure_opencode()
        return "DeepSeek Web отключён. Защищённая копия веб-сессии удалена; профиль браузера и старые данные аккаунтов сохранены."

    def _stop(self):
        with self._lock:
            if self.bridge:
                self.bridge.close()
                self.bridge = None
                self.channel_file.unlink(missing_ok=True)
            self.browser.close()

    def shutdown(self):
        self._closed.set()
        self._cancel.set()
        self._stop()

    def provider_config(self):
        return {"name": PROVIDER_NAME, "package": "@opencode/ai/providers/openai-compatible",
                "settings": {"baseURL": (self.bridge.origin if self.bridge else "http://127.0.0.1:1") + "/v1", "apiKey": "hub-web-placeholder", "encoding": "none"},
                "models": {model: {"name": "DeepSeek Web Instant" if model == MODELS[0] else "DeepSeek Web Expert",
                                   "capabilities": {"tools": True, "input": ["text"], "output": ["text"]},
                                   "limit": {"context": 64000, "output": 8192}, "disabled": not self.signed_in} for model in MODELS}}

    def _configuration(self):
        path = config_path(self.config_dir)
        original = path.read_text(encoding="utf-8-sig") if path.exists() else "{}\n"
        data = parse_config(original)
        for key in ("provider", "providers"):
            if key in data and not isinstance(data[key], dict):
                raise ValueError(f"Поле {key} должно быть объектом")
            existing = data.get(key, {}).get(PROVIDER_ID)
            if existing is not None and (not isinstance(existing, dict) or existing.get("name") != PROVIDER_NAME):
                raise ValueError("Провайдер deepseek-web настроен вручную. Он не перезаписан.")
        plugins = data.get("plugins", data.get("plugin", []))
        if not isinstance(plugins, list):
            raise ValueError("Некорректный список плагинов")
        return path, original, data, plugins

    def configure_opencode(self, default_model=None):
        if default_model is not None and default_model not in MODELS:
            raise ValueError("Неизвестная модель")
        path, original, data, plugins = self._configuration()
        target = self.root / "browser-plugin"
        uri = target.resolve().as_uri()
        replaced = {(self.root / folder).resolve().as_uri() for folder in ("opencode-plugin", "account-plugin", "browser-plugin")}
        normalized = []
        for item in plugins:
            if isinstance(item, list) and len(item) == 2:
                item = {"package": item[0], "options": item[1]}
            source = item.get("package") if isinstance(item, dict) else item
            if source not in replaced:
                normalized.append(item)
        normalized.append({"package": uri, "options": {"channelFile": str(self.channel_file.resolve())}})
        updated = set_property(original, ("providers", PROVIDER_ID), self.provider_config())
        updated = set_property(updated, ("plugins",), normalized)
        if "$schema" not in data:
            updated = set_property(updated, ("$schema",), "https://opencode.ai/config.json")
        for old_id, name in OLD_PROVIDERS.items():
            old = data.get("providers", {}).get(old_id)
            if isinstance(old, dict) and old.get("name") == name:
                for model in old.get("models", {}):
                    updated = set_property(updated, ("providers", old_id, "models", model, "disabled"), True)
                if isinstance(data.get("model"), str) and data["model"].startswith(old_id + "/"):
                    default_model = MODELS[1] if data["model"].endswith(("deepseek-v4-pro", "deepseek-expert")) else MODELS[0]
        if default_model:
            updated = set_property(updated, ("model",), PROVIDER_ID + "/" + default_model)
        parse_config(updated)
        for name in ("index.js", "package.json", "LICENSE", "NOTICE.md"):
            atomic_write(target / name, (REPO_ROOT / "deepseek-plugin" / name).read_text(encoding="utf-8"))
        if updated != original:
            if path.exists():
                shutil.copy2(path, path.with_name(path.name + ".deepseek-" + secrets.token_hex(6) + ".bak"))
            if path.exists() and path.read_text(encoding="utf-8-sig") != original:
                raise RuntimeError("Конфиг изменён другим процессом. Повторите подключение.")
            atomic_write(path, updated)
        return "DeepSeek Web настроен. Если список моделей не обновился, перезапустите службу OpenCode после завершения текущих задач."

    def test_generation(self, model=MODELS[0], tools=False):
        from deepseek_format import completion_response, messages_to_prompt
        nonce = secrets.token_hex(8)
        payload = {"model": model, "messages": [{"role": "user", "content": "Reply with exactly HUB_OK_" + nonce}]}
        if tools:
            payload["messages"][0]["content"] = f"Call hub_probe with value '{nonce}'."
            payload["tools"] = [{"type": "function", "function": {"name": "hub_probe", "description": "Protocol test only; no action is executed.",
                                 "parameters": {"type": "object", "properties": {"value": {"type": "string"}}, "required": ["value"]}}}]
            payload["tool_choice"] = "required"
        prompt = messages_to_prompt(payload)
        text = self.generate(prompt, model, threading.Event())
        result = completion_response(payload, prompt, text)
        if tools:
            valid = any(call["function"]["name"] == "hub_probe" and json.loads(call["function"]["arguments"]).get("value") == nonce for call in result["choices"][0]["message"].get("tool_calls", []))
        else:
            valid = "HUB_OK_" + nonce in text
        if not valid:
            raise WebError("site-changed")
        return "Веб-генерация: OK." if not tools else "Эмуляция tool calling: OK. Фиктивный инструмент не выполнялся."
