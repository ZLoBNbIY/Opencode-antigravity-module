"""
Anthropic Claude Pro / Team Account and Subscription Bridge for AI HUB.
Enables using Claude Pro / Team accounts in OpenCode without pay-per-token API keys.
"""

import os
import sys
import json
import time
import hmac
import socket
import secrets
import uuid
import threading
import urllib.request
import urllib.parse
import urllib.error
import http.client
from pathlib import Path
from http.server import BaseHTTPRequestHandler
from typing import Optional, Dict, Any, List, Tuple

import secure_storage
from provider_proxy import _BoundedHandler, _ThreadingServer

try:
    import hub_paths
    CONFIG_DIR = hub_paths.OPENCODE_CONFIG_DIR
    CLAUDE_ACCOUNTS_FILE = hub_paths.ACCOUNTS_DIR / "claude-accounts.json"
    CLAUDE_PROFILE_DIR = hub_paths.CLAUDE_PROFILE_DIR
    BRIDGE_TOKEN_FILE = hub_paths.SECURE_DIR / "claude-bridge-token.json"
except Exception:
    CONFIG_DIR = Path.home() / ".config" / "opencode"
    CLAUDE_ACCOUNTS_FILE = CONFIG_DIR / "claude-accounts.json"
    CLAUDE_PROFILE_DIR = CONFIG_DIR / "claude_profile"
    BRIDGE_TOKEN_FILE = CONFIG_DIR / "claude-bridge-token.json"
DEFAULT_BRIDGE_PORT = 51186
MAX_BRIDGE_BODY = 10 * 1024 * 1024
MAX_UPSTREAM_BODY = 16 * 1024 * 1024
MAX_EVENT_LINE = 1024 * 1024


class _BridgeServer(_ThreadingServer):
    max_workers = 8


def _response_chunks(response, limit):
    deadline = time.monotonic() + 300
    # read1 allows the deadline to be checked between socket reads.
    read = response.read1
    while time.monotonic() < deadline:
        chunk = read(min(65536, limit + 1))
        if not chunk:
            return
        limit -= len(chunk)
        if limit < 0:
            raise ValueError("Claude upstream response too large")
        yield chunk
    raise TimeoutError("Claude upstream response timed out")


def _response_lines(response):
    pending = bytearray()
    for chunk in _response_chunks(response, MAX_UPSTREAM_BODY):
        parts = chunk.split(b"\n")
        for part in parts[:-1]:
            pending.extend(part)
            if len(pending) > MAX_EVENT_LINE:
                raise ValueError("Claude event line too large")
            yield bytes(pending)
            pending.clear()
        pending.extend(parts[-1])
        if len(pending) > MAX_EVENT_LINE:
            raise ValueError("Claude event line too large")
    if pending:
        yield bytes(pending)

