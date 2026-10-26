"""
Anthropic Claude Pro / Team Account and Subscription Bridge for Antigravity Hub.
Enables using Claude Pro / Team accounts in OpenCode without pay-per-token API keys.
"""

import os
import sys
import json
import time
import socket
import secrets
import threading
import urllib.request
import urllib.parse
import urllib.error
import http.client
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Optional, Dict, Any, List, Tuple

CONFIG_DIR = Path.home() / ".config" / "opencode"
CLAUDE_ACCOUNTS_FILE = CONFIG_DIR / "claude-accounts.json"
CLAUDE_PROFILE_DIR = CONFIG_DIR / "claude_profile"
DEFAULT_BRIDGE_PORT = 51186

CLAUDE_MODELS = {
    "claude-3-7-sonnet": {
        "name": "Claude 3.7 Sonnet",
        "api_model": "claude-3-7-sonnet-20250219",
        "limit": {"context": 200000, "output": 64000},
    },
    "claude-3-7-sonnet-thinking": {
        "name": "Claude 3.7 Sonnet (Thinking)",
        "api_model": "claude-3-7-sonnet-20250219",
        "limit": {"context": 200000, "output": 64000},
        "thinking": True,
    },
    "claude-3-5-sonnet": {
        "name": "Claude 3.5 Sonnet",
        "api_model": "claude-3-5-sonnet-20241022",
        "limit": {"context": 200000, "output": 16384},
    },
    "claude-3-5-haiku": {
        "name": "Claude 3.5 Haiku",
        "api_model": "claude-3-5-haiku-20241022",
        "limit": {"context": 200000, "output": 8192},
    },
    "claude-3-opus": {
        "name": "Claude 3 Opus",
        "api_model": "claude-3-opus-20240229",
        "limit": {"context": 200000, "output": 4096},
    },
}

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36"


def get_active_proxy() -> Optional[str]:
    """Returns proxy to use (VLESS 10809 if running, or custom proxy)."""
    # 1. First check if VLESS port 10809 is actively listening
    try:
        with socket.create_connection(("127.0.0.1", 10809), timeout=0.2):
            return "http://127.0.0.1:10809"
    except Exception:
        pass

    # 2. Check saved user proxy or config
    try:
        cfg_file = CONFIG_DIR / "antigravity.json"
        if cfg_file.exists():
            cfg = json.loads(cfg_file.read_text(encoding="utf-8"))
            if cfg.get("vless_enabled") and cfg.get("vless_url"):
                return "http://127.0.0.1:10809"
            user_proxy = cfg.get("proxy")
            if user_proxy and user_proxy != "http://127.0.0.1:51180":
                return user_proxy
    except Exception:
        pass
    return None


