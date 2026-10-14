"""Use an installed Chromium browser only for interactive web-chat sign-in."""

import base64
import hashlib
import json
import os
from pathlib import Path
import re
import queue
import secrets
import shutil
import socket
import struct
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request

CHAT_URL = "https://chat.deepseek.com/"


class WebError(RuntimeError):
    def __init__(self, code, status=None):
        messages = {
            "browser-missing": "Не найден установленный Chromium-браузер для разового входа. Hub не будет скачивать браузер.",
            "browser-unsupported": "Системный браузер не найден или не поддерживает Chromium CDP (например, подойдут Яндекс, Chrome, Edge, Brave и Opera).",
            "pow": "Не удалось решить проверку DeepSeek. Повторите запрос или войдите в веб-чат заново.",
            "browser-start": "Не удалось открыть отдельный профиль браузера для входа. Проверьте политики браузера и повторите.",
            "browser-protocol": "Соединение с браузером для входа прервано.",
            "login-required": "Завершите вход или проверку человека на chat.deepseek.com в окне браузера Hub.",
            "site-changed": "Интерфейс или протокол веб-чата изменился. Запрос остановлен; платный API не используется.",
            "network": "Веб-чат DeepSeek не завершил прямой HTTPS-запрос. Проверьте соединение и веб-сессию.",
            "limit": "Веб-чат ограничил запросы. Подождите или проверьте ограничения аккаунта на сайте.",
            "cancelled": "Запрос отменён.",
            "timeout": "Время ожидания веб-чата истекло. Повторите запрос позже.",
            "busy": "DeepSeek Web занят другим запросом. Повторите позже.",
        }
        super().__init__(messages.get(code, "Ошибка DeepSeek Web") + (f" (HTTP {status})" if status else ""))
        self.code, self.status = code, status


def browser_paths():
    found = {}
    names = {"chrome": "chrome.exe", "edge": "msedge.exe"}
    if os.name == "nt":
        import winreg
        for brand, filename in names.items():
            for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
                try:
                    with winreg.OpenKey(hive, rf"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{filename}") as key:
                        value = Path(winreg.QueryValue(key, None).strip('"'))
                    if value.is_file() and value.name.lower() == filename:
                        found[brand] = value
                except OSError:
                    pass
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\Shell\Associations\UrlAssociations\https\UserChoice") as key:
                prog_id = winreg.QueryValueEx(key, "ProgId")[0]
            with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, prog_id + r"\shell\open\command") as key:
                command = winreg.QueryValueEx(key, None)[0]
            match = re.match(r'^\s*"([^\"]+\.exe)"|^\s*(.+?\.exe)(?:\s|$)', command, re.IGNORECASE)
            executable = Path(next(group for group in match.groups() if group).strip()) if match else None
            if executable and executable.is_file():
                found["default"] = executable
        except (OSError, StopIteration, AttributeError):
            pass
        roots = [Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")), Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")), Path.home() / "AppData/Local"]
        for root in roots:
            for brand, relative in (("chrome", "Google/Chrome/Application/chrome.exe"), ("edge", "Microsoft/Edge/Application/msedge.exe")):
                candidate = root / relative
                if candidate.is_file():
                    found.setdefault(brand, candidate)
    elif sys.platform == "darwin":
        for brand, app, executable in (("chrome", "Google Chrome", "Google Chrome"), ("edge", "Microsoft Edge", "Microsoft Edge")):
            path = Path(f"/Applications/{app}.app/Contents/MacOS/{executable}")
            if path.is_file():
                found[brand] = path
    else:
        for brand, commands in (("chrome", ("google-chrome", "chromium", "chromium-browser")), ("edge", ("microsoft-edge",))):
            for command in commands:
                path = shutil.which(command)
                if path:
                    found[brand] = Path(path)
                    break
    return found


def supports_cdp(path):
    """Recognize installed Chromium-family executables; Firefox is not CDP."""
    name = Path(path).name.lower()
    return name in {"chrome.exe", "msedge.exe", "browser.exe", "brave.exe", "opera.exe", "vivaldi.exe",
                    "chromium.exe", "chrome", "microsoft-edge", "google-chrome", "chromium", "chromium-browser"}