CLAUDE_MODELS = {
    "claude-opus-5": {
        "name": "Claude Opus 5",
        "api_model": "claude-opus-5",
        "limit": {"context": 200000, "output": 64000},
    },
    "claude-opus-4-8": {
        "name": "Claude Opus 4.8",
        "api_model": "claude-opus-4-8",
        "limit": {"context": 200000, "output": 64000},
    },
    "claude-opus-4-7": {
        "name": "Claude Opus 4.7",
        "api_model": "claude-opus-4-7",
        "limit": {"context": 200000, "output": 64000},
    },
    "claude-sonnet-5": {
        "name": "Claude Sonnet 5",
        "api_model": "claude-sonnet-5",
        "limit": {"context": 200000, "output": 64000},
    },
    "claude-sonnet-4-6": {
        "name": "Claude Sonnet 4.6",
        "api_model": "claude-sonnet-4-6",
        "limit": {"context": 200000, "output": 64000},
    },
    "claude-haiku-4-5": {
        "name": "Claude Haiku 4.5",
        "api_model": "claude-haiku-4-5",
        "limit": {"context": 200000, "output": 8192},
    },
    "claude-fable-5": {
        "name": "Claude Fable 5",
        "api_model": "claude-fable-5",
        "limit": {"context": 200000, "output": 64000},
    },
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
    """Return the dispatcher; it applies the Claude provider route by host."""
    import provider_proxy
    return provider_proxy.proxy_url_for_hub_requests()


def get_http_opener(timeout: int = 15) -> urllib.request.OpenerDirector:
    proxy = get_active_proxy()
    return urllib.request.build_opener(
        urllib.request.ProxyHandler({"http": proxy, "https": proxy}), _NoRedirect())


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def _api_opener(base_url):
    """Keep credentialed requests scoped to the selected HTTPS origin."""
    import provider_proxy

    url, host, port = provider_proxy._origin(base_url)
    if url.scheme != "https" or url.query:
        raise ValueError("Claude API requires an HTTPS base URL")
    if provider_proxy._builtin_host(host) and port == 443:
        return get_http_opener()
    config = provider_proxy._read_json(provider_proxy.CONFIG_DIR / "opencode.json")
    routes = dict(config.get("provider") or {})
    routes["claude-pro"] = {"options": {"baseURL": base_url}}
    config = {**config, "provider": routes}

    class OriginConnection(http.client.HTTPSConnection):
        def connect(self):
            if (provider_proxy._public_host(self.host), self.port) != (host, port):
                raise ValueError("Unexpected Claude API origin")
            sock, _ = provider_proxy.connect_public_routed(host, port, config)
            try:
                sock.settimeout(self.timeout)
                self.sock = self._context.wrap_socket(sock, server_hostname=host)
            except BaseException:
                sock.close()
                raise

    class OriginHandler(urllib.request.HTTPSHandler):
        def https_open(self, request):
            return self.do_open(OriginConnection, request, context=self._context)

    return urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect(), OriginHandler())


