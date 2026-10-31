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
import datetime
import webbrowser
import threading
import subprocess
import tempfile
import sqlite3
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler
import urllib.request
import urllib.parse
import uuid

OPENAI_CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
OPENAI_ISSUER = "https://auth.openai.com"
# OpenCode 2.2.x ChatGPT integration contract (token sharing):
# https://github.com/anomalyco/opencode — packages/core/src/plugin/provider/chatgpt.ts
OPENAI_AUTHORIZE_URL = f"{OPENAI_ISSUER}/api/accounts/authorize"
OPENAI_TOKEN_URL = f"{OPENAI_ISSUER}/api/accounts/oauth/token"
OPENAI_LEGACY_TOKEN_URL = f"{OPENAI_ISSUER}/oauth/token"
OPENAI_RESOURCE = "https://api.openai.com/v1"
REGISTRATION_CLIENT_ID = "dynamic_agent_client"
TOKEN_SHARING_SCOPE = "chatgpt.tokens.use.direct"
TOKEN_SHARING_METHOD = "chatgpt-token-sharing"
LEGACY_BROWSER_METHOD = "chatgpt-browser"
OPENAI_MODELS_URL = f"{OPENAI_RESOURCE}/models"
OPENAI_TASK_AGENT = "OpenCode"
OPENAI_CALLBACK_PORT = 1455
OPENAI_USAGE_URL = "https://chatgpt.com/backend-api/wham/usage"

CONFIG_DIR = Path(os.path.expanduser("~/.config/opencode"))
OPENAI_ACCOUNTS_FILE = CONFIG_DIR / "openai-accounts.json"
OPENAI_LOGIN_LOG_FILE = CONFIG_DIR / "hub-openai-login.log"


def log_openai_event(message: str) -> None:
    """Append timestamped login/refresh diagnostics; pythonw has no console."""
    try:
        OPENAI_LOGIN_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with OPENAI_LOGIN_LOG_FILE.open("a", encoding="utf-8") as fh:
            fh.write(f"[{stamp}] {message}\n")
    except Exception:
        pass


AUTH_FILES = [
    Path(os.path.expanduser("~/.local/share/opencode/auth.json")),
    Path(os.path.expanduser("~/.opencode/auth.json")),
]
OPENCODE_DB_FILE = Path(os.path.expanduser("~/.local/share/opencode/opencode.db"))