class CDP:
    """Small bounded WebSocket client with CDP reply/event multiplexing."""
    def __init__(self, url):
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme != "ws" or parsed.hostname != "127.0.0.1" or not parsed.port or parsed.username or parsed.password:
            raise WebError("browser-protocol")
        self.socket = socket.create_connection(("127.0.0.1", parsed.port), timeout=5)
        self.socket.settimeout(1)
        key = base64.b64encode(secrets.token_bytes(16)).decode()
        request = f"GET {parsed.path} HTTP/1.1\r\nHost: 127.0.0.1:{parsed.port}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n"
        self.socket.sendall(request.encode("ascii"))
        header = bytearray()
        while not header.endswith(b"\r\n\r\n"):
            part = self.socket.recv(1)
            if not part or len(header) > 16384:
                self.socket.close()
                raise WebError("browser-protocol")
            header.extend(part)
        lines = header.decode("latin1").split("\r\n")
        expected = base64.b64encode(hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest()).decode()
        values = {line.split(":", 1)[0].lower(): line.split(":", 1)[1].strip() for line in lines[1:] if ":" in line}
        if " 101 " not in lines[0] or values.get("sec-websocket-accept") != expected:
            self.socket.close()
            raise WebError("browser-protocol")
        self.events = queue.Queue(maxsize=5000)
        self._pending, self._sequence = {}, 0
        self._lock = threading.RLock()
        self._closed = threading.Event()
        self._reader = threading.Thread(target=self._read_loop, name="deepseek-cdp", daemon=True)
        self._reader.start()

    def _exact(self, length):
        data = bytearray()
        while len(data) < length and not self._closed.is_set():
            try:
                part = self.socket.recv(length - len(data))
            except socket.timeout:
                continue
            if not part:
                raise WebError("browser-protocol")
            data.extend(part)
        if len(data) != length:
            raise WebError("browser-protocol")
        return bytes(data)

    def _send(self, data, opcode=1):
        mask = secrets.token_bytes(4)
        size = len(data)
        prefix = bytes([0x80 | opcode, 0x80 | size]) if size < 126 else bytes([0x80 | opcode, 0x80 | 126]) + struct.pack("!H", size) if size < 65536 else bytes([0x80 | opcode, 0x80 | 127]) + struct.pack("!Q", size)
        with self._lock:
            self.socket.sendall(prefix + mask + bytes(byte ^ mask[i % 4] for i, byte in enumerate(data)))

    def _read_loop(self):
        fragments = bytearray()
        try:
            while not self._closed.is_set():
                first, second = self._exact(2)
                size = second & 127
                if size == 126:
                    size = struct.unpack("!H", self._exact(2))[0]
                elif size == 127:
                    size = struct.unpack("!Q", self._exact(8))[0]
                if size + len(fragments) > 12 * 1024 * 1024:
                    raise WebError("browser-protocol")
                mask = self._exact(4) if second & 128 else None
                payload = self._exact(size)
                if mask:
                    payload = bytes(byte ^ mask[i % 4] for i, byte in enumerate(payload))
                opcode = first & 15
                if opcode == 8:
                    break
                if opcode == 9:
                    self._send(payload, 10)
                    continue
                if opcode == 10:
                    continue
                if opcode not in (0, 1):
                    raise WebError("browser-protocol")
                fragments.extend(payload)
                if not first & 0x80:
                    continue
                message = json.loads(fragments)
                fragments.clear()
                if "id" in message:
                    with self._lock:
                        pending = self._pending.get(message["id"])
                        if pending:
                            pending[1].append(message)
                            pending[0].set()
                elif message.get("method") in ("Fetch.requestPaused", "Network.responseReceived", "Network.loadingFinished", "Network.loadingFailed"):
                    try:
                        self.events.put_nowait(message)
                    except queue.Full:
                        raise WebError("browser-protocol")
        except (OSError, ValueError, WebError):
            pass  # Never expose CDP payloads or exceptions containing page data.
        finally:
            self._closed.set()
            with self._lock:
                for done, _ in self._pending.values():
                    done.set()

    def call(self, method, params=None, timeout=15):
        if self._closed.is_set():
            raise WebError("browser-protocol")
        done, result = threading.Event(), []
        with self._lock:
            self._sequence += 1
            ident = self._sequence
            self._pending[ident] = (done, result)
        try:
            self._send(json.dumps({"id": ident, "method": method, "params": params or {}}).encode())
            if not done.wait(timeout):
                raise WebError("timeout")
            if not result or "error" in result[0]:
                raise WebError("browser-protocol")
            return result[0].get("result", {})
        except OSError:
            raise WebError("browser-protocol") from None
        finally:
            with self._lock:
                self._pending.pop(ident, None)

    def evaluate(self, expression):
        result = self.call("Runtime.evaluate", {"expression": expression, "returnByValue": True})
        if "exceptionDetails" in result:
            raise WebError("browser-protocol")
        return result.get("result", {}).get("value")

    def close(self):
        self._closed.set()
        try:
            self.socket.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self.socket.close()
        self._reader.join(timeout=2)