class ClaudeAccountManager:
    """Manages Claude Pro / Team accounts and subscriptions."""

    def __init__(self):
        self._lock = threading.RLock()
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _read_account_file(path):
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        protected = isinstance(data, dict) and ("protection" in data or "payload" in data)
        if protected:
            data = secure_storage.unprotect_payload(data, "claude-accounts")
        accounts = data.get("accounts") if isinstance(data, dict) else None
        if not isinstance(accounts, list) or any(not isinstance(a, dict) for a in accounts):
            raise ValueError("Invalid Claude account store")
        return accounts, protected

    def load_accounts(self) -> List[Dict[str, Any]]:
        with self._lock:
            source = CLAUDE_ACCOUNTS_FILE
            if not source.exists():
                source = CONFIG_DIR / "claude-accounts.json"
                if not source.exists():
                    return []
            try:
                accounts, protected = self._read_account_file(source)
            except Exception:
                print("[Claude Manager] Unable to read account store")
                return []
            if not protected or source != CLAUDE_ACCOUNTS_FILE:
                self.save_accounts(accounts)
            return accounts

    def save_accounts(self, accounts: List[Dict[str, Any]]) -> bool:
        with self._lock:
            try:
                if CLAUDE_ACCOUNTS_FILE.exists():
                    self._read_account_file(CLAUDE_ACCOUNTS_FILE)
                record = secure_storage.protect_payload("claude-accounts", {"accounts": accounts})
                secure_storage.atomic_write(
                    CLAUDE_ACCOUNTS_FILE,
                    json.dumps(record, indent=2, ensure_ascii=False),
                )
                return True
            except Exception as e:
                print(f"[Claude Manager] Error saving accounts ({type(e).__name__})")
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
        if found and self.save_accounts(accounts):
            self.configure_opencode_provider()
            return True
        return False

    def delete_account(self, email: str) -> bool:
        accounts = self.load_accounts()
        new_accs = [a for a in accounts if a.get("email") != email]
        if len(new_accs) != len(accounts):
            if new_accs and not any(a.get("active") for a in new_accs):
                new_accs[0]["active"] = True
            if not self.save_accounts(new_accs):
                return False
            self.configure_opencode_provider()
            return True
        return False

    def verify_and_add_account(self, session_key: str, custom_name: str = "", base_url: str = "") -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        """Validates claude.ai sessionKey, Claude Code setup-token, or third-party Claude API (e.g. Xpiki) and saves account."""
        session_key = session_key.strip()
        base_url = (base_url or "").strip().rstrip("/")
        if not session_key:
            return False, "Укажите sessionKey (куки claude.ai) или API-ключ Claude (sk-...)", None

        # Case A: Anthropic API / Third-Party Proxy (Xpiki, etc.) / Claude Code setup-token
        is_api_token = session_key.startswith("sk-ant-api") or session_key.startswith("sk-") or bool(base_url)
        if is_api_token and not session_key.startswith("sk-ant-sid"):
            target_base = base_url or "https://api.anthropic.com/v1"
            try:
                opener = _api_opener(target_base)
            except (ValueError, OSError):
                return False, "Укажите доступный HTTPS URL для Claude API.", None
            test_url = f"{target_base}/models"
            headers = {
                "User-Agent": USER_AGENT,
                "x-api-key": session_key,
                "Authorization": f"Bearer {session_key}",
                "anthropic-version": "2023-06-01",
            }
            try:
                req = urllib.request.Request(test_url, headers=headers)
                with opener.open(req, timeout=12) as resp:
                    data = json.loads(b"".join(_response_chunks(resp, MAX_UPSTREAM_BODY)))
            except Exception:
                # Fallback probe to /messages with small ping
                try:
                    probe_body = {
                        "model": "claude-3-5-haiku-20241022" if "anthropic.com" in target_base else "claude-haiku-4-5",
                        "max_tokens": 10,
                        "messages": [{"role": "user", "content": "ping"}]
                    }
                    probe_req = urllib.request.Request(
                        f"{target_base}/messages",
                        data=json.dumps(probe_body).encode("utf-8"),
                        headers={**headers, "Content-Type": "application/json"}
                    )
                    with opener.open(probe_req, timeout=12) as resp:
                        data = json.loads(b"".join(_response_chunks(resp, MAX_UPSTREAM_BODY)))
                except urllib.error.HTTPError as e:
                    return False, f"Ошибка авторизации Claude API ({e.code}): недействительный ключ или эндпоинт {target_base}.", None
                except Exception as e:
                    return False, f"Ошибка подключения к {target_base}: {e}", None

            domain_label = urllib.parse.urlparse(target_base).netloc or "anthropic"
            email = custom_name or (f"claude-api@{domain_label}" if domain_label != "api.anthropic.com" else "claude-code@anthropic")
            account_data = {
                "email": email,
                "name": custom_name or ("Claude API (Xpiki)" if "xpiki" in target_base else "Claude API"),
                "session_key": session_key,
                "base_url": target_base,
                "token_type": "api_token",
                "org_id": domain_label,
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

            if not self.save_accounts(accounts):
                return False, "Не удалось сохранить аккаунт Claude.", None
            self.configure_opencode_provider()
            self.configure_claude_cli_settings(session_key, target_base)
            return True, f"Аккаунт Claude API ({email}) успешно подключён!", account_data

        # Case B: claude.ai Web Session (sessionKey cookie: sk-ant-sid...)
        if not session_key.startswith("sk-ant-"):
            if not session_key.startswith("sid01-"):
                return False, (
                    "Введённое значение не является sessionKey или API-токеном Claude!\n\n"
                    "• Для сессии claude.ai: cookie называется 'sessionKey' (начинается с sk-ant-sid01-...).\n"
                    "• Для Claude API (Xpiki): токен начинается с sk-..."
                ), None
            session_key = f"sk-ant-{session_key}"

        headers = {
            "User-Agent": USER_AGENT,
            "Cookie": f"sessionKey={session_key}",
            "Accept": "application/json",
        }

        try:
            opener = get_http_opener(timeout=15)
            req = urllib.request.Request("https://claude.ai/api/organizations", headers=headers)
            with opener.open(req, timeout=10) as resp:
                orgs = json.loads(b"".join(_response_chunks(resp, MAX_UPSTREAM_BODY)))

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
                    u_data = json.loads(b"".join(_response_chunks(resp, MAX_UPSTREAM_BODY)))
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

            if not self.save_accounts(accounts):
                return False, "Не удалось сохранить аккаунт Claude.", None
            self.configure_opencode_provider()
            return True, f"Аккаунт {email} ({plan_type.upper()}) успешно подключён!", account_data
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                return False, f"Ошибка авторизации claude.ai ({e.code}). Сессия истекла или заблокирована.", None
            return False, f"Ошибка API claude.ai: {e}", None
        except Exception as e:
            return False, f"Ошибка проверки сессии: {e}", None

    def configure_opencode_provider(self) -> bool:
        """Configures the claude-pro provider in ~/.config/opencode/opencode.json(c)."""
        import jsonc_config
        active_acc = self.get_active_account()
        try:
            cfg_path = jsonc_config.config_path(CONFIG_DIR)
            original = cfg_path.read_text(encoding="utf-8-sig") if cfg_path.exists() else "{}\n"
            cfg_data = jsonc_config.parse_config(original)

            if active_acc:
                bridge_service.ensure_running()
                provider_cfg = {
                    "npm": "@ai-sdk/openai-compatible",
                    "name": "Claude Pro (AI HUB)",
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
                updated = jsonc_config.set_property(original, ("provider", "claude-pro"), provider_cfg)
            else:
                providers = cfg_data.get("provider", {})
                if isinstance(providers, dict) and "claude-pro" in providers:
                    updated = jsonc_config.set_property(original, ("provider", "claude-pro", "models"), {})
                else:
                    updated = original

            if updated != original or not cfg_path.exists():
                secure_storage.atomic_write(cfg_path, updated)
            try:
                import opencode_config
                opencode_config.ensure_session_title_config(cfg_path)
            except Exception:
                pass
            return True
        except Exception as e:
            print(f"[Claude Manager] Failed to configure opencode.json: {e}")
            return False

    def configure_claude_cli_settings(self, api_token: str, base_url: str = "https://api.xpiki.com/v1", model: str = "claude-opus-5") -> Tuple[bool, str]:
        """Configures ~/.claude/settings.json for official Claude Code CLI according to the Teletype guide."""
        try:
            claude_dir = Path.home() / ".claude"
            claude_dir.mkdir(parents=True, exist_ok=True)
            settings_path = claude_dir / "settings.json"
            data: Dict[str, Any] = {}
            if settings_path.exists():
                try:
                    data = json.loads(settings_path.read_text(encoding="utf-8"))
                except Exception:
                    data = {}
            env_block = data.setdefault("env", {})
            env_block["ANTHROPIC_AUTH_TOKEN"] = api_token.strip()
            env_block["ANTHROPIC_BASE_URL"] = (base_url or "https://api.xpiki.com/v1").strip().rstrip("/")
            env_block["ANTHROPIC_MODEL"] = model.strip()
            settings_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
            return True, f"Настройки Claude Code CLI записаны в {settings_path}"
        except Exception as e:
            return False, f"Ошибка записи ~/.claude/settings.json: {e}"

    def configure_claude_desktop_settings(self, api_token: str, base_url: str = "https://api.xpiki.com/v1") -> Tuple[bool, str]:
        """Configures Claude Desktop config (%APPDATA%/Claude/claude_desktop_config.json) for third-party inference."""
        try:
            appdata = os.environ.get("APPDATA")
            if not appdata:
                return False, "APPDATA environment variable not found"
            claude_desktop_dir = Path(appdata) / "Claude"
            claude_desktop_dir.mkdir(parents=True, exist_ok=True)
            cfg_path = claude_desktop_dir / "claude_desktop_config.json"
            data: Dict[str, Any] = {}
            if cfg_path.exists():
                try:
                    data = json.loads(cfg_path.read_text(encoding="utf-8"))
                except Exception:
                    data = {}
            inference = data.setdefault("thirdPartyInference", {})
            inference["baseUrl"] = (base_url or "https://api.xpiki.com/v1").strip().rstrip("/")
            inference["apiKey"] = api_token.strip()
            cfg_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
            return True, f"Настройки Claude Desktop записаны в {cfg_path}"
        except Exception as e:
            return False, f"Ошибка настройки Claude Desktop: {e}"

    def login_claude_browser(self, mode: str = "tunnel", timeout: int = 300, progress_callback=None) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        """Opens a browser window for user to log into claude.ai,
        automatically captures sessionKey cookie, and saves the verified account.
        mode can be 'tunnel' (built-in browser through VLESS tunnel) or 'default' (system default browser)."""
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            return False, "Библиотека playwright не найдена.", None

        CLAUDE_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
        proxy = get_active_proxy()
        proxy_cfg = {"server": proxy} if proxy else None

        # Determine browser executable based on mode
        executable_path = None
        browser_desc = "встроенного браузера Chromium"
        if mode == "default":
            try:
                import browser_paths
                b_paths = browser_paths.browser_paths()
                cand = b_paths.get("default") or b_paths.get("chrome") or b_paths.get("edge")
                if cand and browser_paths.supports_cdp(cand):
                    executable_path = str(cand)
                    browser_desc = f"дефолтного браузера ({Path(executable_path).name})"
            except Exception:
                pass

        if progress_callback:
            tunnel_info = "через VLESS-туннель" if proxy else "прямое подключение"
            progress_callback(f"Запуск {browser_desc} ({tunnel_info})...")

        p = None
        context = None
        try:
            p = sync_playwright().start()
            launch_args = ["--disable-blink-features=AutomationControlled"]
            launch_kwargs = {
                "headless": False,
                "proxy": proxy_cfg,
                "user_agent": USER_AGENT,
                "viewport": {"width": 1280, "height": 800},
                "args": launch_args,
            }
            if executable_path:
                launch_kwargs["executable_path"] = executable_path

            context = p.chromium.launch_persistent_context(
                str(CLAUDE_PROFILE_DIR),
                **launch_kwargs
            )
            page = context.pages[0] if context.pages else context.new_page()

            if progress_callback:
                progress_callback("Открываем claude.ai... Пожалуйста, войдите в аккаунт.")

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
                    p = None
                    ctx = None
                    try:
                        from playwright.sync_api import sync_playwright
                        p = sync_playwright().start()
                        proxy = get_active_proxy()
                        proxy_cfg = {"server": proxy} if proxy else None
                        browser_options = {"channel": "chromium"} if getattr(sys, "frozen", False) else {}
                        ctx = p.chromium.launch_persistent_context(
                            str(CLAUDE_PROFILE_DIR),
                            headless=True,
                            proxy=proxy_cfg,
                            user_agent=USER_AGENT,
                            **browser_options,
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
                    except Exception:
                        pass
                    finally:
                        if ctx is not None:
                            try:
                                ctx.close()
                            except Exception:
                                pass
                        if p is not None:
                            try:
                                p.stop()
                            except Exception:
                                pass

        if changed:
            self.save_accounts(accounts)


class ClaudeSubscriptionBridge:
    """Local HTTP bridge providing OpenAI/Anthropic compatible endpoint forwarding to claude.ai."""

    def __init__(self, port: int = DEFAULT_BRIDGE_PORT):
        self.port = port
        self.bridge_token = self._load_or_create_token()
        self._server: Optional[_BridgeServer] = None
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

    @staticmethod
    def _load_or_create_token() -> str:
        try:
            if BRIDGE_TOKEN_FILE.exists():
                record = json.loads(BRIDGE_TOKEN_FILE.read_text(encoding="utf-8"))
                data = secure_storage.unprotect_payload(record, "claude-bridge-token")
                tok = str(data.get("token") or "").strip()
                if tok:
                    return tok
        except Exception:
            pass
        # Adopt existing token from opencode.json(c) if already configured
        try:
            import jsonc_config
            oc_path = jsonc_config.config_path(CONFIG_DIR)
            if oc_path.exists():
                oc = jsonc_config.parse_config(oc_path.read_text(encoding="utf-8-sig"))
                existing = str(
                    oc.get("provider", {}).get("claude-pro", {}).get("options", {}).get("apiKey") or ""
                ).strip()
                if existing:
                    try:
                        rec = secure_storage.protect_payload("claude-bridge-token", {"token": existing})
                        secure_storage.atomic_write(BRIDGE_TOKEN_FILE, json.dumps(rec))
                    except Exception:
                        pass
                    return existing
        except Exception:
            pass
        token = secrets.token_hex(16)
        try:
            rec = secure_storage.protect_payload("claude-bridge-token", {"token": token})
            secure_storage.atomic_write(BRIDGE_TOKEN_FILE, json.dumps(rec))
        except Exception:
            pass
        return token

    def _is_authorized(self, headers) -> bool:
        def matches(token):
            return hmac.compare_digest(token.encode("utf-8"), self.bridge_token.encode("utf-8"))

        if hasattr(headers, "get_all") and any(len(headers.get_all(name, [])) > 1
                                              for name in ("Authorization", "x-api-key")):
            return False
        auth = str(headers.get("Authorization") or "").strip()
        if auth.lower().startswith("bearer "):
            token = auth[7:].strip()
            if token and matches(token):
                return True
        api_key = str(headers.get("x-api-key") or "").strip()
        if api_key and matches(api_key):
            return True
        return False

    def ensure_running(self):
        with self._lock:
            if self._server is not None:
                return
            try:
                bridge_self = self

                class Handler(_BoundedHandler):
                    def parse_request(self):
                        if not super().parse_request():
                            return False
                        if "Origin" in self.headers or "Sec-Fetch-Site" in self.headers:
                            self.send_error(403, "Browser requests are not permitted")
                            return False
                        return True

                    def do_OPTIONS(self):
                        self.send_error(405, "Method Not Allowed")

                    def do_GET(self):
                        if not bridge_self._is_authorized(self.headers):
                            self.send_error(401, "Unauthorized")
                            return
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
                        if not bridge_self._is_authorized(self.headers):
                            self.send_error(401, "Unauthorized")
                            return
                        if self.path not in ("/v1/chat/completions", "/v1/messages", "/v1/messages?beta=true"):
                            self.send_error(404, "Not Found")
                            return

                        body_bytes = self._read_body(MAX_BRIDGE_BODY, required=True)
                        if body_bytes is None:
                            return
                        try:
                            payload = json.loads(body_bytes.decode("utf-8"))
                        except (ValueError, RecursionError):
                            self.send_error(400, "Invalid JSON payload")
                            return
                        if not isinstance(payload, dict) or not isinstance(payload.get("model", ""), str):
                            self.send_error(400, "Invalid completion payload")
                            return
                        messages = payload.get("messages", [])
                        if not isinstance(messages, list) or any(
                            not isinstance(msg, dict) or not isinstance(msg.get("content", ""), (str, list))
                            for msg in messages
                        ):
                            self.send_error(400, "Invalid completion messages")
                            return

                        acc = claude_service.get_active_account()
                        if not acc:
                            self.send_error(401, "No active Claude Pro account configured in AI HUB")
                            return

                        # Forward to claude.ai API
                        bridge_self.handle_completion_request(self, payload, acc)

                self._server = _BridgeServer(("127.0.0.1", self.port), Handler)
                self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
                self._thread.start()
            except Exception as e:
                print(f"[Claude Bridge] Failed to start server on port {self.port}: {e}")

    def _claude_web_completion_url(self, opener, org_id: str, req_headers: dict) -> str:
        safe_org = urllib.parse.quote(str(org_id or ""), safe="")
        conv_uuid = str(uuid.uuid4())
        create_url = f"https://claude.ai/api/organizations/{safe_org}/chat_conversations"
        create_req = urllib.request.Request(
            create_url,
            data=json.dumps({"uuid": conv_uuid, "name": ""}).encode("utf-8"),
            headers={**req_headers, "Accept": "application/json"},
        )
        with opener.open(create_req, timeout=20) as resp:
            for _ in _response_chunks(resp, 128 * 1024):
                pass
        return f"https://claude.ai/api/organizations/{safe_org}/chat_conversations/{conv_uuid}/completion"

    def handle_completion_request(self, handler: BaseHTTPRequestHandler, payload: dict, account: dict):
        """Translates completion requests into claude.ai conversation calls with streaming and compaction filtering."""
        is_stream = payload.get("stream", False)
        requested_model = payload.get("model", "claude-pro/claude-3-7-sonnet").replace("claude-pro/", "")
        model_info = CLAUDE_MODELS.get(requested_model, CLAUDE_MODELS.get("claude-3-7-sonnet", {}))
        actual_model = model_info.get("api_model", requested_model)

        session_key = account.get("session_key", "")
        org_id = account.get("org_id", "")
        base_url = account.get("base_url") or "https://api.anthropic.com/v1"
        try:
            opener = _api_opener(base_url) if account.get("token_type") == "api_token" else get_http_opener()
        except (ValueError, OSError):
            handler.send_error(502, "Claude upstream is unavailable")
            return

        # Extract messages and separate system prompt
        raw_messages = payload.get("messages", [])
        system_parts = []
        conversation_messages = []

        for m in raw_messages:
            role = m.get("role", "user")
            content = m.get("content", "")
            if isinstance(content, list):
                text_parts = [c["text"] for c in content if isinstance(c, dict)
                              and c.get("type") == "text" and isinstance(c.get("text"), str)]
                content = "\n".join(text_parts)
            if role == "system":
                system_parts.append(content)
            elif role in ("user", "assistant"):
                conversation_messages.append({"role": role, "content": content})

        system_text = "\n\n".join(system_parts) if system_parts else ""
        is_compaction = "<summary>" in system_text or any("<summary>" in m.get("content", "") for m in conversation_messages)

        prompt_text = ""
        if system_text:
            prompt_text += f"\n\nSystem: {system_text}"
            if is_compaction:
                prompt_text += "\n\nCRITICAL INSTRUCTION: Output MUST begin immediately with <summary> and end with </summary>. Do NOT output any intro or greeting."

        for m in conversation_messages:
            prompt_text += f"\n\n{m['role'].capitalize()}: {m['content']}"
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
            handler.send_header("Connection", "close")
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

            compaction_buffer = ""
            summary_started = not is_compaction

            def emit_chunk(delta_text: str):
                nonlocal compaction_buffer, summary_started
                if not isinstance(delta_text, str) or not delta_text:
                    return
                if is_compaction and not summary_started:
                    compaction_buffer += delta_text
                    if "<summary>" in compaction_buffer:
                        summary_started = True
                        clean_text = compaction_buffer[compaction_buffer.index("<summary>"):]
                        c = {
                            "id": chunk_id,
                            "object": "chat.completion.chunk",
                            "created": int(time.time()),
                            "model": requested_model,
                            "choices": [{"index": 0, "delta": {"content": clean_text}, "finish_reason": None}],
                        }
                        handler.wfile.write(f"data: {json.dumps(c)}\n\n".encode("utf-8"))
                        handler.wfile.flush()
                    return

                c = {
                    "id": chunk_id,
                    "object": "chat.completion.chunk",
                    "created": int(time.time()),
                    "model": requested_model,
                    "choices": [{"index": 0, "delta": {"content": delta_text}, "finish_reason": None}],
                }
                handler.wfile.write(f"data: {json.dumps(c)}\n\n".encode("utf-8"))
                handler.wfile.flush()

            try:
                if account.get("token_type") == "api_token":
                    target_url = f"{base_url.rstrip('/')}/messages"
                    anthropic_headers = {
                        "User-Agent": USER_AGENT,
                        "x-api-key": session_key,
                        "Authorization": f"Bearer {session_key}",
                        "anthropic-version": "2023-06-01",
                        "Content-Type": "application/json",
                        "Accept": "text/event-stream",
                    }
                    anthropic_body = {
                        "model": actual_model,
                        "messages": conversation_messages or [{"role": "user", "content": "Hello"}],
                        "max_tokens": model_info.get("limit", {}).get("output", 4096),
                        "stream": True,
                    }
                    if system_text:
                        anthropic_body["system"] = system_text
                        if is_compaction:
                            anthropic_body["system"] += "\n\nCRITICAL INSTRUCTION: Output MUST begin immediately with <summary> and end with </summary>. Do NOT output any intro or greeting before <summary>."

                    req = urllib.request.Request(target_url, data=json.dumps(anthropic_body).encode("utf-8"), headers=anthropic_headers)
                    with opener.open(req, timeout=45) as resp:
                        for line in _response_lines(resp):
                            if not line:
                                continue
                            line_str = line.decode("utf-8", errors="ignore")
                            if line_str.startswith("data: "):
                                try:
                                    ev = json.loads(line_str[6:].strip())
                                    delta_text = ""
                                    if ev.get("type") == "content_block_delta":
                                        delta_text = ev.get("delta", {}).get("text", "")
                                    emit_chunk(delta_text)
                                except (ValueError, AttributeError):
                                    pass
                else:
                    target_url = self._claude_web_completion_url(opener, org_id, req_headers)
                    req = urllib.request.Request(target_url, data=json.dumps(claude_payload).encode("utf-8"), headers=req_headers)
                    with opener.open(req, timeout=45) as resp:
                        for line in _response_lines(resp):
                            if not line:
                                continue
                            line_str = line.decode("utf-8", errors="ignore")
                            if line_str.startswith("data: "):
                                try:
                                    data = json.loads(line_str[6:].strip())
                                    completion = data.get("completion") or data.get("text") or ""
                                    emit_chunk(completion)
                                except (ValueError, AttributeError):
                                    pass
            except (BrokenPipeError, ConnectionResetError):
                return
            except Exception:
                err_chunk = {
                    "id": chunk_id,
                    "object": "chat.completion.chunk",
                    "created": int(time.time()),
                    "model": requested_model,
                    "choices": [{"index": 0, "delta": {"content": "\n\n[Claude upstream request failed]"}, "finish_reason": "stop"}],
                }
                handler.wfile.write(f"data: {json.dumps(err_chunk)}\n\n".encode("utf-8"))
                handler.wfile.write(b"data: [DONE]\n\n")
                return

            # If compaction summary was not found in buffer, wrap buffer in summary tags
            if is_compaction and not summary_started and compaction_buffer:
                fallback_summary = f"<summary>\n{compaction_buffer.strip()}\n</summary>"
                c = {
                    "id": chunk_id,
                    "object": "chat.completion.chunk",
                    "created": int(time.time()),
                    "model": requested_model,
                    "choices": [{"index": 0, "delta": {"content": fallback_summary}, "finish_reason": None}],
                }
                handler.wfile.write(f"data: {json.dumps(c)}\n\n".encode("utf-8"))

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
                if account.get("token_type") == "api_token":
                    target_url = f"{base_url.rstrip('/')}/messages"
                    anthropic_headers = {
                        "User-Agent": USER_AGENT,
                        "x-api-key": session_key,
                        "Authorization": f"Bearer {session_key}",
                        "anthropic-version": "2023-06-01",
                        "Content-Type": "application/json",
                    }
                    anthropic_body = {
                        "model": actual_model,
                        "messages": conversation_messages or [{"role": "user", "content": "Hello"}],
                        "max_tokens": model_info.get("limit", {}).get("output", 4096),
                    }
                    if system_text:
                        anthropic_body["system"] = system_text
                    req = urllib.request.Request(target_url, data=json.dumps(anthropic_body).encode("utf-8"), headers=anthropic_headers)
                    with opener.open(req, timeout=45) as resp:
                        res_json = json.loads(b"".join(_response_chunks(resp, MAX_UPSTREAM_BODY)))
                        text_blocks = [c.get("text", "") for c in res_json.get("content", []) if c.get("type") == "text"]
                        raw_text = "".join(text_blocks)
                else:
                    target_url = self._claude_web_completion_url(opener, org_id, req_headers)
                    req = urllib.request.Request(target_url, data=json.dumps(claude_payload).encode("utf-8"), headers=req_headers)
                    with opener.open(req, timeout=45) as resp:
                        body_text = b"".join(_response_chunks(resp, MAX_UPSTREAM_BODY)).decode("utf-8", errors="ignore")
                    if "data: " in body_text:
                        parts = []
                        for line_str in body_text.splitlines():
                            if line_str.startswith("data: "):
                                try:
                                    ev = json.loads(line_str[6:].strip())
                                    parts.append(ev.get("completion") or ev.get("text") or "")
                                except Exception:
                                    pass
                        raw_text = "".join(parts)
                    else:
                        try:
                            parsed_body = json.loads(body_text)
                            raw_text = parsed_body.get("completion") or parsed_body.get("text") or body_text
                        except Exception:
                            raw_text = body_text

                if is_compaction and "<summary>" in raw_text:
                    raw_text = raw_text[raw_text.index("<summary>"):]
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
            except (BrokenPipeError, ConnectionResetError):
                return
            except Exception:
                handler.send_error(502, "Claude upstream request failed")


# Singleton instances
claude_service = ClaudeAccountManager()
bridge_service = ClaudeSubscriptionBridge()