def find_opencode_cli() -> str | None:
    candidates = [
        Path(os.path.expanduser("~\\AppData\\Local\\Programs\\ai.opencode.desktop\\resources\\opencode-cli.exe")),
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


def _openai_method_for(account: dict) -> str:
    """Token-sharing accounts carry a client ID from the OpenAI OAuth flow."""
    return TOKEN_SHARING_METHOD if account.get("clientID") else LEGACY_BROWSER_METHOD


def _openai_credential_metadata(account: dict) -> dict:
    if account.get("clientID"):
        return {
            "clientID": account.get("clientID", ""),
            "scopes": list(account.get("scopes") or []),
            "accountID": account.get("accountId", ""),
            "email": account.get("email", ""),
        }
    return {
        "accountID": account.get("accountId", ""),
        "email": account.get("email", ""),
    }


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
                "methodID": _openai_method_for(account),
                "refresh": account.get("refresh", ""),
                "access": account.get("access", ""),
                "expires": account.get("expires", 0),
                "metadata": _openai_credential_metadata(account),
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
                        "methodID": _openai_method_for(account),
                        "refresh": account.get("refresh", ""),
                        "access": account.get("access", ""),
                        "expires": account.get("expires", 0),
                        "metadata": _openai_credential_metadata(account),
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


def generate_pkce() -> tuple[str, str]:
    """PKCE verifier/S256 challenge for the OpenAI token-sharing authorize flow."""
    verifier = secrets.token_urlsafe(43)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return verifier, challenge


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


def import_openai_accounts(imported_list: list[dict]) -> int:
    """
    Imports and merges a list of OpenAI accounts into the local store.
    Returns the count of successfully imported/merged accounts.
    """
    if not imported_list:
        return 0
    accounts = load_openai_accounts()
    count = 0
    for new_acc in imported_list:
        if not isinstance(new_acc, dict):
            continue
        acc_id = new_acc.get("accountId") or new_acc.get("id")
        email = new_acc.get("email")
        if not acc_id and not email:
            continue
        idx = next(
            (i for i, a in enumerate(accounts) if (acc_id and a.get("accountId") == acc_id) or (email and a.get("email") == email)),
            None
        )
        if idx is not None:
            accounts[idx].update(new_acc)
        else:
            accounts.append(new_acc)
        count += 1

    if accounts:
        if not any(a.get("is_active") for a in accounts):
            accounts[0]["is_active"] = True
        save_openai_accounts(accounts)
        active_acc = next((a for a in accounts if a.get("is_active")), accounts[0])
        write_active_auth_openai(active_acc)

    return count


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
    removed_was_active = next(
        (
            acc
            for acc in accounts
            if (acc.get("id") == account_id or acc.get("accountId") == account_id) and acc.get("is_active")
        ),
        None,
    )
    remaining = [
        acc for acc in accounts
        if acc.get("id") != account_id and acc.get("accountId") != account_id
    ]

    if removed_was_active is not None:
        # The active credential is being removed: point OpenCode at the next
        # remaining account (or clear auth entirely when the pool is empty).
        next_active = next((acc for acc in remaining if acc.get("is_active")), None) or (remaining[0] if remaining else None)
        for acc in remaining:
            acc["is_active"] = (acc is next_active)
        write_active_auth_openai(next_active)
    elif remaining and not any(acc.get("is_active") for acc in remaining):
        remaining[0]["is_active"] = True
        write_active_auth_openai(remaining[0])

    save_openai_accounts(remaining)
    return True


def _get_http_opener(timeout: int = 15):
    """Route OpenAI usage/auth requests according to the provider selector."""
    import provider_proxy
    proxy_url = provider_proxy.proxy_url_for_hub_requests()
    handler = urllib.request.ProxyHandler({"http": proxy_url, "https": proxy_url})
    return urllib.request.build_opener(handler)


OPENAI_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


def refresh_openai_token(account: dict) -> tuple[bool, dict]:
    refresh_token = account.get("refresh")
    if not refresh_token:
        return False, account

    client_id = account.get("clientID") or ""
    if client_id:
        token_url = OPENAI_TOKEN_URL
        form_data = urllib.parse.urlencode({
            "grant_type": "refresh_token",
            "client_id": client_id,
            "refresh_token": refresh_token,
            "resource": OPENAI_RESOURCE,
        }).encode("utf-8")
    else:
        # Legacy login (old Codex-CLI client): keep refreshing against the old issuer path.
        token_url = OPENAI_LEGACY_TOKEN_URL
        form_data = urllib.parse.urlencode({
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": OPENAI_CLIENT_ID,
        }).encode("utf-8")

    req = urllib.request.Request(
        token_url,
        data=form_data,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": OPENAI_BROWSER_UA,
        },
    )

    opener = _get_http_opener(timeout=15)

    try:
        with opener.open(req, timeout=15) as resp:
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
            if tokens.get("scope"):
                account["scopes"] = tokens["scope"].split()

            if account.get("is_active"):
                write_active_auth_openai(account)

            return True, account
    except Exception as e:
        print(f"[OpenAI Manager] Token refresh failed for {account.get('email')}: {e}")
        return False, account


def fetch_openai_usage(account: dict, _retried: bool = False) -> dict:
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
            "User-Agent": OPENAI_BROWSER_UA,
            "Accept": "application/json",
        },
    )

    opener = _get_http_opener(timeout=12)

    try:
        with opener.open(req, timeout=12) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
            return _parse_usage_payload(payload, account)
    except urllib.error.HTTPError as he:
        if he.code == 401 and not _retried:
            # Token might have been revoked/expired - retry once with refresh
            ok, updated_acc = refresh_openai_token(account)
            if ok:
                return fetch_openai_usage(updated_acc, _retried=True)
        print(f"[OpenAI Manager] HTTP error {he.code} fetching usage: {he}")
    except Exception as e:
        print(f"[OpenAI Manager] Error fetching usage for {account.get('email')}: {e}")

    # Return cached or default fallback
    cached = account.get("quota") or {}
    if cached.get("status") in ("ok", "stale"):
        return {**cached, "status": "stale"}
    return {"status": "error", "primary": {}, "secondary": {}}


