"""
OpenAI / ChatGPT Account and Quota Manager for Antigravity Hub
"""

import os
import sys
import json
import time
import base64
import secrets
import hashlib
import webbrowser
import threading
import subprocess
import tempfile
import sqlite3
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler
import urllib.request
import urllib.parse

OPENAI_CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
OPENAI_ISSUER = "https://auth.openai.com"
OPENAI_CALLBACK_PORT = 1455
OPENAI_USAGE_URL = "https://chatgpt.com/backend-api/wham/usage"

CONFIG_DIR = Path(os.path.expanduser("~/.config/opencode"))
OPENAI_ACCOUNTS_FILE = CONFIG_DIR / "openai-accounts.json"
AUTH_FILES = [
    Path(os.path.expanduser("~/.local/share/opencode/auth.json")),
    Path(os.path.expanduser("~/.opencode/auth.json")),
]
OPENCODE_DB_FILE = Path(os.path.expanduser("~/.local/share/opencode/opencode.db"))


def find_opencode_cli() -> str | None:
    candidates = [
        Path(os.path.expanduser("~\\AppData\\Roaming\\ai.opencode.desktop\\cli\\2.0.27\\opencode-cli.exe")),
        Path(r"C:\Users\DevOps\AppData\Local\Programs\@opencode-aidesktop\resources\opencode-cli.exe"),
    ]
    base = Path(os.path.expanduser("~\\AppData\\Roaming\\ai.opencode.desktop\\cli"))
    if base.exists():
        for p in base.glob("*/opencode-cli.exe"):
            if p.exists():
                return str(p)
    for c in candidates:
        if c.exists():
            return str(c)
    return None


def get_openai_cred_id() -> str:
    if OPENCODE_DB_FILE.exists():
        try:
            conn = sqlite3.connect(str(OPENCODE_DB_FILE), timeout=5)
            cur = conn.cursor()
            cur.execute("SELECT id FROM credential WHERE integration_id = 'openai'")
            row = cur.fetchone()
            conn.close()
            if row:
                return row[0]
        except Exception:
            pass
    return "cred_openai_active"


def sync_opencode_db_openai(account: dict | None):
    """Sync OpenAI credential directly into opencode.db SQLite database."""
    if not OPENCODE_DB_FILE.exists():
        return
    try:
        conn = sqlite3.connect(str(OPENCODE_DB_FILE), timeout=5)
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='credential'")
        if not cur.fetchone():
            conn.close()
            return

        if account:
            val_json = json.dumps({
                "type": "oauth",
                "methodID": "chatgpt-browser",
                "refresh": account.get("refresh", ""),
                "access": account.get("access", ""),
                "expires": account.get("expires", 0),
                "metadata": {
                    "accountID": account.get("accountId", ""),
                    "email": account.get("email", ""),
                }
            }, ensure_ascii=False)
            label = account.get("name") or account.get("email") or "ChatGPT OAuth"
            now_ms = int(time.time() * 1000)

            cur.execute("SELECT id FROM credential WHERE integration_id = 'openai'")
            row = cur.fetchone()
            if row:
                cur.execute(
                    "UPDATE credential SET label = ?, value = ?, time_updated = ? WHERE integration_id = 'openai'",
                    (label, val_json, now_ms)
                )
            else:
                cred_id = get_openai_cred_id()
                cur.execute(
                    "INSERT INTO credential (id, integration_id, label, value, time_created, time_updated) VALUES (?, 'openai', ?, ?, ?, ?)",
                    (cred_id, label, val_json, now_ms, now_ms)
                )
        else:
            cur.execute("DELETE FROM credential WHERE integration_id = 'openai'")

        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[OpenAI Manager] SQLite sync warning: {e}")


