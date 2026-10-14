"""Direct stdlib HTTPS client for the chat.deepseek.com web-chat endpoints."""
import json
import threading
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit

from deepseek_browser import WebError, parse_web_sse
from deepseek_pow import solve_pow

BASE = "https://chat.deepseek.com"
COMPLETION_PATH = "/api/v0/chat/completion"
_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"


class DeepSeekHttpClient:
    def __init__(self, session, opener=None, timeout=300):
        if (not isinstance(session, dict) or not isinstance(session.get("token"), str) or not session["token"]
                or not isinstance(session.get("cookies"), dict)):
            raise WebError("login-required")
        self.session = session
        self.timeout = timeout
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, request, response, code, message, headers, new_url):
                return None
        self.opener = opener or urllib.request.build_opener(urllib.request.HTTPSHandler(), NoRedirect())
        self._lock = threading.Lock()

    def _request(self, path, payload, extra_headers=None, cancel=None):
        if cancel is not None and cancel.is_set():
            raise WebError("cancelled")
        headers = {
            "Authorization": "Bearer " + self.session["token"], "Accept": "*/*",
            "Content-Type": "application/json", "User-Agent": self.session.get("userAgent") or _USER_AGENT,
            "Origin": BASE, "Referer": BASE + "/", "X-App-Version": "2.0.0",
            "X-Client-Version": "2.0.0", "X-Client-Platform": "web",
            "X-Client-Locale": "en_US", "X-Client-Bundle-Id": "com.deepseek.chat",
            "X-Client-Timezone-Offset": str(-time.timezone // 60),
        }
        cookies = self.session.get("cookies", {})
        if cookies:
            if any(not isinstance(name, str) or not isinstance(value, str)
                   or any(char in name + value for char in "\r\n;,") for name, value in cookies.items()):
                raise WebError("login-required")
            headers["Cookie"] = "; ".join(f"{name}={value}" for name, value in cookies.items())
        if extra_headers:
            headers.update(extra_headers)
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        request = urllib.request.Request(BASE + path, data=body, headers=headers, method="POST")
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                final = urlsplit(response.geturl())
                if final.scheme != "https" or final.hostname != "chat.deepseek.com":
                    raise WebError("network")
                body = response.read(16 * 1024 * 1024 + 1)
                if len(body) > 16 * 1024 * 1024:
                    raise WebError("site-changed")
                return response.status, body
        except urllib.error.HTTPError as error:
            if error.code in (401, 403):
                raise WebError("login-required", error.code) from None
            if error.code == 429:
                raise WebError("limit", error.code) from None
            raise WebError("network", error.code) from None
        except (urllib.error.URLError, TimeoutError, OSError):
            raise WebError("network") from None

    @staticmethod
    def _biz(raw):
        try:
            data = json.loads(raw)
            if data.get("code") != 0:
                raise WebError("login-required" if data.get("code") == 40003 else "network")
            return data["data"]["biz_data"]
        except WebError:
            raise
        except (ValueError, KeyError, TypeError):
            raise WebError("site-changed") from None

    def _pow_header(self, cancel):
        _, raw = self._request("/api/v0/chat/create_pow_challenge", {"target_path": COMPLETION_PATH}, cancel=cancel)
        try:
            challenge = self._biz(raw)["challenge"]
            return solve_pow(challenge, cancel)
        except WebError:
            raise
        except InterruptedError:
            raise WebError("cancelled") from None
        except ValueError:
            raise WebError("pow") from None

    def generate(self, prompt, model_type, cancel):
        if model_type not in ("default", "expert"):
            raise ValueError("Unknown DeepSeek web model")
        if not self._lock.acquire(blocking=False):
            raise WebError("busy")
        try:
            _, raw = self._request("/api/v0/chat_session/create", {}, cancel=cancel)
            try:
                session_id = self._biz(raw)["chat_session"]["id"]
            except (KeyError, TypeError):
                raise WebError("site-changed") from None
            pow_header = self._pow_header(cancel)
            payload = {
                "chat_session_id": session_id, "parent_message_id": None, "prompt": prompt,
                "ref_file_ids": [], "thinking_enabled": False, "search_enabled": False,
                "action": None, "preempt": False, "model_type": model_type,
            }
            _, response = self._request(COMPLETION_PATH, payload, {"X-DS-PoW-Response": pow_header}, cancel=cancel)
            try:
                return parse_web_sse(response.decode("utf-8"))
            except UnicodeDecodeError:
                raise WebError("site-changed") from None
        finally:
            self._lock.release()
