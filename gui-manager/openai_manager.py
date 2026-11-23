"""
OpenAI / ChatGPT Account and Quota Manager for AI HUB
"""

import os
import sys
import json
import math
import time
import base64
import secrets
import hashlib
import webbrowser
import threading
import subprocess
import sqlite3
from pathlib import Path
from http.server import HTTPServer
import urllib.request
import urllib.parse
from contextlib import closing
from html import escape

import secure_storage
import opencode_credentials
from provider_proxy import _BoundedHandler

OPENAI_CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
OPENAI_ISSUER = "https://auth.openai.com"
OPENAI_CALLBACK_PORT = 1455
OPENAI_USAGE_URL = "https://chatgpt.com/backend-api/wham/usage"

CONFIG_DIR = Path(os.path.expanduser("~/.config/opencode"))
try:
    import hub_paths
    CONFIG_DIR = hub_paths.OPENCODE_CONFIG_DIR
    OPENAI_ACCOUNTS_FILE = hub_paths.OPENAI_ACCOUNTS_FILE
except Exception:
    OPENAI_ACCOUNTS_FILE = CONFIG_DIR / "openai-accounts.json"
AUTH_FILES = [
    Path(os.path.expanduser("~/.local/share/opencode/auth.json")),
    Path(os.path.expanduser("~/.opencode/auth.json")),
]
# Optional explicit override, also used by callers with isolated stores.
OPENCODE_DB_FILE: Path | None = None
_accounts_lock = threading.RLock()


def _opencode_database_path() -> Path | None:
    if OPENCODE_DB_FILE is not None:
        path = Path(OPENCODE_DB_FILE)
        return path if path.exists() else None
    return opencode_credentials.database_path()


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


OPENCODE_CREDENTIAL_PREFIX = "cred_openai_hub_"
LEGACY_HUB_CREDENTIAL_ID = "cred_openai_active"


def _is_hub_managed_credential_id(credential_id: object) -> bool:
    value = str(credential_id or "")
    return value.startswith(OPENCODE_CREDENTIAL_PREFIX) or value == LEGACY_HUB_CREDENTIAL_ID


def _openai_account_identity(account: dict) -> str:
    """Return a stable, non-secret identity used to map one Hub account to one credential."""
    for field in ("accountId", "id", "email"):
        value = str(account.get(field) or "").strip()
        if value:
            return value.casefold()
    return ""


def get_openai_cred_id(account: dict | None = None) -> str:
    """Return the stable OpenCode credential ID for a Hub account.

    Older Hub versions used one generic credential for every ChatGPT account.  A
    per-account ID is required because OpenCode identifies a credential connection
    by ID and publishes ``credential.switched`` when that connection is activated.
    """
    if isinstance(account, dict):
        identity = _openai_account_identity(account)
        if not identity:
            return LEGACY_HUB_CREDENTIAL_ID
        digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]
        return f"{OPENCODE_CREDENTIAL_PREFIX}{digest}"

    rows = _read_opencode_credential_rows() or []
    # Rows are ordered exactly like OpenCode's currentActive() selection:
    # active DESC, time_created DESC, id DESC.  The first row is the effective
    # credential even if active is null/false in a legacy migrated database.
    selected = rows[0] if rows else None
    if selected and selected.get("id"):
        return str(selected["id"])
    return LEGACY_HUB_CREDENTIAL_ID


def _read_opencode_credential_rows(
    integration_id: str | None = "openai",
) -> list[dict] | None:
    """Read OpenCode credentials without mutating the canonical database.

    Returns ``None`` when an existing database cannot be read.  Callers must not
    confuse that with a legitimately empty credential store.  Pass
    ``integration_id=None`` to inspect every integration for ID collisions.
    """
    db = _opencode_database_path()
    if db is None:
        return []
    try:
        with closing(sqlite3.connect(
            f"{db.resolve().as_uri()}?mode=ro", uri=True, timeout=2
        )) as conn:
            table = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='credential'"
            ).fetchone()
            if not table:
                # The DB file exists but has no v2 credential schema.  This is
                # unsupported state, not an empty credential store.
                return None
            columns = {row[1] for row in conn.execute("PRAGMA table_info(credential)")}
            # Older OpenCode databases have no credential ID column.  They can
            # still seed the Hub pool, but cannot participate in an ID-based
            # hot switch until OpenCode migrates the database.
            if not {"integration_id", "value"}.issubset(columns):
                return None
            selected = [
                column for column in
                ("id", "integration_id", "value", "label", "active", "time_created", "time_updated")
                if column in columns
            ]
            where = " WHERE integration_id = ?" if integration_id is not None else ""
            params = (integration_id,) if integration_id is not None else ()
            order_parts = [
                column + " DESC" for column in ("active", "time_created", "id")
                if column in columns
            ]
            order = f" ORDER BY {', '.join(order_parts)}" if order_parts else ""
            rows = conn.execute(
                f"SELECT {', '.join(selected)} FROM credential{where}{order}", params
            ).fetchall()
    except (OSError, sqlite3.Error, ValueError):
        return None

    result: list[dict] = []
    for row in rows:
        item = dict(zip(selected, row))
        item.setdefault("id", "")
        try:
            item["value"] = json.loads(item.get("value") or "{}")
        except (TypeError, ValueError):
            # A malformed canonical credential row must not cause a fallback to
            # a stale legacy auth.json token.
            return None
        result.append(item)
    return result