def _parse_usage_payload(payload: dict, account: dict) -> dict:
    if payload.get("email"):
        account["email"] = payload["email"]
    if payload.get("plan_type"):
        account["plan_type"] = payload["plan_type"]

    rate_limit = payload.get("rate_limit", {})
    w1 = rate_limit.get("primary_window") or {}
    w2 = rate_limit.get("secondary_window") or {}

    # Identify 5h window (<= 86400s) and weekly window (> 86400s) dynamically
    w1_secs = w1.get("limit_window_seconds") or 0
    w2_secs = w2.get("limit_window_seconds") or 0
    if w1_secs > w2_secs and w2_secs > 0:
        win_5h = w2
        win_weekly = w1
    elif w1_secs > 0:
        win_5h = w1
        win_weekly = w2
    else:
        win_5h = w1
        win_weekly = w2

    def parse_window(win: dict) -> dict:
        if not win or win.get("used_percent") is None:
            return {}
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

    parsed_5h = parse_window(win_5h)
    parsed_weekly = parse_window(win_weekly)

    quota_data = {
        "status": "ok",
        "plan_type": payload.get("plan_type", account.get("plan_type", "plus")),
        "allowed": rate_limit.get("allowed", True),
        "limit_reached": rate_limit.get("limit_reached", False),
        "primary": parsed_5h,
        "secondary": parsed_weekly,
        "window_5h": parsed_5h,
        "window_weekly": parsed_weekly,
        "credits": payload.get("credits", {}),
        "last_checked": int(time.time()),
    }

    account["quota"] = quota_data
    return quota_data