def parse_web_sse(body):
    """Read RESPONSE fragments only; never treat THINK as tool calls."""
    types, contents = [], {}
    active, completed = None, False
    if body.lstrip().startswith("{"):
        try:
            error = json.loads(body)
        except ValueError:
            raise WebError("site-changed") from None
        raise WebError("login-required" if error.get("code") == 40003 else "network")
    for line in body.splitlines():
        if not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if data == "[DONE]":
            completed = True
            continue
        try:
            event = json.loads(data)
        except ValueError:
            raise WebError("site-changed") from None
        if event.get("error") or event.get("code", 0) != 0:
            raise WebError("network")
        value, path = event.get("v"), event.get("p")
        if isinstance(value, dict) and isinstance(value.get("response"), dict):
            fragments = value["response"].get("fragments", [])
            types = [item.get("type") for item in fragments]
            for index, item in enumerate(fragments):
                if item.get("type") == "RESPONSE":
                    active = index
                    contents[index] = item.get("content") or ""
            completed |= value["response"].get("status") in ("FINISHED", "COMPLETE")
        elif path == "response/fragments" and event.get("o") == "APPEND":
            if isinstance(value, str):
                value = json.loads(value)
            for item in (value if isinstance(value, list) else [value]):
                if not isinstance(item, dict):
                    raise WebError("site-changed")
                index = len(types)
                types.append(item.get("type"))
                if item.get("type") == "RESPONSE":
                    active = index
                    contents[index] = item.get("content") or ""
        elif isinstance(path, str) and path.startswith("response/fragments/") and path.endswith("/content"):
            try:
                index = int(path.split("/")[2])
            except ValueError:
                raise WebError("site-changed") from None
            active = len(types) - 1 if index == -1 else index
            if event.get("o") == "APPEND" and isinstance(value, str) and 0 <= active < len(types) and types[active] == "RESPONSE":
                contents[active] = contents.get(active, "") + value
        elif path == "response/status":
            active = None
            completed |= value in ("FINISHED", "COMPLETE")
        elif "p" in event:
            active = None  # Bare values inherit the *last path*, not last text path.
        elif isinstance(value, str) and active is not None and 0 <= active < len(types) and types[active] == "RESPONSE":
            contents[active] = contents.get(active, "") + value
    text = "".join(contents[index] for index in sorted(contents))
    # Network.loadingFinished proves transport completion; some versions omit DONE.
    if not text:
        raise WebError("site-changed")
    return text