def sync_opencode_cli_openai(account: dict | None):
    """Trigger opencode-cli auth import / logout to notify the running OpenCode service."""
    cli = find_opencode_cli()
    if not cli:
        return
    try:
        if account:
            cred_id = get_openai_cred_id()
            label = account.get("name") or account.get("email") or "ChatGPT OAuth"
            payload = [
                {
                    "id": cred_id,
                    "integrationID": "openai",
                    "label": label,
                    "active": True,
                    "value": {
                        "type": "oauth",
                        "methodID": "chatgpt-browser",
                        "refresh": account.get("refresh", ""),
                        "access": account.get("access", ""),
                        "expires": account.get("expires", 0),
                        "metadata": {
                            "accountID": account.get("accountId", ""),
                            "email": account.get("email", ""),
                        }
                    }
                }
            ]
            tmp_file = Path(tempfile.gettempdir()) / "opencode_openai_import.json"
            with open(tmp_file, "w", encoding="utf-8") as f:
                json.dump(payload, f)
            subprocess.run([cli, "auth", "import", str(tmp_file)], capture_output=True, timeout=10)
            try:
                tmp_file.unlink(missing_ok=True)
            except Exception:
                pass
        else:
            subprocess.run([cli, "auth", "logout", "openai"], capture_output=True, timeout=10)
    except Exception as e:
        print(f"[OpenAI Manager] CLI sync warning: {e}")


def decode_jwt_payload(jwt_token: str) -> dict:
    try:
        parts = jwt_token.split(".")
        if len(parts) >= 2:
            payload_b64 = parts[1]
            padding = "=" * ((4 - len(payload_b64) % 4) % 4)
            decoded = base64.urlsafe_b64decode(payload_b64 + padding).decode("utf-8")
            return json.loads(decoded)
    except Exception:
        pass
    return {}


def extract_claims_info(id_token: str, access_token: str) -> dict:
    id_claims = decode_jwt_payload(id_token) if id_token else {}
    access_claims = decode_jwt_payload(access_token) if access_token else {}

    auth_claim = access_claims.get("https://api.openai.com/auth") or id_claims.get("https://api.openai.com/auth") or {}
    profile_claim = access_claims.get("https://api.openai.com/profile") or id_claims.get("https://api.openai.com/profile") or {}

    email = (
        profile_claim.get("email")
        or id_claims.get("email")
        or access_claims.get("email")
        or "unknown@chatgpt.com"
    )
    name = profile_claim.get("name") or id_claims.get("name") or ""
    account_id = (
        auth_claim.get("chatgpt_account_id")
        or access_claims.get("chatgpt_account_id")
        or id_claims.get("chatgpt_account_id")
        or ""
    )
    plan_type = (
        auth_claim.get("chatgpt_plan_type")
        or access_claims.get("chatgpt_plan_type")
        or id_claims.get("chatgpt_plan_type")
        or "plus"
    )

    return {
        "email": email,
        "name": name,
        "accountId": account_id,
        "plan_type": plan_type,
    }