def _openai_credential_value(account: dict) -> dict:
    metadata: dict[str, str] = {}
    account_id = str(account.get("accountId") or "").strip()
    email = str(account.get("email") or "").strip()
    if account_id:
        metadata["accountID"] = account_id
    if email:
        metadata["email"] = email
    return {
        "type": "oauth",
        "methodID": "chatgpt-browser",
        "refresh": str(account.get("refresh") or ""),
        "access": str(account.get("access") or ""),
        "expires": int(account.get("expires") or 0),
        "metadata": metadata,
    }


def _openai_credential_label(account: dict) -> str:
    return str(account.get("name") or account.get("email") or "ChatGPT OAuth")


def _openai_credential_matches_account(row: dict | None, account: dict) -> bool:
    if not row or row.get("integration_id") != "openai":
        return False
    value = row.get("value") or {}
    if value.get("type") != "oauth":
        return False
    metadata = value.get("metadata") or {}
    stored_account_id = str(metadata.get("accountID") or metadata.get("accountId") or "")
    wanted_account_id = str(account.get("accountId") or "").strip()
    if wanted_account_id:
        if not stored_account_id or stored_account_id != wanted_account_id:
            return False
    else:
        stored_email = str(metadata.get("email") or "")
        wanted_email = str(account.get("email") or "").strip()
        if wanted_email and stored_email.casefold() != wanted_email.casefold():
            return False
    return True


def _openai_credential_has_current_tokens(row: dict | None, wanted: dict) -> bool:
    if not row:
        return False
    value = row.get("value") or {}
    if value.get("access") == wanted.get("access") and value.get("refresh") == wanted.get("refresh"):
        return True
    # OpenCode may refresh the credential concurrently.  A strictly newer
    # expiry means its token supersedes the value that Hub requested.
    try:
        return int(value.get("expires") or 0) > int(wanted.get("expires") or 0)
    except (TypeError, ValueError):
        return False


def sync_opencode_db_openai(account: dict | None) -> bool:
    """Verify the canonical OpenCode database after an official CLI operation.

    This function intentionally performs no direct SQLite mutation.  OpenCode
    must own credential writes so it can publish ``credential.updated`` and
    ``credential.switched`` to an already-running server.
    """
    rows = _read_opencode_credential_rows()
    if rows is None:
        return False
    if account is None:
        return not any(_is_hub_managed_credential_id(row.get("id")) for row in rows)
    if sum(1 for row in rows if row.get("active")) != 1:
        # OpenCode maintains exactly one active credential per integration.
        return False
    credential_id = get_openai_cred_id(account)
    row = next((item for item in rows if item.get("id") == credential_id), None)
    wanted = _openai_credential_value(account)
    return bool(
        row
        and row.get("active")
        and _openai_credential_matches_account(row, account)
        and _openai_credential_has_current_tokens(row, wanted)
    )


def _openai_import_payload(account: dict, credential_id: str) -> str:
    return json.dumps([
        {
            "id": credential_id,
            "integrationID": "openai",
            "label": _openai_credential_label(account),
            "active": True,
            "value": _openai_credential_value(account),
        }
    ], ensure_ascii=False)


def _run_opencode_cli(cli: str, args: list[str], input_text: str | None = None) -> None:
    kwargs = {
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "text": True,
        "encoding": "utf-8",
        "timeout": 30,
        "check": True,
    }
    if input_text is not None:
        kwargs["input"] = input_text
    subprocess.run([cli, *args], **kwargs)


def _restore_opencode_credential(cli: str, row: dict, was_active: bool) -> None:
    """Best-effort restoration of a credential removed before a failed import."""
    credential_id = str(row.get("id") or "")
    if not credential_id:
        return
    try:
        current = next(
            (item for item in (_read_opencode_credential_rows() or []) if item.get("id") == credential_id),
            None,
        )
        if current:
            _run_opencode_cli(cli, ["auth", "logout", "openai", credential_id])
        payload = [{
            "id": credential_id,
            "integrationID": "openai",
            "label": str(row.get("label") or "ChatGPT OAuth"),
            "active": bool(was_active),
            "value": row.get("value") or {},
        }]
        _run_opencode_cli(cli, ["auth", "import"], json.dumps(payload, ensure_ascii=False))
        if was_active:
            _run_opencode_cli(cli, ["auth", "switch", "openai", credential_id])
    except Exception:
        # Never include credential values or labels in diagnostics.
        print("[OpenAI Manager] Credential rollback failed")