class BrowserSession:
    def __init__(self, root, preference="auto"):
        self.root = Path(root)
        self.preference = preference
        self.brand = None
        self.process = None
        self.browser = None
        self.page = None
        self.page_id = None
        self.debug_url = None
        self._lock = threading.RLock()

    @property
    def running(self):
        return self.browser is not None and not self.browser._closed.is_set()

    def start(self):
        with self._lock:
            if self.running:
                return
            paths = browser_paths()
            self.brand = self.preference if self.preference != "auto" else next((name for name in ("default", "chrome", "edge") if name in paths), None)
            if self.brand not in paths:
                raise WebError("browser-missing")
            if not supports_cdp(paths[self.brand]):
                raise WebError("browser-unsupported")
            profile = self.root / "browser-profiles" / self.brand
            profile.mkdir(parents=True, exist_ok=True)
            if os.name != "nt":
                profile.chmod(0o700)
            port_file = profile / "hub-debug-endpoint.json"
            if port_file.exists():
                try:
                    self.debug_url = json.loads(port_file.read_text())["url"]
                    self.browser = CDP(self.debug_url)
                    self.browser.call("Browser.getVersion")
                    self._new_page()
                    return
                except (OSError, ValueError, KeyError, WebError):
                    if self.browser:
                        self.browser.close()
                    self.browser = None
            # This is an ephemeral debugger marker in our profile, not user data.
            port_file.unlink(missing_ok=True)
            # Port zero marks navigator.webdriver in Chromium. Use a normal
            # positive debugger port, without automation/stealth flags.
            with socket.socket() as reservation:
                reservation.bind(("127.0.0.1", 0))
                debugger_port = reservation.getsockname()[1]
            self.process = subprocess.Popen([
                str(paths[self.brand]), "--user-data-dir=" + str(profile.resolve()),
                "--remote-debugging-address=127.0.0.1", "--remote-debugging-port=" + str(debugger_port),
                "--no-first-run", "--no-default-browser-check", "--new-window", "about:blank",
            ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            deadline = time.monotonic() + 25
            while time.monotonic() < deadline:
                try:
                    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
                    with opener.open(f"http://127.0.0.1:{debugger_port}/json/version", timeout=1) as response:
                        self.debug_url = json.load(response)["webSocketDebuggerUrl"]
                    parsed = urllib.parse.urlsplit(self.debug_url)
                    if parsed.hostname != "127.0.0.1" or parsed.port != debugger_port or not parsed.path.startswith("/devtools/browser/"):
                        raise ValueError()
                    self.browser = CDP(self.debug_url)
                    from deepseek_storage import atomic_write
                    atomic_write(port_file, json.dumps({"url": self.debug_url}))
                    break
                except (OSError, ValueError, KeyError, WebError):
                    time.sleep(0.2)
            else:
                self.close()
                raise WebError("browser-start")
            self._new_page()

    def _new_page(self):
        if self.page:
            self.page.close()
            self.page = None
        if self.page_id:
            try:
                self.browser.call("Target.closeTarget", {"targetId": self.page_id})
            except WebError:
                pass
        self.page_id = self.browser.call("Target.createTarget", {"url": CHAT_URL})["targetId"]
        # Page websocket shares the browser debugger's loopback port.
        root = urllib.parse.urlsplit(self.browser_url)
        self.page = CDP(f"ws://127.0.0.1:{root.port}/devtools/page/{self.page_id}")
        self.page.call("Page.enable")

    @property
    def browser_url(self):
        return self.debug_url

    def session_ready(self):
        self.start()
        value = self.page.evaluate("""(() => {
          if (location.origin !== 'https://chat.deepseek.com') return false;
          try { const token = JSON.parse(localStorage.getItem('userToken') || 'null');
            return !!token?.value && !location.pathname.includes('sign_in') && !!document.querySelector('textarea');
          } catch { return false; }
        })()""")
        return value is True

    def capture_session(self):
        """Export only chat.deepseek.com auth material for the direct HTTPS client."""
        self.start()
        if not self.session_ready():
            raise WebError("login-required")
        self.page.call("Network.enable")
        token = self.page.evaluate("""(() => {
          try { return JSON.parse(localStorage.getItem('userToken') || 'null')?.value || null; }
          catch { return null; }
        })()""")
        user_agent = self.page.evaluate("navigator.userAgent")
        cookies = self.page.call("Network.getCookies", {"urls": [CHAT_URL]}).get("cookies", [])
        cookie_values = {item["name"]: item["value"] for item in cookies
                         if item.get("domain", "").lstrip(".").endswith("deepseek.com")}
        if not isinstance(token, str) or not token or not isinstance(user_agent, str) or not cookie_values:
            raise WebError("login-required")
        return {"token": token, "cookies": cookie_values, "userAgent": user_agent, "capturedAt": int(time.time())}

    def show(self):
        self.start()
        self._set_window_state("normal")
        self.page.call("Page.bringToFront")

    def minimize(self):
        """Keep the authenticated web session alive without an open foreground window."""
        if not self.running or not self.page_id:
            return
        self._set_window_state("minimized")

    def _set_window_state(self, state):
        try:
            window = self.browser.call("Browser.getWindowForTarget", {"targetId": self.page_id})
            self.browser.call("Browser.setWindowBounds", {"windowId": window["windowId"], "bounds": {"windowState": state}})
        except (WebError, KeyError):
            # Window controls are best-effort; CDP/session functionality remains usable.
            pass

    # BrowserSession is intentionally limited to interactive sign-in and session capture.

    def close(self):
        # Browser.close affects our separate profile, never personal Chrome/Edge.
        if self.browser:
            try:
                self.browser.call("Browser.close", timeout=3)
            except WebError:
                pass
        if self.page:
            self.page.close()
        if self.browser:
            self.browser.close()
        self.page, self.browser, self.page_id = None, None, None
        if self.process and self.process.poll() is None:
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.terminate()
        self.process = None