def get_active_auth_openai() -> dict | None:
    for auth_path in AUTH_FILES:
        if auth_path.exists():
            try:
                with open(auth_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    val = data.get("openai")
                    if val:
                        return val
            except Exception:
                pass
    return None


def write_active_auth_openai(account: dict | None) -> bool:
    try:
        for auth_path in AUTH_FILES:
            data = {}
            if auth_path.exists():
                try:
                    with open(auth_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                except Exception:
                    data = {}

            if account:
                data["openai"] = {
                    "type": "oauth",
                    "access": account.get("access", ""),
                    "refresh": account.get("refresh", ""),
                    "expires": account.get("expires", 0),
                    "accountId": account.get("accountId", ""),
                }
            else:
                data.pop("openai", None)

            auth_path.parent.mkdir(parents=True, exist_ok=True)
            with open(auth_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)

        # Sync into OpenCode 2.0 database & notify daemon
        sync_opencode_db_openai(account)
        sync_opencode_cli_openai(account)

        return True
    except Exception as e:
        print(f"[OpenAI Manager] Error updating auth: {e}")
        return False


def load_openai_accounts() -> list[dict]:
    accounts = []
    if OPENAI_ACCOUNTS_FILE.exists():
        try:
            with open(OPENAI_ACCOUNTS_FILE, "r", encoding="utf-8") as f:
                accounts = json.load(f)
        except Exception as e:
            print(f"[OpenAI Manager] Error reading openai-accounts.json: {e}")

    # If accounts file is empty or missing, check if auth.json has an openai account
    active_auth = get_active_auth_openai()
    if not accounts and active_auth and active_auth.get("access"):
        claims = extract_claims_info("", active_auth.get("access", ""))
        imported_acc = {
            "id": claims["accountId"] or "openai_default",
            "accountId": active_auth.get("accountId") or claims["accountId"],
            "email": claims["email"],
            "name": claims["name"],
            "plan_type": claims["plan_type"],
            "access": active_auth.get("access", ""),
            "refresh": active_auth.get("refresh", ""),
            "expires": active_auth.get("expires", 0),
            "added_at": int(time.time()),
            "last_used": int(time.time()),
            "is_active": True,
            "quota": None,
        }
        accounts.append(imported_acc)
        save_openai_accounts(accounts)

    # Sync is_active flag with auth.json
    active_account_id = active_auth.get("accountId") if active_auth else None
    for acc in accounts:
        if active_account_id and acc.get("accountId") == active_account_id:
            acc["is_active"] = True
        elif not active_account_id and accounts and acc == accounts[0]:
            acc["is_active"] = True
        else:
            acc["is_active"] = False

    return accounts


def save_openai_accounts(accounts: list[dict]) -> bool:
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        with open(OPENAI_ACCOUNTS_FILE, "w", encoding="utf-8") as f:
            json.dump(accounts, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        print(f"[OpenAI Manager] Error saving openai-accounts.json: {e}")
        return False


def set_active_openai_account(account_id: str) -> bool:
    accounts = load_openai_accounts()
    target_account = None
    for acc in accounts:
        if acc.get("id") == account_id or acc.get("accountId") == account_id:
            acc["is_active"] = True
            target_account = acc
        else:
            acc["is_active"] = False

    if target_account:
        save_openai_accounts(accounts)
        write_active_auth_openai(target_account)
        return True
    return False


def remove_openai_account(account_id: str) -> bool:
    accounts = load_openai_accounts()
    remaining = [
        acc for acc in accounts
        if acc.get("id") != account_id and acc.get("accountId") != account_id
    ]

    was_active = any(
        (acc.get("id") == account_id or acc.get("accountId") == account_id) and acc.get("is_active")
        for acc in accounts
    )

    if remaining and was_active:
        remaining[0]["is_active"] = True
        write_active_auth_openai(remaining[0])
    elif not remaining and was_active:
        write_active_auth_openai(None)

    save_openai_accounts(remaining)
    return True


def refresh_openai_token(account: dict) -> tuple[bool, dict]:
    refresh_token = account.get("refresh")
    if not refresh_token:
        return False, account

    form_data = urllib.parse.urlencode({
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": OPENAI_CLIENT_ID,
    }).encode("utf-8")

    req = urllib.request.Request(
        f"{OPENAI_ISSUER}/oauth/token",
        data=form_data,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "opencode/1.0.0",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            tokens = json.loads(resp.read().decode("utf-8"))
            access_token = tokens.get("access_token")
            new_refresh = tokens.get("refresh_token") or refresh_token
            expires_in = tokens.get("expires_in", 86400)

            account["access"] = access_token
            account["refresh"] = new_refresh
            account["expires"] = int(time.time() * 1000) + (expires_in * 1000)

            claims = extract_claims_info(tokens.get("id_token", ""), access_token)
            if claims.get("email"):
                account["email"] = claims["email"]
            if claims.get("plan_type"):
                account["plan_type"] = claims["plan_type"]

            if account.get("is_active"):
                write_active_auth_openai(account)

            return True, account
    except Exception as e:
        print(f"[OpenAI Manager] Token refresh failed for {account.get('email')}: {e}")
        return False, account


def fetch_openai_usage(account: dict) -> dict:
    # If token expires within 2 minutes, refresh it first
    now_ms = int(time.time() * 1000)
    if account.get("expires", 0) - now_ms < 120000:
        refresh_openai_token(account)

    access_token = account.get("access", "")
    account_id = account.get("accountId", "")

    req = urllib.request.Request(
        OPENAI_USAGE_URL,
        headers={
            "Authorization": f"Bearer {access_token}",
            "chatgpt-account-id": account_id,
            "User-Agent": "opencode/1.0.0",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=12) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
            return _parse_usage_payload(payload, account)
    except urllib.error.HTTPError as he:
        if he.code == 401:
            # Token might have been revoked/expired - retry once with refresh
            ok, updated_acc = refresh_openai_token(account)
            if ok:
                return fetch_openai_usage(updated_acc)
        print(f"[OpenAI Manager] HTTP error {he.code} fetching usage: {he}")
    except Exception as e:
        print(f"[OpenAI Manager] Error fetching usage for {account.get('email')}: {e}")

    # Return cached or default fallback
    return account.get("quota") or {
        "status": "error",
        "primary": {"used_percent": 0, "remaining_percent": 100, "reset_label": "Недоступно"},
        "secondary": {"used_percent": 0, "remaining_percent": 100, "reset_label": "Недоступно"},
    }


def _parse_usage_payload(payload: dict, account: dict) -> dict:
    if payload.get("email"):
        account["email"] = payload["email"]
    if payload.get("plan_type"):
        account["plan_type"] = payload["plan_type"]

    rate_limit = payload.get("rate_limit", {})
    primary = rate_limit.get("primary_window") or {}
    secondary = rate_limit.get("secondary_window") or {}

    def parse_window(win: dict) -> dict:
        used_pct = float(win.get("used_percent", 0.0))
        rem_pct = max(0.0, min(100.0, 100.0 - used_pct))
        reset_after = win.get("reset_after_seconds", 0)
        reset_at = win.get("reset_at", 0)

        reset_label = "сейчас"
        if reset_after > 0:
            hrs = reset_after // 3600
            mins = (reset_after % 3600) // 60
            if hrs > 24:
                days = hrs // 24
                hrs = hrs % 24
                reset_label = f"через {days}д {hrs}ч"
            elif hrs > 0:
                reset_label = f"через {hrs}ч {mins}м"
            else:
                reset_label = f"через {mins}м"

        return {
            "used_percent": round(used_pct, 1),
            "remaining_percent": round(rem_pct, 1),
            "reset_after_seconds": reset_after,
            "reset_at": reset_at,
            "reset_label": reset_label,
            "limit_window_seconds": win.get("limit_window_seconds", 0),
        }

    quota_data = {
        "status": "ok",
        "plan_type": payload.get("plan_type", account.get("plan_type", "plus")),
        "allowed": rate_limit.get("allowed", True),
        "limit_reached": rate_limit.get("limit_reached", False),
        "primary": parse_window(primary),
        "secondary": parse_window(secondary),
        "credits": payload.get("credits", {}),
        "last_checked": int(time.time()),
    }

    account["quota"] = quota_data
    return quota_data


def check_and_auto_rotate_openai(accounts: list[dict]) -> tuple[bool, str]:
    """
    Checks if active OpenAI account has exhausted its quota, and if so,
    seamlessly rotates to the next available account with quota,
    updating auth.json without requiring any restart of OpenCode.
    """
    if len(accounts) <= 1:
        return False, ""

    active_acc = next((a for a in accounts if a.get("is_active")), None)
    if not active_acc:
        return False, ""

    quota = active_acc.get("quota") or {}
    primary = quota.get("primary") or {}
    limit_reached = (
        quota.get("limit_reached", False)
        or primary.get("remaining_percent", 100) <= 0
        or primary.get("used_percent", 0) >= 100
    )

    if not limit_reached:
        return False, ""

    # Find candidates with remaining quota
    candidates = [
        a for a in accounts
        if (a.get("accountId") != active_acc.get("accountId") and a.get("id") != active_acc.get("id"))
        and (a.get("quota") or {}).get("primary", {}).get("remaining_percent", 100) > 0
    ]

    if not candidates:
        return False, "Все аккаунты OpenAI исчерпали доступную квоту."

    next_acc = candidates[0]
    set_active_openai_account(next_acc.get("accountId") or next_acc.get("id"))
    for a in accounts:
        a["is_active"] = (a.get("accountId") == next_acc.get("accountId"))

    return True, f"Лимит {active_acc.get('email')} исчерпан. Автоматически переключен на {next_acc.get('email')} на лету (без перезапуска)."


def refresh_all_openai_accounts() -> tuple[list[dict], str | None]:
    accounts = load_openai_accounts()
    for acc in accounts:
        try:
            acc["quota"] = fetch_openai_usage(acc)
            acc["last_used"] = int(time.time())
        except Exception as e:
            print(f"[OpenAI Manager] Failed refreshing quota for {acc.get('email')}: {e}")
    save_openai_accounts(accounts)

    rotated, msg = check_and_auto_rotate_openai(accounts)
    return accounts, (msg if rotated else None)


# --- OAuth Server Handler for Browser Login ---

class _OAuthCallbackHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        # Suppress standard logging to keep output clean
        pass

    def do_GET(self):
        url = urllib.parse.urlparse(self.path)
        if url.path != "/auth/callback":
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"Not Found")
            return

        params = urllib.parse.parse_qs(url.query)
        error = params.get("error_description", [None])[0] or params.get("error", [None])[0]
        code = params.get("code", [None])[0]
        state = params.get("state", [None])[0]

        server: _OAuthServer = self.server  # type: ignore

        if error:
            server.auth_error = error
            self._render_page(False, f"Ошибка авторизации: {error}")
            server.done_event.set()
            return

        if not code or state != server.expected_state:
            err_msg = "Неверное состояние OAuth или отсутствует код авторизации."
            server.auth_error = err_msg
            self._render_page(False, err_msg)
            server.done_event.set()
            return

        server.auth_code = code
        self._render_page(True, "Авторизация успешно завершена! Вы можете закрыть эту вкладку браузера.")
        server.done_event.set()

    def _render_page(self, success: bool, message: str):
        self.send_response(200 if success else 400)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()

        color = "#10b981" if success else "#ef4444"
        icon = "✓" if success else "✕"
        html = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>Antigravity Hub — OpenAI Auth</title>
  <style>
    body {{
      background-color: #121214;
      color: #f4f4f5;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      display: flex;
      align-items: center;
      justify-content: center;
      height: 100vh;
      margin: 0;
    }}
    .card {{
      background: #18181b;
      border: 1px solid #27272a;
      border-radius: 16px;
      padding: 36px 44px;
      text-align: center;
      max-width: 440px;
      box-shadow: 0 10px 30px rgba(0,0,0,0.5);
    }}
    .badge {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 64px;
      height: 64px;
      border-radius: 50%;
      background: {color}22;
      color: {color};
      font-size: 32px;
      margin-bottom: 20px;
    }}
    h2 {{ margin: 0 0 10px 0; font-size: 22px; }}
    p {{ color: #a1a1aa; font-size: 14px; line-height: 1.5; }}
  </style>
</head>
<body>
  <div class="card">
    <div class="badge">{icon}</div>
    <h2>{'Авторизация успешна' if success else 'Ошибка входа'}</h2>
    <p>{message}</p>
  </div>
</body>
</html>"""
        self.wfile.write(html.encode("utf-8"))


class _OAuthServer(HTTPServer):
    def __init__(self, server_address, expected_state: str):
        super().__init__(server_address, _OAuthCallbackHandler)
        self.expected_state = expected_state
        self.auth_code: str | None = None
        self.auth_error: str | None = None
        self.done_event = threading.Event()


def login_openai_browser(timeout: int = 300) -> tuple[bool, str, dict | None]:
    """
    Initiates browser-based OAuth PKCE login for ChatGPT/OpenAI,
    listens for callback on localhost:1455, exchanges tokens,
    fetches quota, and saves account.
    """
    code_verifier = secrets.token_urlsafe(32)
    digest = hashlib.sha256(code_verifier.encode("utf-8")).digest()
    code_challenge = base64.urlsafe_b64encode(digest).decode("utf-8").rstrip("=")
    state = secrets.token_urlsafe(24)

    redirect_uri = f"http://localhost:{OPENAI_CALLBACK_PORT}/auth/callback"

    try:
        server = _OAuthServer(("localhost", OPENAI_CALLBACK_PORT), state)
    except Exception as e:
        return False, f"Не удалось запустить локальный сервер на порту {OPENAI_CALLBACK_PORT}: {e}", None

    server_thread = threading.Thread(target=server.handle_request, daemon=True)
    server_thread.start()

    auth_url = (
        f"{OPENAI_ISSUER}/oauth/authorize?"
        + urllib.parse.urlencode({
            "response_type": "code",
            "client_id": OPENAI_CLIENT_ID,
            "redirect_uri": redirect_uri,
            "scope": "openid profile email offline_access",
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "id_token_add_organizations": "true",
            "codex_cli_simplified_flow": "true",
            "state": state,
            "originator": "opencode",
        })
    )

    try:
        webbrowser.open(auth_url)
    except Exception as e:
        server.server_close()
        return False, f"Не удалось открыть браузер: {e}", None

    # Wait for callback or timeout
    finished = server.done_event.wait(timeout=timeout)
    server.server_close()

    if not finished:
        return False, "Время ожидания авторизации в браузере истекло.", None

    if server.auth_error or not server.auth_code:
        return False, server.auth_error or "Авторизация была отменена.", None

    # Exchange code for tokens
    form_data = urllib.parse.urlencode({
        "grant_type": "authorization_code",
        "code": server.auth_code,
        "redirect_uri": redirect_uri,
        "client_id": OPENAI_CLIENT_ID,
        "code_verifier": code_verifier,
    }).encode("utf-8")

    token_req = urllib.request.Request(
        f"{OPENAI_ISSUER}/oauth/token",
        data=form_data,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "opencode/1.0.0",
        },
    )

    try:
        with urllib.request.urlopen(token_req, timeout=15) as resp:
            tokens = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        return False, f"Ошибка обмена кода на токены: {e}", None

    access_token = tokens.get("access_token", "")
    refresh_token = tokens.get("refresh_token", "")
    id_token = tokens.get("id_token", "")
    expires_in = tokens.get("expires_in", 86400)

    claims = extract_claims_info(id_token, access_token)
    account_id = claims["accountId"] or f"openai_{secrets.token_hex(6)}"

    new_account = {
        "id": account_id,
        "accountId": account_id,
        "email": claims["email"],
        "name": claims["name"],
        "plan_type": claims["plan_type"],
        "access": access_token,
        "refresh": refresh_token,
        "expires": int(time.time() * 1000) + (expires_in * 1000),
        "added_at": int(time.time()),
        "last_used": int(time.time()),
        "is_active": True,
        "quota": None,
    }

    # Fetch live usage immediately
    try:
        new_account["quota"] = fetch_openai_usage(new_account)
    except Exception as e:
        print(f"[OpenAI Manager] Usage fetch error after login: {e}")

    # Add to accounts pool
    accounts = load_openai_accounts()
    # Replace existing account with same accountId or email, or append
    existing_idx = next(
        (i for i, a in enumerate(accounts) if a.get("accountId") == account_id or a.get("email") == new_account["email"]),
        None
    )

    if existing_idx is not None:
        accounts[existing_idx] = new_account
    else:
        accounts.append(new_account)

    # Set as active in auth.json
    for a in accounts:
        a["is_active"] = (a["accountId"] == account_id)

    save_openai_accounts(accounts)
    write_active_auth_openai(new_account)

    return True, f"Аккаунт {new_account['email']} успешно подключен!", new_account