def get_http_opener(timeout: int = 15) -> urllib.request.OpenerDirector:
    proxy = get_active_proxy()
    if proxy:
        return urllib.request.build_opener(urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
    return urllib.request.build_opener(urllib.request.ProxyHandler({}))


class ClaudeAccountManager:
    """Manages Claude Pro / Team accounts and subscriptions."""

    def __init__(self):
        self._lock = threading.Lock()
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    def load_accounts(self) -> List[Dict[str, Any]]:
        with self._lock:
            if not CLAUDE_ACCOUNTS_FILE.exists():
                return []
            try:
                data = json.loads(CLAUDE_ACCOUNTS_FILE.read_text(encoding="utf-8"))
                return data.get("accounts", [])
            except Exception:
                return []

    def save_accounts(self, accounts: List[Dict[str, Any]]) -> bool:
        with self._lock:
            try:
                CLAUDE_ACCOUNTS_FILE.write_text(
                    json.dumps({"accounts": accounts}, indent=2, ensure_ascii=False),
                    encoding="utf-8",
                )
                return True
            except Exception as e:
                print(f"[Claude Manager] Error saving accounts: {e}")
                return False

    def get_active_account(self) -> Optional[Dict[str, Any]]:
        accounts = self.load_accounts()
        for a in accounts:
            if a.get("active", False):
                return a
        if accounts:
            return accounts[0]
        return None

    def set_active_account(self, email: str) -> bool:
        accounts = self.load_accounts()
        found = False
        for a in accounts:
            if a.get("email") == email:
                a["active"] = True
                found = True
            else:
                a["active"] = False
        if found:
            self.save_accounts(accounts)
            self.configure_opencode_provider()
            return True
        return False

    def delete_account(self, email: str) -> bool:
        accounts = self.load_accounts()
        new_accs = [a for a in accounts if a.get("email") != email]
        if len(new_accs) != len(accounts):
            if new_accs and not any(a.get("active") for a in new_accs):
                new_accs[0]["active"] = True
            self.save_accounts(new_accs)
            self.configure_opencode_provider()
            return True
        return False

    def verify_and_add_account(self, session_key: str, custom_name: str = "") -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        """Validates claude.ai sessionKey or Claude Code setup-token and saves account info."""
        session_key = session_key.strip()
        if not session_key:
            return False, "Укажите sessionKey (куки claude.ai) или токен Claude Code", None

        opener = get_http_opener(timeout=15)

        # Case A: Anthropic API / Claude Code setup-token (starts with sk-ant-api...)
        if session_key.startswith("sk-ant-api"):
            try:
                headers = {
                    "User-Agent": USER_AGENT,
                    "x-api-key": session_key,
                    "anthropic-version": "2023-06-01",
                }
                req = urllib.request.Request("https://api.anthropic.com/v1/models", headers=headers)
                with opener.open(req, timeout=10) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                email = custom_name or "claude-code@anthropic"
                account_data = {
                    "email": email,
                    "name": custom_name or "Claude Code",
                    "session_key": session_key,
                    "token_type": "api_token",
                    "org_id": "claude-code",
                    "plan": "pro",
                    "active": False,
                    "added_at": int(time.time()),
                    "groups": [
                        {
                            "name": "claude",
                            "remainingPercent": 100.0,
                            "resetTime": "",
                            "windows": [
                                {"window": "5h", "remainingPercent": 100.0, "resetTime": ""},
                                {"window": "weekly", "remainingPercent": 100.0, "resetTime": ""},
                            ]
                        }
                    ]
                }
                accounts = self.load_accounts()
                updated = False
                for i, existing in enumerate(accounts):
                    if existing.get("email") == email:
                        account_data["active"] = existing.get("active", False)
                        accounts[i] = account_data
                        updated = True
                        break
                if not updated:
                    if not accounts:
                        account_data["active"] = True
                    accounts.append(account_data)

                self.save_accounts(accounts)
                self.configure_opencode_provider()
                return True, f"Аккаунт Claude Code ({email}) успешно подключён!", account_data
            except urllib.error.HTTPError as e:
                return False, f"Ошибка авторизации Anthropic API ({e.code}): недействительный токен.", None
            except Exception as e:
                return False, f"Ошибка подключения к api.anthropic.com (таймаут или сеть): {e}", None

        # Case B: claude.ai Web Session (sessionKey cookie: sk-ant-sid...)
        if not session_key.startswith("sk-ant-"):
            if not session_key.startswith("sid01-"):
                return False, (
                    "Введённое значение не является sessionKey или токеном Claude!\n\n"
                    "• Для сессии claude.ai: cookie в первой колонке называется 'sessionKey', "
                    "а её значение начинается с 'sk-ant-sid01-...'.\n"
                    "• Для Claude Code CLI: токен начинается с 'sk-ant-api...'.\n\n"
                    "Вы скопировали значение другой куки (например, __cf_bm). "
                    "В таблице Cookies найдите именно строку 'sessionKey'."
                ), None
            session_key = f"sk-ant-{session_key}"

        headers = {
            "User-Agent": USER_AGENT,
            "Cookie": f"sessionKey={session_key}",
            "Accept": "application/json",
        }

        try:
            req = urllib.request.Request("https://claude.ai/api/organizations", headers=headers)
            with opener.open(req, timeout=10) as resp:
                orgs = json.loads(resp.read().decode("utf-8"))

            if not orgs or not isinstance(orgs, list):
                return False, "Не удалось получить список организаций claude.ai. Проверьте sessionKey.", None

            primary_org = orgs[0]
            org_id = primary_org.get("uuid") or primary_org.get("id")
            plan_type = "pro" if any(k in str(primary_org.get("capabilities", [])).lower() for k in ("pro", "claude_pro", "paid")) else "free"
            
            # Fetch user profile
            email = "claude.user@anthropic"
            try:
                prof_req = urllib.request.Request("https://claude.ai/api/auth/current_user", headers=headers)
                with opener.open(prof_req, timeout=10) as resp:
                    u_data = json.loads(resp.read().decode("utf-8"))
                    email = u_data.get("email_address") or u_data.get("email") or email
            except Exception:
                pass

            account_data = {
                "email": email,
                "name": custom_name or email.split("@")[0],
                "session_key": session_key,
                "token_type": "session_key",
                "org_id": org_id,
                "plan": plan_type,
                "active": False,
                "added_at": int(time.time()),
                "groups": [
                    {
                        "name": "claude",
                        "remainingPercent": 100.0,
                        "resetTime": "",
                        "windows": [
                            {"window": "5h", "remainingPercent": 100.0, "resetTime": ""},
                            {"window": "weekly", "remainingPercent": 100.0, "resetTime": ""},
                        ]
                    }
                ]
            }

            accounts = self.load_accounts()
            updated = False
            for i, existing in enumerate(accounts):
                if existing.get("email") == email:
                    account_data["active"] = existing.get("active", False)
                    accounts[i] = account_data
                    updated = True
                    break

            if not updated:
                if not accounts:
                    account_data["active"] = True
                accounts.append(account_data)

            self.save_accounts(accounts)
            self.configure_opencode_provider()
            return True, f"Аккаунт {email} ({plan_type.upper()}) успешно подключён!", account_data
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                return False, f"Ошибка авторизации claude.ai ({e.code}). Сессия истекла или заблокирована.", None
            return False, f"Ошибка API claude.ai: {e}", None
        except Exception as e:
            return False, f"Ошибка проверки сессии: {e}", None

    def configure_opencode_provider(self) -> bool:
        """Configures the claude-pro provider in ~/.config/opencode/opencode.json."""
        active_acc = self.get_active_account()
        cfg_path = CONFIG_DIR / "opencode.json"
        try:
            cfg_data: Dict[str, Any] = {}
            if cfg_path.exists():
                cfg_data = json.loads(cfg_path.read_text(encoding="utf-8"))

            if "provider" not in cfg_data:
                cfg_data["provider"] = {}

            if active_acc:
                bridge_service.ensure_running()
                provider_cfg = {
                    "npm": "@ai-sdk/openai-compatible",
                    "name": "Claude Pro (Antigravity Hub)",
                    "options": {
                        "baseURL": f"http://127.0.0.1:{DEFAULT_BRIDGE_PORT}/v1",
                        "apiKey": bridge_service.bridge_token,
                    },
                    "models": {},
                }
                for model_id, info in CLAUDE_MODELS.items():
                    provider_cfg["models"][f"claude-pro/{model_id}"] = {
                        "name": info["name"],
                        "limit": info["limit"],
                    }
                cfg_data["provider"]["claude-pro"] = provider_cfg
            else:
                cfg_data["provider"].pop("claude-pro", None)

            cfg_path.write_text(json.dumps(cfg_data, indent=4, ensure_ascii=False), encoding="utf-8")
            return True
        except Exception as e:
            print(f"[Claude Manager] Failed to configure opencode.json: {e}")
            return False

    def login_claude_browser(self, timeout: int = 300, progress_callback=None) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        """Opens a dedicated browser window for user to log into claude.ai,
        automatically captures sessionKey cookie, and saves the verified account."""
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            return False, "Библиотека playwright не найдена.", None

        CLAUDE_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
        proxy = get_active_proxy()
        proxy_cfg = {"server": proxy} if proxy else None

        if progress_callback:
            progress_callback("Запуск браузера для входа в claude.ai...")

        p = None
        context = None
        try:
            p = sync_playwright().start()
            context = p.chromium.launch_persistent_context(
                str(CLAUDE_PROFILE_DIR),
                headless=False,
                proxy=proxy_cfg,
                user_agent=USER_AGENT,
                viewport={"width": 1280, "height": 800},
                args=["--disable-blink-features=AutomationControlled"]
            )
            page = context.pages[0] if context.pages else context.new_page()

            if progress_callback:
                progress_callback("Открываем claude.ai... Пожалуйста, выполните вход в аккаунт.")

            try:
                page.goto("https://claude.ai/login", wait_until="commit", timeout=30000)
            except Exception:
                pass

            deadline = time.monotonic() + timeout
            captured_key = None

            while time.monotonic() < deadline:
                try:
                    cookies = context.cookies(["https://claude.ai", "https://api.claude.ai"])
                    for c in cookies:
                        c_name = c.get("name", "")
                        c_val = c.get("value", "")
                        if c_name == "sessionKey" and c_val:
                            captured_key = c_val
                            break
                    if captured_key:
                        break
                except Exception:
                    pass

                time.sleep(1.5)

            try:
                context.close()
                p.stop()
            except Exception:
                pass

            if not captured_key:
                return False, "Время ожидания входа истекло (sessionKey не обнаружен в браузере).", None

            if progress_callback:
                progress_callback("sessionKey перехвачен! Проверяем аккаунт...")

            ok, msg, acc = self.verify_and_add_account(captured_key)
            if ok:
                return True, f"Успешно! sessionKey извлечен автоматически. Аккаунт: {acc.get('email', '')}", acc
            return False, f"Перехвачен sessionKey, но ошибка проверки: {msg}", None

        except Exception as e:
            if context:
                try:
                    context.close()
                except Exception:
                    pass
            if p:
                try:
                    p.stop()
                except Exception:
                    pass
            return False, f"Ошибка запуска браузера: {e}", None

    def refresh_claude_sessions_silent(self) -> None:
        """Periodically refreshes claude.ai sessionKey so it stays active and never expires."""
        accounts = self.load_accounts()
        changed = False

        for acc in accounts:
            if acc.get("token_type") != "session_key":
                continue

            session_key = acc.get("session_key", "")
            if not session_key:
                continue

            try:
                opener = get_http_opener(timeout=10)
                headers = {
                    "User-Agent": USER_AGENT,
                    "Cookie": f"sessionKey={session_key}",
                    "Accept": "application/json",
                }
                req = urllib.request.Request("https://claude.ai/api/auth/current_user", headers=headers)
                with opener.open(req, timeout=10) as resp:
                    set_cookie = resp.headers.get("Set-Cookie", "")
                    if "sessionKey=" in set_cookie:
                        for part in set_cookie.split(";"):
                            part = part.strip()
                            if part.startswith("sessionKey="):
                                new_key = part.split("=", 1)[1].strip()
                                if new_key and new_key != session_key:
                                    acc["session_key"] = new_key
                                    changed = True
                                    print(f"[Claude Manager] sessionKey auto-refreshed for {acc.get('email')}")
            except Exception:
                if CLAUDE_PROFILE_DIR.exists():
                    try:
                        from playwright.sync_api import sync_playwright
                        p = sync_playwright().start()
                        proxy = get_active_proxy()
                        proxy_cfg = {"server": proxy} if proxy else None
                        ctx = p.chromium.launch_persistent_context(
                            str(CLAUDE_PROFILE_DIR),
                            headless=True,
                            proxy=proxy_cfg,
                            user_agent=USER_AGENT
                        )
                        page = ctx.new_page()
                        page.goto("https://claude.ai/", wait_until="networkidle", timeout=15000)
                        cookies = ctx.cookies(["https://claude.ai", "https://api.claude.ai"])
                        for c in cookies:
                            if c.get("name") == "sessionKey" and c.get("value"):
                                new_val = c.get("value")
                                if new_val != session_key:
                                    acc["session_key"] = new_val
                                    changed = True
                                    print(f"[Claude Manager] Headless sessionKey renewal successful for {acc.get('email')}")
                        ctx.close()
                        p.stop()
                    except Exception:
                        pass

        if changed:
            self.save_accounts(accounts)


class ClaudeSubscriptionBridge:
    """Local HTTP bridge providing OpenAI/Anthropic compatible endpoint forwarding to claude.ai."""

    def __init__(self, port: int = DEFAULT_BRIDGE_PORT):
        self.port = port
        self.bridge_token = secrets.token_hex(16)
        self._server: Optional[HTTPServer] = None
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

    def ensure_running(self):
        with self._lock:
            if self._server is not None:
                return
            try:
                bridge_self = self

                class Handler(BaseHTTPRequestHandler):
                    def log_message(self, format, *args):
                        pass

                    def do_OPTIONS(self):
                        self.send_response(200)
                        self.send_header("Access-Control-Allow-Origin", "*")
                        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
                        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
                        self.end_headers()

                    def do_GET(self):
                        if self.path == "/v1/models":
                            data = {
                                "object": "list",
                                "data": [
                                    {"id": f"claude-pro/{m}", "object": "model", "owned_by": "anthropic-subscription"}
                                    for m in CLAUDE_MODELS.keys()
                                ]
                            }
                            resp_bytes = json.dumps(data).encode("utf-8")
                            self.send_response(200)
                            self.send_header("Content-Type", "application/json")
                            self.send_header("Content-Length", str(len(resp_bytes)))
                            self.end_headers()
                            self.wfile.write(resp_bytes)
                        else:
                            self.send_error(404, "Not Found")

                    def do_POST(self):
                        if not self.path.startswith("/v1/chat/completions") and not self.path.startswith("/v1/messages"):
                            self.send_error(404, "Not Found")
                            return

                        length = int(self.headers.get("Content-Length", 0))
                        body_bytes = self.rfile.read(length)
                        try:
                            payload = json.loads(body_bytes.decode("utf-8"))
                        except Exception:
                            self.send_error(400, "Invalid JSON payload")
                            return

                        acc = claude_service.get_active_account()
                        if not acc:
                            self.send_error(401, "No active Claude Pro account configured in Antigravity Hub")
                            return

                        # Forward to claude.ai API
                        bridge_self.handle_completion_request(self, payload, acc)

                self._server = HTTPServer(("127.0.0.1", self.port), Handler)
                self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
                self._thread.start()
            except Exception as e:
                print(f"[Claude Bridge] Failed to start server on port {self.port}: {e}")

    def handle_completion_request(self, handler: BaseHTTPRequestHandler, payload: dict, account: dict):
        """Translates completion requests into claude.ai conversation calls with streaming."""
        is_stream = payload.get("stream", False)
        requested_model = payload.get("model", "claude-pro/claude-3-7-sonnet").replace("claude-pro/", "")
        model_info = CLAUDE_MODELS.get(requested_model, CLAUDE_MODELS["claude-3-7-sonnet"])
        actual_model = model_info["api_model"]

        opener = get_http_opener(timeout=60)
        session_key = account.get("session_key", "")
        org_id = account.get("org_id", "")

        # Extract messages
        raw_messages = payload.get("messages", [])
        prompt_text = ""
        for m in raw_messages:
            role = m.get("role", "user")
            content = m.get("content", "")
            if isinstance(content, list):
                text_parts = [c.get("text", "") for c in content if isinstance(c, dict) and c.get("type") == "text"]
                content = "\n".join(text_parts)
            prompt_text += f"\n\n{role.capitalize()}: {content}"
        prompt_text += "\n\nAssistant:"

        req_headers = {
            "User-Agent": USER_AGENT,
            "Cookie": f"sessionKey={session_key}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream" if is_stream else "application/json",
        }

        claude_payload = {
            "prompt": prompt_text,
            "timezone": "Europe/Berlin",
            "model": actual_model,
        }

        if is_stream:
            handler.send_response(200)
            handler.send_header("Content-Type", "text/event-stream")
            handler.send_header("Cache-Control", "no-cache")
            handler.send_header("Connection", "keep-alive")
            handler.end_headers()

            # Stream synthetic response chunks
            chunk_id = f"chatcmpl-{secrets.token_hex(6)}"
            initial_chunk = {
                "id": chunk_id,
                "object": "chat.completion.chunk",
                "created": int(time.time()),
                "model": requested_model,
                "choices": [{"index": 0, "delta": {"role": "assistant", "content": ""}, "finish_reason": None}],
            }
            handler.wfile.write(f"data: {json.dumps(initial_chunk)}\n\n".encode("utf-8"))
            handler.wfile.flush()

            try:
                if account.get("token_type") == "api_token":
                    target_url = "https://api.anthropic.com/v1/messages"
                    anthropic_headers = {
                        "User-Agent": USER_AGENT,
                        "x-api-key": session_key,
                        "anthropic-version": "2023-06-01",
                        "Content-Type": "application/json",
                        "Accept": "text/event-stream",
                    }
                    anthropic_body = {
                        "model": actual_model,
                        "messages": [{"role": m.get("role", "user"), "content": m.get("content", "")} for m in raw_messages if m.get("role") in ("user", "assistant")],
                        "max_tokens": model_info.get("limit", {}).get("output", 4096),
                        "stream": True,
                    }
                    req = urllib.request.Request(target_url, data=json.dumps(anthropic_body).encode("utf-8"), headers=anthropic_headers)
                    with opener.open(req, timeout=45) as resp:
                        for line in resp:
                            if not line:
                                continue
                            line_str = line.decode("utf-8", errors="ignore")
                            if line_str.startswith("data: "):
                                try:
                                    ev = json.loads(line_str[6:].strip())
                                    delta_text = ""
                                    if ev.get("type") == "content_block_delta":
                                        delta_text = ev.get("delta", {}).get("text", "")
                                    if delta_text:
                                        c = {
                                            "id": chunk_id,
                                            "object": "chat.completion.chunk",
                                            "created": int(time.time()),
                                            "model": requested_model,
                                            "choices": [{"index": 0, "delta": {"content": delta_text}, "finish_reason": None}],
                                        }
                                        handler.wfile.write(f"data: {json.dumps(c)}\n\n".encode("utf-8"))
                                        handler.wfile.flush()
                                except Exception:
                                    pass
                else:
                    target_url = f"https://claude.ai/api/organizations/{org_id}/chat_conversations"
                    req = urllib.request.Request(target_url, data=json.dumps(claude_payload).encode("utf-8"), headers=req_headers)
                    with opener.open(req, timeout=45) as resp:
                        for line in resp:
                            if not line:
                                continue
                            line_str = line.decode("utf-8", errors="ignore")
                            if line_str.startswith("data: "):
                                try:
                                    data = json.loads(line_str[6:].strip())
                                    completion = data.get("completion") or data.get("text") or ""
                                    if completion:
                                        c = {
                                            "id": chunk_id,
                                            "object": "chat.completion.chunk",
                                            "created": int(time.time()),
                                            "model": requested_model,
                                            "choices": [{"index": 0, "delta": {"content": completion}, "finish_reason": None}],
                                        }
                                        handler.wfile.write(f"data: {json.dumps(c)}\n\n".encode("utf-8"))
                                        handler.wfile.flush()
                                except Exception:
                                    pass
            except Exception as e:
                err_chunk = {
                    "id": chunk_id,
                    "object": "chat.completion.chunk",
                    "created": int(time.time()),
                    "model": requested_model,
                    "choices": [{"index": 0, "delta": {"content": f"\n\n[Claude Subscription Error: {e}]"}, "finish_reason": "stop"}],
                }
                handler.wfile.write(f"data: {json.dumps(err_chunk)}\n\n".encode("utf-8"))

            final_chunk = {
                "id": chunk_id,
                "object": "chat.completion.chunk",
                "created": int(time.time()),
                "model": requested_model,
                "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
            }
            handler.wfile.write(f"data: {json.dumps(final_chunk)}\n\n".encode("utf-8"))
            handler.wfile.write(b"data: [DONE]\n\n")
            handler.wfile.flush()
        else:
            # Non-streaming fallback
            try:
                target_url = f"https://claude.ai/api/organizations/{org_id}/chat_conversations"
                req = urllib.request.Request(target_url, data=json.dumps(claude_payload).encode("utf-8"), headers=req_headers)
                with opener.open(req, timeout=45) as resp:
                    raw_text = resp.read().decode("utf-8")
                    resp_obj = {
                        "id": f"chatcmpl-{secrets.token_hex(6)}",
                        "object": "chat.completion",
                        "created": int(time.time()),
                        "model": requested_model,
                        "choices": [{
                            "index": 0,
                            "message": {"role": "assistant", "content": raw_text},
                            "finish_reason": "stop"
                        }],
                    }
                    data_bytes = json.dumps(resp_obj).encode("utf-8")
                    handler.send_response(200)
                    handler.send_header("Content-Type", "application/json")
                    handler.send_header("Content-Length", str(len(data_bytes)))
                    handler.end_headers()
                    handler.wfile.write(data_bytes)
            except Exception as e:
                handler.send_error(500, f"Claude Proxy Error: {e}")


# Singleton instances
claude_service = ClaudeAccountManager()
bridge_service = ClaudeSubscriptionBridge()