def fetch_openai_models(account: dict, timeout: int = 15) -> list[dict]:
    """Fetch the models this account token can actually use.

    Mirrors OpenCode's ChatGPT plugin (`GET {resource}/models` with the bearer
    token): the token-sharing endpoint returns `{models: [...]}` where each item
    has slug/display_name/visibility/supported_in_api. The platform-style
    `{data: [...]}` shape is accepted as fallback. The result drives the Hub's
    OpenAI card display; OpenCode itself re-reads the list automatically from
    the same endpoint whenever the credential becomes active.
    """
    now_ms = int(time.time() * 1000)
    if account.get("expires", 0) - now_ms < 120000:
        refresh_openai_token(account)

    access_token = account.get("access", "")
    if not access_token:
        account["models"] = []
        return []

    req = urllib.request.Request(
        OPENAI_MODELS_URL,
        headers={
            "Authorization": f"Bearer {access_token}",
            "User-Agent": OPENAI_BROWSER_UA,
            "Accept": "application/json",
        },
    )

    try:
        with _get_http_opener(timeout=timeout).open(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        print(f"[OpenAI Manager] Error fetching models for {account.get('email')}: {e}")
        models = account.get("models")
        return models if isinstance(models, list) else []

    if isinstance(payload, dict):
        items = payload.get("models")
        if items is None:
            items = payload.get("data")
        if items is None:
            items = []
    elif isinstance(payload, list):
        items = payload
    else:
        items = []

    models = []
    for item in items:
        if not isinstance(item, dict):
            continue
        slug = item.get("slug") or item.get("id")
        if not isinstance(slug, str) or not slug.strip():
            continue
        if item.get("visibility") == "hidden":
            continue
        if item.get("supported_in_api") is False:
            continue
        models.append({
            "id": slug.strip(),
            "name": item.get("display_name") or slug.strip(),
            "context": item.get("context_window") or 0,
        })

    models.sort(key=lambda m: m["id"].lower())
    account["models"] = models
    return models


def check_and_auto_rotate_openai(accounts: list[dict]) -> tuple[bool, str]:
    """
    Checks if active OpenAI account has exhausted its quota (5h or weekly), and if so,
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
    secondary = quota.get("secondary") or {}
    limit_reached = (
        quota.get("limit_reached", False)
        or primary.get("remaining_percent", 100) <= 0
        or primary.get("used_percent", 0) >= 100
        or secondary.get("remaining_percent", 100) <= 0
        or secondary.get("used_percent", 0) >= 100
    )

    if not limit_reached:
        return False, ""

    # Find candidates with remaining quota in both windows
    candidates = [
        a for a in accounts
        if (a.get("accountId") != active_acc.get("accountId") and a.get("id") != active_acc.get("id"))
        and (a.get("quota") or {}).get("primary", {}).get("remaining_percent", 100) > 0
        and (a.get("quota") or {}).get("secondary", {}).get("remaining_percent", 100) > 0
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
        client_id = params.get("client_id", [None])[0]

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

        if not client_id:
            # OpenAI returns the issued (per-user) client id on the callback in
            # the token-sharing flow; without it OpenCode cannot refresh the
            # credential.
            err_msg = "OpenAI не вернул client_id в callback — повторите вход."
            server.auth_error = err_msg
            self._render_page(False, err_msg)
            server.done_event.set()
            return

        server.auth_code = code
        server.auth_client_id = client_id
        self._render_page(True, "Авторизация успешно завершена! Модели аккаунта будут загружены автоматически.")
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
        self.auth_client_id: str | None = None
        self.auth_error: str | None = None
        self.done_event = threading.Event()


def login_openai_browser(timeout: int = 300) -> tuple[bool, str, dict | None]:
    """
    Initiates browser-based OAuth PKCE login for ChatGPT (OpenCode token-sharing
    flow), listens for callback on a free loopback port, exchanges tokens,
    verifies the token-sharing scope, fetches available models + quota, and
    saves the account.
    """
    code_verifier, code_challenge = generate_pkce()
    state = secrets.token_hex(16)
    nonce = secrets.token_hex(16)
    host_id = f"urn:uuid:{uuid.uuid4()}"

    try:
        import provider_proxy
        log_openai_event(f"login: start, hub proxy = {provider_proxy.proxy_url_for_hub_requests()}")
    except Exception as proxy_err:
        log_openai_event(f"login: start, hub proxy unknown ({proxy_err})")

    try:
        server = _OAuthServer(("127.0.0.1", 0), state)
        port = server.server_address[1]
    except Exception as e:
        return False, f"Не удалось открыть локальный callback-порт: {e}", None

    redirect_uri = f"http://127.0.0.1:{port}/auth/callback"

    server_thread = threading.Thread(target=server.handle_request, daemon=True)
    server_thread.start()

    auth_url = (
        f"{OPENAI_AUTHORIZE_URL}?"
        + urllib.parse.urlencode({
            "client_id": REGISTRATION_CLIENT_ID,
            "agent_name_hint": OPENAI_TASK_AGENT,
            "ext_agent_host_id": host_id,
            "response_type": "code",
            "redirect_uri": redirect_uri,
            "scope": f"openid profile email offline_access resource.invoke {TOKEN_SHARING_SCOPE}",
            "resource": OPENAI_RESOURCE,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "state": state,
            "nonce": nonce,
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
        log_openai_event("login: timeout waiting for callback")
        return False, "Время ожидания авторизации в браузере истекло.", None

    if server.auth_error or not server.auth_code:
        log_openai_event(f"login: callback error={server.auth_error!r}")
        return False, server.auth_error or "Авторизация была отменена.", None

    client_id = server.auth_client_id or ""
    log_openai_event(f"login: callback received, client_id={'yes' if client_id else 'NO'}")

    # Exchange code for tokens (token endpoint issues a per-user client on first login)
    form_data = urllib.parse.urlencode({
        "grant_type": "authorization_code",
        "code": server.auth_code,
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "resource": OPENAI_RESOURCE,
        "code_verifier": code_verifier,
    }).encode("utf-8")

    token_req = urllib.request.Request(
        OPENAI_TOKEN_URL,
        data=form_data,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": OPENAI_BROWSER_UA,
        },
    )

    opener = _get_http_opener(timeout=15)

    try:
        with opener.open(token_req, timeout=15) as resp:
            tokens = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        log_openai_event(f"login: token exchange failed: {e}")
        return False, f"Ошибка обмена кода на токены: {e}", None

    if tokens.get("error"):
        log_openai_event(f"login: token endpoint returned error={tokens.get('error')} desc={tokens.get('error_description')}")
        return False, f"OpenAI вернул ошибку обмена токена: {tokens.get('error_description') or tokens.get('error')}", None

    granted_scopes = (tokens.get("scope") or "").split()
    if TOKEN_SHARING_SCOPE not in granted_scopes:
        log_openai_event(f"login: token sharing scope missing, granted={granted_scopes}")
        return False, (
            "OpenAI не выдал скоуп token sharing (chatgpt.tokens.use.direct). "
            "Войдите заново и разрешите токен-шеринг, либо используйте платформенный API-ключ."
        ), None

    access_token = tokens.get("access_token", "")
    refresh_token = tokens.get("refresh_token", "")
    id_token = tokens.get("id_token", "")

    # Best-effort ID token validation (issuer/audience/nonce), matching OpenCode's plugin.
    id_claims = decode_jwt_payload(id_token)
    if id_claims.get("iss") not in (OPENAI_ISSUER, f"{OPENAI_ISSUER}/"):
        log_openai_event(f"login: bad id_token iss={id_claims.get('iss')}")
        return False, "ChatGPT вернул недействительный ID token: неизвестный issuer.", None
    aud_claims = id_claims.get("aud")
    if client_id not in (aud_claims if isinstance(aud_claims, list) else [aud_claims]):
        log_openai_event(f"login: id_token aud mismatch aud={aud_claims} expected={client_id}")
        return False, "ChatGPT вернул ID token с другой аудиторией, чем ожидается. Повторите вход.", None
    if id_claims.get("nonce") != nonce:
        log_openai_event(f"login: id_token nonce mismatch")
        return False, "ChatGPT вернул ID token с другим nonce. Повторите вход.", None
    if not str(id_claims.get("sub", "")).strip():
        log_openai_event("login: id_token has no subject")
        return False, "ChatGPT sign-in вернул ID token без subject.", None

    log_openai_event(f"login: tokens verified, email={id_claims.get('email')}, scopes={granted_scopes}")

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
        "clientID": client_id,
        "scopes": granted_scopes,
        "methodID": TOKEN_SHARING_METHOD,
        "added_at": int(time.time()),
        "last_used": int(time.time()),
        "is_active": True,
        "quota": None,
        "models": None,
    }

    # Read the models this account can actually use right away
    try:
        fetch_openai_models(new_account)
        log_openai_event(f"login: models loaded for {new_account['email']}: {len(new_account.get('models') or [])}")
    except Exception as e:
        log_openai_event(f"login: models fetch error for {new_account.get('email')}: {e}")
        print(f"[OpenAI Manager] Models fetch error after login: {e}")

    # Fetch live usage immediately (best effort)
    try:
        new_account["quota"] = fetch_openai_usage(new_account)
    except Exception as e:
        log_openai_event(f"login: usage fetch error for {new_account.get('email')}: {e}")
        print(f"[OpenAI Manager] Usage fetch error after login: {e}")

    # Add to accounts pool
    accounts = load_openai_accounts()
    # Replace existing account with same accountId or email, or append
    existing_idx = next(
        (i for i, a in enumerate(accounts) if a.get("accountId") == account_id or a.get("email") == new_account["email"]),
        None
    )

    model_note = f", доступно моделей: {len(new_account.get('models') or [])}" if new_account.get("models") else ""
    if existing_idx is not None:
        accounts[existing_idx] = new_account
    else:
        accounts.append(new_account)

    # Set as active in auth.json
    for a in accounts:
        a["is_active"] = (a["accountId"] == account_id)

    save_openai_accounts(accounts)
    write_active_auth_openai(new_account)
    log_openai_event(f"login: success, account {new_account['email']} saved to pool (is_active)")

    return True, f"Аккаунт {new_account['email']} успешно подключен{model_note}!", new_account