def sync_opencode_cli_openai(account: dict | None) -> bool:
    """Create/replace and activate one ChatGPT credential through OpenCode's API.

    ``auth import`` alone is not a switch: OpenCode 2.3.2 skips an existing ID
    and only activates newly imported credentials.  The target is therefore
    imported through stdin and then explicitly activated with ``auth switch``,
    which publishes ``Credential.Event.Switched`` to the running server.
    """
    cli = find_opencode_cli()
    db_exists = _opencode_database_path() is not None
    if not cli:
        # A database-backed OpenCode installation needs its CLI for the switch
        # event.  Legacy installations are migrated through auth.json instead.
        return not db_exists

    try:
        if account is None:
            rows = _read_opencode_credential_rows()
            if rows is None:
                return False
            managed = [
                str(row.get("id")) for row in rows
                if _is_hub_managed_credential_id(row.get("id"))
            ]
            for credential_id in managed:
                _run_opencode_cli(cli, ["auth", "logout", "openai", credential_id])
            return sync_opencode_db_openai(None)

        credential_id = get_openai_cred_id(account)
        wanted = _openai_credential_value(account)
        if not db_exists:
            # Legacy OpenCode has no canonical DB to verify.  Keep the historical
            # stdin-only import path; the caller also updates auth.json.
            _run_opencode_cli(cli, ["auth", "import"], _openai_import_payload(account, credential_id))
            return True

        rows = _read_opencode_credential_rows()
        all_rows = _read_opencode_credential_rows(None)
        if rows is None or all_rows is None:
            return False
        existing = next((row for row in rows if row.get("id") == credential_id), None)
        previous_active = next((row for row in rows if row.get("active")), None)

        # OpenCode activates and removes credentials by primary key across all
        # integrations.  Never let a Hub-generated ID collide with another
        # integration's credential.
        if any(
            row.get("id") == credential_id and row.get("integration_id") != "openai"
            for row in all_rows
        ):
            print("[OpenAI Manager] Credential ID collision with another OpenCode integration")
            return False
        if existing and not _openai_credential_matches_account(existing, account):
            # The deterministic ID must never be used to take over a credential
            # that belongs to a different ChatGPT account.
            print("[OpenAI Manager] Credential ID belongs to a different ChatGPT account")
            return False

        replaced = False
        if existing and not _openai_credential_has_current_tokens(existing, wanted):
            # OpenCode 2.3.2 exposes no public endpoint for replacing a
            # credential value.  Remove and re-import this one ID through the
            # official API, then activate it.  Other accounts are untouched.
            _run_opencode_cli(cli, ["auth", "logout", "openai", credential_id])
            replaced = True

        try:
            if not existing or replaced:
                _run_opencode_cli(cli, ["auth", "import"], _openai_import_payload(account, credential_id))
            _run_opencode_cli(cli, ["auth", "switch", "openai", credential_id])
        except Exception:
            if replaced and existing:
                _restore_opencode_credential(cli, existing, bool(existing.get("active")))
            elif not existing:
                try:
                    _run_opencode_cli(cli, ["auth", "logout", "openai", credential_id])
                except Exception:
                    pass
            if previous_active and previous_active.get("id") != credential_id:
                try:
                    _run_opencode_cli(cli, ["auth", "switch", "openai", str(previous_active["id"])])
                except Exception:
                    pass
            raise

        if not sync_opencode_db_openai(account):
            if replaced and existing:
                _restore_opencode_credential(cli, existing, bool(existing.get("active")))
            elif not existing:
                try:
                    _run_opencode_cli(cli, ["auth", "logout", "openai", credential_id])
                except Exception:
                    pass
            if previous_active and previous_active.get("id") != credential_id:
                try:
                    _run_opencode_cli(cli, ["auth", "switch", "openai", str(previous_active["id"])])
                except Exception:
                    pass
            return False

        # Remove a legacy duplicate for the same ChatGPT account, but never
        # touch credentials belonging to another account.
        for row in (_read_opencode_credential_rows() or []):
            other_id = str(row.get("id") or "")
            if other_id == credential_id or not other_id:
                continue
            if _openai_credential_matches_account(row, account):
                try:
                    _run_opencode_cli(cli, ["auth", "logout", "openai", other_id])
                except Exception:
                    pass
        return True
    except Exception as exc:
        # Never print subprocess output or credential data: both may contain a token.
        print(f"[OpenAI Manager] CLI sync failed ({type(exc).__name__})")
        return False


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
    # OpenCode v2 migrates auth.json once and then treats opencode.db as the
    # canonical credential store.  Reading the legacy file first can resurrect
    # a stale token and pair it with the wrong chatgpt-account-id.
    db_exists = _opencode_database_path() is not None
    rows = _read_opencode_credential_rows()
    if rows is None:
        # A canonical store that cannot be read must not be shadowed by a stale
        # legacy auth.json token.
        return None
    if db_exists:
        if not rows:
            # A valid, empty v2 DB is canonical.  It is not permission to
            # resurrect a token from a one-time migration file.
            return None
        # OpenCode orders rows active DESC, time_created DESC, id DESC and
        # selects the first one, even when active is null/false.
        effective = rows[0]
        value = effective.get("value") or {}
        if value.get("type") == "oauth" and value.get("access"):
            metadata = value.get("metadata") or {}
            return {
                **value,
                "accountId": metadata.get("accountID") or metadata.get("accountId"),
                "email": metadata.get("email"),
                "credentialId": effective.get("id"),
            }
        return None

    # Legacy fallback is used only when no canonical OpenCode DB exists.
    for auth_path in AUTH_FILES:
        if auth_path.exists():
            try:
                with open(auth_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    val = data.get("openai")
                    if isinstance(val, dict) and val.get("access"):
                        return val
            except Exception:
                pass
    return None


def _write_legacy_auth_openai(account: dict | None) -> bool:
    """Update legacy auth.json stores only when no canonical OpenCode DB exists."""
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

        secure_storage.atomic_write(
            auth_path,
            json.dumps(data, indent=2, ensure_ascii=False),
        )
    return True


def write_active_auth_openai(account: dict | None) -> bool:
    """Synchronize the selected Hub account and acknowledge the active credential."""
    with _accounts_lock:
        try:
            db_exists = _opencode_database_path() is not None
            if not sync_opencode_cli_openai(account):
                return False
            # Keep plaintext compatibility files only for legacy OpenCode.  Once
            # the v2 DB exists it is canonical and must not be shadowed by a
            # stale auth.json copy.
            if not db_exists or account is None:
                return _write_legacy_auth_openai(account)
            return True
        except Exception as exc:
            print(f"[OpenAI Manager] Error updating auth ({type(exc).__name__})")
            return False


def _read_openai_account_file(path):
    raw = json.loads(path.read_text(encoding="utf-8-sig"))
    protected = isinstance(raw, dict) and ("protection" in raw or "payload" in raw)
    accounts = secure_storage.unprotect_payload(raw, "openai-accounts").get("accounts") if protected else raw
    if not isinstance(accounts, list) or any(not isinstance(a, dict) for a in accounts):
        raise ValueError("Invalid OpenAI account store")
    return accounts, protected


def load_openai_accounts(*, strict: bool = False) -> list[dict]:
    """Strict reads raise on a damaged Hub account store and never write it."""
    with _accounts_lock:
        accounts = []
        try:
            accounts, protected = _read_openai_account_file(OPENAI_ACCOUNTS_FILE)
            if not strict and not protected:
                save_openai_accounts(accounts)
        except FileNotFoundError:
            pass
        except Exception as e:
            if strict:
                raise OSError("Не удалось прочитать хранилище аккаунтов OpenAI; импорт не начат.") from None
            print(f"[OpenAI Manager] Error reading account store ({type(e).__name__})")
            return []

        # Seed an empty Hub pool from the active OpenCode credential.
        active_auth = get_active_auth_openai()
        if not accounts and active_auth and active_auth.get("access"):
            claims = extract_claims_info("", active_auth.get("access", ""))
            imported_acc = {
                "id": active_auth.get("accountId") or claims["accountId"] or "openai_default",
                "accountId": active_auth.get("accountId") or claims["accountId"],
                "email": active_auth.get("email") or claims["email"],
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
            if not strict:
                save_openai_accounts(accounts)

        # Sync is_active with the active OpenCode credential.
        active = None
        if active_auth:
            credential_id = active_auth.get("credentialId")
            if credential_id and _is_hub_managed_credential_id(credential_id):
                active = next((a for a in accounts if get_openai_cred_id(a) == credential_id), None)
            if active is None:
                for field in ("accountId", "email"):
                    value = str(active_auth.get(field) or "").casefold()
                    matches = [a for a in accounts if value and str(a.get(field) or "").casefold() == value]
                    if len(matches) == 1:
                        active = matches[0]
                        break
        if active is None and (not active_auth or not active_auth.get("accountId")):
            active = next((a for a in accounts if a.get("is_active")), accounts[0] if accounts else None)
        for acc in accounts:
            acc["is_active"] = acc is active

        return accounts


def save_openai_accounts(accounts: list[dict]) -> bool:
    with _accounts_lock:
        try:
            if OPENAI_ACCOUNTS_FILE.exists():
                _read_openai_account_file(OPENAI_ACCOUNTS_FILE)
            record = secure_storage.protect_payload("openai-accounts", {"accounts": accounts})
            secure_storage.atomic_write(
                OPENAI_ACCOUNTS_FILE,
                json.dumps(record, indent=2, ensure_ascii=False),
            )
            return True
        except Exception as e:
            print(f"[OpenAI Manager] Error saving account store ({type(e).__name__})")
            return False


def _find_openai_account(accounts: list[dict], identifier: str) -> dict | None:
    """Find exactly one Hub account without conflating its id and accountId fields."""
    wanted = str(identifier or "").strip()
    if not wanted:
        return None
    for field in ("id", "accountId", "email"):
        if field == "email":
            matches = [
                account for account in accounts
                if str(account.get(field) or "").casefold() == wanted.casefold()
            ]
        else:
            matches = [account for account in accounts if account.get(field) == wanted]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            return None
    return None


def import_openai_accounts(imported_list: list[dict], *, strict: bool = False) -> int:
    """
    Imports and merges a list of OpenAI accounts into the local store.
    Proactively refreshes access tokens and writes active auth to OpenCode.
    Returns the count of successfully imported/merged accounts. Strict mode
    rejects invalid input before writing and raises on failed or partial writes.
    """
    if not imported_list:
        return 0

    def fail(message):
        if strict:
            raise OSError(message)
        return 0

    with _accounts_lock:
        # Even compatibility callers must not treat an unreadable store as empty.
        try:
            accounts = load_openai_accounts(strict=True)
        except OSError:
            if strict:
                raise
            return 0
        previous_active = next((acc for acc in accounts if acc.get("is_active")), None)
        previous_auth = dict(previous_active) if previous_active else None
        original_flags = {id(acc): bool(acc.get("is_active")) for acc in accounts}
        desired_active = previous_active
        count = 0
        for new_acc in imported_list:
            if not isinstance(new_acc, dict) or not _openai_account_identity(new_acc):
                if strict:
                    raise ValueError("В импорте OpenAI найден аккаунт без идентификатора.")
                continue
            account_id = new_acc.get("accountId")
            local_id = new_acc.get("id")
            email = new_acc.get("email")
            idx = next(
                (i for i, a in enumerate(accounts)
                 if (account_id and a.get("accountId") == account_id)
                 or (local_id and a.get("id") == local_id)
                 or (email and a.get("email") == email
                     and not (account_id and a.get("accountId") and a["accountId"] != account_id))),
                None
            )
            if idx is not None:
                for k, v in new_acc.items():
                    if v is not None:
                        accounts[idx][k] = v
                merged = accounts[idx]
            else:
                merged = dict(new_acc)
                accounts.append(merged)
            if new_acc.get("is_active") is True:
                desired_active = merged
            count += 1

        if not count:
            return 0

        active_acc = desired_active if any(acc is desired_active for acc in accounts) else accounts[0]

        # Proactively refresh tokens for accounts where token is missing, expired,
        # or near expiry.  Suppress the active-account side effect until the
        # final OpenCode activation has been acknowledged.
        now_ms = int(time.time() * 1000)
        for acc in accounts:
            expires = acc.get("expires", 0)
            if not acc.get("access") or (expires - now_ms < 300000):
                was_active = acc.get("is_active")
                acc["is_active"] = False
                try:
                    refresh_openai_token(acc)
                except Exception as err:
                    print(f"[OpenAI Manager] Refresh on import failed ({type(err).__name__})")
                finally:
                    acc["is_active"] = was_active

        # Persist imported tokens first, but do not publish a new active flag
        # before OpenCode confirms the corresponding credential switch.
        for acc in accounts:
            acc["is_active"] = False
        if not save_openai_accounts(accounts):
            for acc in accounts:
                acc["is_active"] = original_flags.get(id(acc), False)
            return fail("Не удалось сохранить импортируемые аккаунты OpenAI.")

        if not write_active_auth_openai(active_acc):
            for acc in accounts:
                acc["is_active"] = original_flags.get(id(acc), False)
            restored = save_openai_accounts(accounts)
            return fail("Аккаунты OpenAI сохранены, но не удалось активировать аккаунт в OpenCode."
                        + ("" if restored else " Не удалось восстановить прежнее локальное состояние."))

        for acc in accounts:
            acc["is_active"] = acc is active_acc
        if not save_openai_accounts(accounts):
            restored_auth = write_active_auth_openai(previous_auth)
            for acc in accounts:
                acc["is_active"] = original_flags.get(id(acc), False)
            restored_store = save_openai_accounts(accounts)
            return fail("Аккаунты OpenAI импортированы, но не удалось сохранить выбор активного аккаунта."
                        + ("" if restored_auth and restored_store else " Прежнее состояние восстановлено не полностью."))

    return count


def set_active_openai_account(account_id: str) -> bool:
    """Activate one account in OpenCode before committing Hub's active state."""
    with _accounts_lock:
        accounts = load_openai_accounts()
        target_account = _find_openai_account(accounts, account_id)
        if not target_account:
            return False
        previous_account = next((acc for acc in accounts if acc.get("is_active")), None)

        # OpenCode must acknowledge the switch first.  Saving is_active before
        # this point can make the UI claim a rotation that never reached the
        # already-running server.
        if not write_active_auth_openai(target_account):
            return False

        for acc in accounts:
            acc["is_active"] = acc is target_account
        if not save_openai_accounts(accounts):
            # The server was switched successfully but the protected Hub store
            # was not.  Restore the previous server selection to avoid a
            # split-brain state.
            if previous_account and previous_account is not target_account:
                write_active_auth_openai(previous_account)
            return False
        return True


def remove_opencode_credentials_openai(account: dict) -> bool:
    """Remove only the OpenCode credentials that belong to one Hub account."""
    if _opencode_database_path() is None:
        return True
    rows = _read_opencode_credential_rows()
    if rows is None:
        return False
    credential_id = get_openai_cred_id(account)
    credential_ids = {
        str(row.get("id")) for row in rows
        if row.get("id") and (
            row.get("id") == credential_id
            or _openai_credential_matches_account(row, account)
        )
    }
    if not credential_ids:
        return True
    cli = find_opencode_cli()
    if not cli:
        return False
    try:
        for item in sorted(credential_ids):
            _run_opencode_cli(cli, ["auth", "logout", "openai", item])
        remaining_rows = _read_opencode_credential_rows()
        if remaining_rows is None:
            return False
        remaining = {str(row.get("id")) for row in remaining_rows}
        return not (credential_ids & remaining)
    except Exception as exc:
        print(f"[OpenAI Manager] Credential removal failed ({type(exc).__name__})")
        return False


def remove_openai_account(account_id: str) -> bool:
    with _accounts_lock:
        accounts = load_openai_accounts()
        target = _find_openai_account(accounts, account_id)
        if not target:
            return False
        remaining = [acc for acc in accounts if acc is not target]
        was_active = bool(target.get("is_active"))

        if was_active and remaining:
            replacement = next((acc for acc in remaining if acc.get("is_active")), remaining[0])
            if not write_active_auth_openai(replacement):
                return False
            if not remove_opencode_credentials_openai(target):
                write_active_auth_openai(target)
                return False
            for acc in accounts:
                acc["is_active"] = acc is replacement
            if not save_openai_accounts(remaining):
                write_active_auth_openai(target)
                return False
            return True

        if was_active and not remaining:
            if not remove_opencode_credentials_openai(target):
                return False
            if not write_active_auth_openai(None):
                write_active_auth_openai(target)
                return False
            return save_openai_accounts([])

        if not remove_opencode_credentials_openai(target):
            return False
        return save_openai_accounts(remaining)


def set_openai_account_enabled(account_id: str, enabled: bool) -> bool:
    """Enables or disables an OpenAI account."""
    accounts = load_openai_accounts()
    target = _find_openai_account(accounts, account_id)
    if not target:
        return False
    target["enabled"] = enabled
    return save_openai_accounts(accounts)


def set_openai_account_candidate(account_id: str, candidate: bool) -> bool:
    """Sets whether an OpenAI account participates in auto-rotation."""
    accounts = load_openai_accounts()
    target = _find_openai_account(accounts, account_id)
    if not target:
        return False
    target["candidate"] = candidate
    return save_openai_accounts(accounts)


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

            if account.get("is_active"):
                write_active_auth_openai(account)

            return True, account
    except Exception as e:
        # Some HTTP/JSON exceptions embed the response body, which can contain tokens.
        print(f"[OpenAI Manager] Token refresh failed ({type(e).__name__})")
        return False, account


def fetch_openai_usage(account: dict, _retried: bool = False) -> dict:
    # If token expires within 2 minutes, refresh it first
    now_ms = int(time.time() * 1000)
    if not _retried and account.get("expires", 0) - now_ms < 120000:
        try:
            refresh_openai_token(account)
        except Exception as exc:
            print(f"[OpenAI Manager] Token refresh failed ({type(exc).__name__})")

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

    try:
        opener = _get_http_opener(timeout=12)
        with opener.open(req, timeout=12) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
            return _parse_usage_payload(payload, account)
    except urllib.error.HTTPError as he:
        if he.code == 401 and not _retried:
            # Token might have been revoked/expired - retry once with refresh
            try:
                ok, updated_acc = refresh_openai_token(account)
            except Exception:
                ok = False
            if ok:
                return fetch_openai_usage(updated_acc, _retried=True)
        print(f"[OpenAI Manager] Usage HTTP error {he.code}")
    except Exception as e:
        print(f"[OpenAI Manager] Usage fetch failed ({type(e).__name__})")

    return _stale_openai_usage(account)


def _stale_openai_usage(account: dict) -> dict:
    cached = account.get("quota") or {}
    if isinstance(cached, dict) and cached.get("status") in ("ok", "stale"):
        return {**cached, "status": "stale"}
    return {"status": "error", "primary": {}, "secondary": {}}


def _parse_usage_payload(payload: dict, account: dict) -> dict:
    if not isinstance(payload, dict) or not isinstance(payload.get("rate_limit"), dict):
        raise ValueError("Некорректный ответ о квоте OpenAI")
    if payload.get("email"):
        account["email"] = payload["email"]
    if payload.get("plan_type"):
        account["plan_type"] = payload["plan_type"]

    rate_limit = payload["rate_limit"]
    w1 = rate_limit.get("primary_window")
    w2 = rate_limit.get("secondary_window")

    def seconds(value):
        number = _quota_number(value)
        return int(number) if number is not None and number >= 0 else 0

    def parse_window(win: dict) -> dict:
        if not isinstance(win, dict):
            return {}
        used_pct = _quota_number(win.get("used_percent"))
        if used_pct is None or not 0 <= used_pct <= 100:
            return {}
        rem_pct = 100.0 - used_pct
        reset_after = seconds(win.get("reset_after_seconds"))
        reset_at = seconds(win.get("reset_at"))

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
            "used_percent": used_pct,
            "remaining_percent": rem_pct,
            "reset_after_seconds": reset_after,
            "reset_at": reset_at,
            "reset_label": reset_label,
            "limit_window_seconds": seconds(win.get("limit_window_seconds")),
        }

    primary, secondary = parse_window(w1), parse_window(w2)
    parsed_5h, parsed_weekly = primary, secondary
    if primary.get("limit_window_seconds", 0) > 86400 and secondary.get("limit_window_seconds", 0) <= 86400:
        parsed_5h, parsed_weekly = secondary, primary
    elif not primary and 0 < secondary.get("limit_window_seconds", 0) <= 86400:
        parsed_5h, parsed_weekly = secondary, primary

    allowed = rate_limit.get("allowed")
    limit_reached = rate_limit.get("limit_reached")
    if not (primary or secondary or isinstance(allowed, bool) or isinstance(limit_reached, bool)):
        return _stale_openai_usage(account)

    quota_data = {
        "status": "ok",
        "plan_type": payload.get("plan_type", account.get("plan_type", "plus")),
        "allowed": allowed if isinstance(allowed, bool) else None,
        "limit_reached": limit_reached if isinstance(limit_reached, bool) else None,
        "primary": parsed_5h,
        "secondary": parsed_weekly,
        "window_5h": parsed_5h,
        "window_weekly": parsed_weekly,
        "credits": payload.get("credits", {}),
        "last_checked": int(time.time()),
    }

    account["quota"] = quota_data
    return quota_data


def _quota_number(value):
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def _quota_windows(quota: dict):
    return [quota[key] if isinstance(quota.get(key), dict) else {} for key in ("primary", "secondary")]


def _openai_quota_exhausted(quota: dict) -> bool:
    """Return whether a ChatGPT quota payload forbids further requests."""
    if not isinstance(quota, dict):
        return False

    def exhausted(window: dict) -> bool:
        remaining = _quota_number(window.get("remaining_percent"))
        used = _quota_number(window.get("used_percent"))
        return remaining == 0 or used == 100

    return (
        quota.get("limit_reached") is True
        or quota.get("allowed") is False
        or any(exhausted(window) for window in _quota_windows(quota))
    )


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
    if not isinstance(quota, dict) or quota.get("status") != "ok" or not _openai_quota_exhausted(quota):
        return False, ""

    # Find enabled candidates with remaining quota in both windows. A candidate
    # explicitly marked as limited is skipped even if a stale percentage is > 0.
    candidates = []
    for account in accounts:
        if account is active_acc:
            continue
        identity = _openai_account_identity(account)
        if not identity or identity == _openai_account_identity(active_acc):
            continue
        if account.get("enabled", True) is False or account.get("candidate", True) is False:
            continue
        candidate_quota = account.get("quota") or {}
        if (not isinstance(candidate_quota, dict) or candidate_quota.get("status") != "ok"
                or _openai_quota_exhausted(candidate_quota)):
            continue
        remaining = [_quota_number(w.get("remaining_percent")) for w in _quota_windows(candidate_quota)]
        if candidate_quota.get("allowed") is True or all(r is not None and 0 < r <= 100 for r in remaining):
            candidates.append(account)

    if not candidates:
        return False, "Нет доступных аккаунтов OpenAI с подтверждённой квотой."

    next_acc = candidates[0]
    if not set_active_openai_account(next_acc.get("id") or next_acc.get("accountId") or next_acc.get("email")):
        return False, "Не удалось активировать следующий аккаунт OpenAI."
    for a in accounts:
        a["is_active"] = a is next_acc

    return True, f"Лимит {active_acc.get('email')} исчерпан. Автоматически переключен на {next_acc.get('email')} на лету (без перезапуска)."


def refresh_all_openai_accounts() -> tuple[list[dict], str | None]:
    accounts = load_openai_accounts()
    for acc in accounts:
        try:
            acc["quota"] = fetch_openai_usage(acc)
            acc["last_used"] = int(time.time())
        except Exception as e:
            print(f"[OpenAI Manager] Quota refresh failed ({type(e).__name__})")
            acc["quota"] = _stale_openai_usage(acc)
    if not save_openai_accounts(accounts):
        raise OSError("Не удалось сохранить лимиты ChatGPT")

    _rotated, msg = check_and_auto_rotate_openai(accounts)
    return accounts, (msg or None)


# --- OAuth Server Handler for Browser Login ---

class _OAuthCallbackHandler(_BoundedHandler):
    def log_message(self, format, *args):
        # Suppress standard logging to keep output clean
        pass

    def do_GET(self):
        if self.path.partition("?")[0] != "/auth/callback":
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"Not Found")
            return

        try:
            params = urllib.parse.parse_qs(self.path.partition("?")[2], max_num_fields=16)
        except ValueError:
            self.send_error(400, "Invalid OAuth callback")
            return
        error = params.get("error_description", [None])[0] or params.get("error", [None])[0]
        code = params.get("code", [None])[0]
        state = params.get("state", [None])[0]

        server: _OAuthServer = self.server  # type: ignore

        if (server.done_event.is_set() or len(params.get("state", [])) != 1 or
                not secrets.compare_digest(state.encode("utf-8"), server.expected_state.encode("utf-8"))):
            self._render_page(False, "Неверное состояние OAuth.")
            return

        if error or not code or len(params.get("code", [])) != 1:
            server.auth_error = "Сервер авторизации отклонил запрос." if error else "Отсутствует код авторизации."
            try:
                self._render_page(False, server.auth_error)
            finally:
                server.done_event.set()
            return

        server.auth_code = code
        try:
            self._render_page(True, "Ответ получен. Вернитесь в Hub и дождитесь результата сохранения аккаунта.")
        finally:
            server.done_event.set()

    def _render_page(self, success: bool, message: str):
        self.send_response(200 if success else 400)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()

        color = "#10b981" if success else "#ef4444"
        icon = "✓" if success else "✕"
        html = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>AI HUB — OpenAI Auth</title>
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
    <h2>{'Ответ браузера получен' if success else 'Ошибка входа'}</h2>
    <p>{escape(message)}</p>
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
        return False, f"Не удалось запустить локальный сервер на порту {OPENAI_CALLBACK_PORT} ({type(e).__name__})", None

    server_thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=0.1), daemon=True)
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
        if not webbrowser.open(auth_url):
            return False, "Не удалось открыть браузер по умолчанию.", None
        finished = server.done_event.wait(timeout=timeout)
    except Exception as e:
        return False, f"Не удалось открыть браузер ({type(e).__name__})", None
    finally:
        server.shutdown()
        server_thread.join(timeout=2)
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
            "User-Agent": OPENAI_BROWSER_UA,
        },
    )

    try:
        opener = _get_http_opener(timeout=15)
        with opener.open(token_req, timeout=15) as resp:
            tokens = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        return False, f"Ошибка обмена кода на токены ({type(e).__name__})", None

    if not tokens.get("access_token"):
        return False, "Сервер авторизации не вернул access_token.", None

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
        print(f"[OpenAI Manager] Usage fetch error after login ({type(e).__name__})")

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

    if not save_openai_accounts(accounts):
        return False, "Не удалось сохранить аккаунт ChatGPT на диск.", None
    if not write_active_auth_openai(new_account):
        return False, "Аккаунт сохранён в Hub, но не удалось активировать его в OpenCode.", new_account

    return True, f"Аккаунт {new_account['email']} успешно подключен!", new_account
