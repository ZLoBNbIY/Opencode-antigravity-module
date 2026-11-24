"""Idempotent provisioning of the Antigravity pool credential in OpenCode 2.

OpenCode 2 exposes its integration auth flow through the local CLI::

    opencode-cli.exe api GET  /api/integration
    opencode-cli.exe api POST /api/integration/google/connect/oauth --data '<json>'
    opencode-cli.exe api POST /api/integration/google/connect/oauth/<id>/complete --data '{}'

The module never deletes, disables or switches credentials: the
``GOOGLE_GENERATIVE_AI_API_KEY`` env connection and any foreign credential stay
untouched.  Only plugin profile 3.1.x (GA) is supported; the version is taken
from ``cloudcode_route_patch.get_expected_plugin_version()`` (which honours the
Hub/OpenCode pin), never from a literal here.

Safety: CLI output, exception details, tokens, attempt IDs and credential IDs
are never logged.  Every call has a timeout, and only the documented fields
(``id``/``status``/``mode`` of an attempt and ``data[].id``, ``connections[]``,
``methods[]`` of an integration) are read.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import threading
import time
from pathlib import Path
from urllib.parse import quote

# Child of the Hub logger: inherits its file handler without importing it.
log = logging.getLogger("ai_hub.google_connection")

POOL_METHOD_ID = "antigravity-auth-pool-reconnect"
POOL_LABEL = "Antigravity Hub pool"
GOOGLE_INTEGRATION_ID = "google"

API_GET = "GET"
API_POST = "POST"
INTEGRATION_PATH = "/api/integration"
CONNECT_PATH = "/api/integration/google/connect/oauth"

GET_TIMEOUT = 8
POST_TIMEOUT = 10
VERIFY_TIMEOUT = 6
RETRY_ATTEMPTS = 3
RETRY_DELAY = 0.5

# Canonical statuses (see docs/google-connection.md).
ALREADY_CONNECTED = "already_connected"
CONNECTED = "connected"
SKIP = "skip"
CLI_MISSING = "cli_missing"
API_ERROR = "api_error"
TIMEOUT = "timeout"
VERIFY_FAILED = "verify_failed"
IN_PROGRESS = "connect_in_progress"
FOREIGN_CREDENTIAL = "foreign_credential"
STALE_FOREIGN_CREDENTIAL = "stale_foreign_credential"
INACTIVE = "inactive"

# Backwards-compatible aliases for early callers of this module.
ALREADY = ALREADY_CONNECTED
UNSUPPORTED = SKIP
NO_CLI = CLI_MISSING
FAILED = API_ERROR
INCOMPLETE = TIMEOUT
BUSY = IN_PROGRESS

_VERSION_RE = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
_ATTEMPT_ID_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.:-]{0,255}$")
_FAILED_STATES = {"failed", "error", "expired", "cancelled", "canceled", "rejected"}

# Process-wide guard in addition to the HubApi's non-blocking lock: startup and
# parallel logins must never create two credentials.
_POOL_LOCK = threading.Lock()


def _debug(status: str) -> None:
    # Static status only - no args, stdout, stderr or exception attributes.
    log.info("Google connection: status=%s", status)


def is_supported_version(version) -> bool:
    """True only for a strict 3.1.x GA version string."""
    match = _VERSION_RE.fullmatch(version) if isinstance(version, str) else None
    return bool(match and match.group(1) == "3" and match.group(2) == "1")


def expected_version():
    """Resolve the plugin profile through the existing Hub helper."""
    try:
        import cloudcode_route_patch
        return cloudcode_route_patch.get_expected_plugin_version()
    except Exception:
        return None


def _is_file(path) -> bool:
    try:
        return bool(path) and os.path.isfile(os.fspath(path))
    except (TypeError, ValueError, OSError):
        return False


def resolve_cli(*, manager=None, is_file=None, which=None):
    """Find opencode-cli.exe: Hub helper first, then beside OpenCode.exe, then PATH."""
    is_file = is_file or _is_file
    which = which or shutil.which
    if manager is None:
        try:
            import antigravity_manager as manager  # noqa: F401
        except Exception:
            manager = None

    helper = getattr(manager, "get_opencode_cli", None)
    if callable(helper):
        try:
            candidate = helper()
        except Exception:
            candidate = None
        if candidate and is_file(candidate):
            return str(candidate)

    # Generic discovery: no publisher/tenant directory name is hard-coded here.
    try:
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
        for candidate in (base / "Programs").glob("*/resources/opencode-cli.exe"):
            if is_file(candidate):
                return str(candidate)
    except (OSError, ValueError):
        pass

    exe = None
    exe_helper = getattr(manager, "get_opencode_exe", None)
    if callable(exe_helper):
        try:
            exe = exe_helper()
        except Exception:
            exe = None
    exe_paths = []
    if exe and is_file(exe):
        exe_paths.append(Path(exe))
    try:
        programs = Path.home() / "AppData" / "Local" / "Programs"
        if programs.is_dir():
            exe_paths.extend(p for p in programs.glob("*/OpenCode.exe") if is_file(p))
    except (OSError, ValueError):
        pass
    for exe_path in exe_paths:
        for relative in ("resources/opencode-cli.exe", "opencode-cli.exe", "cli/opencode-cli.exe"):
            candidate = exe_path.parent / relative
            if is_file(candidate):
                return str(candidate)

    for name in ("opencode-cli", "opencode"):
        try:
            found = which(name)
        except Exception:
            found = None
        if found and is_file(found):
            return found
    return None


def _run_cli(args, timeout):
    """Run through the Hub helper with proxy-stripped environment.

    ``opencode_launch_environment()`` removes stale Hub HTTP_PROXY/
    HTTPS_PROXY/ALL_PROXY values so the local API call cannot be routed through
    the Hub's own dispatcher.
    """
    import antigravity_manager
    import proxy_config
    return antigravity_manager.run_silent_cmd(
        args, timeout=timeout, env=proxy_config.opencode_launch_environment())


def _parse_object(stdout):
    """Decode the first JSON object in stdout, ignoring CLI chatter."""
    if not isinstance(stdout, str):
        return None
    start = stdout.find("{")
    if start < 0:
        return None
    try:
        value, _ = json.JSONDecoder().raw_decode(stdout[start:])
    except (ValueError, TypeError):
        return None
    return value if isinstance(value, dict) else None


def api_request(cli, method, path, data=None, *, run_cli=None, timeout=POST_TIMEOUT):
    """Call ``opencode api``; return the parsed object or None on any failure."""
    args = [str(cli), "api", method, path]
    if data is not None:
        # One argument, never shell interpolation. Contains no credentials.
        args.extend(["--data", json.dumps(data, ensure_ascii=False, separators=(",", ":"))])
    try:
        result = (run_cli or _run_cli)(args, timeout=timeout)
        if getattr(result, "returncode", 1) != 0:
            return None
        return _parse_object(getattr(result, "stdout", ""))
    except Exception:
        return None


def _first_str(row, keys):
    if not isinstance(row, dict):
        return ""
    for key in keys:
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _integration_rows(payload):
    """Only the real CLI envelope ``{"location": ..., "data": [...]}``."""
    if not isinstance(payload, dict):
        return []
    data = payload.get("data")
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return [data]
    return []


def _google_integration(payload):
    for row in _integration_rows(payload):
        if isinstance(row, dict) and row.get("id") == GOOGLE_INTEGRATION_ID:
            return row
    return None


def _google_connections(payload):
    """Connections of the ``id == "google"`` entry of the CLI ``data`` envelope."""
    return _connections(_google_integration(payload))


def has_pool_connection(payload) -> bool:
    """True when the Google integration already has our Hub-labelled credential."""
    return classify_connections(_google_integration(payload),
                                active_check=lambda _integration_id: None) == ALREADY_CONNECTED


def _methods(integration):
    """Return the set of advertised method IDs, or None when not advertised."""
    if not isinstance(integration, dict):
        return None
    raw = integration.get("methods")
    if isinstance(raw, dict):
        return set(str(key) for key in raw)
    if not isinstance(raw, list):
        return None
    methods = set()
    for entry in raw:
        if isinstance(entry, str):
            methods.add(entry)
        elif isinstance(entry, dict):
            name = _first_str(entry, ("id", "methodID", "methodId", "name"))
            if name:
                methods.add(name)
    return methods


def _connections(integration):
    if not isinstance(integration, dict):
        return []
    rows = integration.get("connections")
    if isinstance(rows, list):
        return rows
    if isinstance(rows, dict):
        return list(rows.values())
    return []


def _is_pool_row(row) -> bool:
    """Hub credential marker: type=credential, label=POOL_LABEL, method=oauth.

    ``methodID`` is only the plugin's internal placeholder and must never be
    compared with a connection field (there ``method`` is always ``"oauth"``).
    """
    if not isinstance(row, dict):
        return False
    if _first_str(row, ("label",)) != POOL_LABEL:
        return False
    method = _first_str(row, ("method",)).lower()
    return method in ("", "oauth")


def _default_active_check(integration_id):
    try:
        import openai_manager
        reader = getattr(openai_manager, "_read_opencode_credential_rows", None)
        return reader(integration_id) if callable(reader) else None
    except Exception:
        return None


def _is_inactive(row, active_check=None) -> bool:
    """Read-only ``active`` flag of our credential; unknown state is not inactive."""
    checker = active_check or _default_active_check
    try:
        rows = checker(GOOGLE_INTEGRATION_ID)
    except Exception:
        return False
    if not isinstance(rows, list):
        return False
    credential_id = row.get("id") if isinstance(row, dict) else None
    for candidate in rows:
        if not isinstance(candidate, dict):
            continue
        matches = (
            (credential_id and candidate.get("id") == credential_id)
            or candidate.get("label") == POOL_LABEL
        )
        if matches:
            return not bool(candidate.get("active"))
    return False


def _stale_foreign_credentials(foreign_rows, active_check=None):
    """Detect a dead legacy OAuth credential that can be safely worked around.

    OpenCode may keep an old ``methodID=oauth`` row with an empty access token,
    zero expiry and no usable method.  It is not a live user credential, so it
    must not block provisioning of the Hub pool credential.  We never delete it:
    the pool login simply creates its own active credential alongside it.
    Any credential whose state cannot be positively confirmed as stale is still
    treated as foreign and is never duplicated.
    """
    checker = active_check or _default_active_check
    try:
        db_rows = checker(GOOGLE_INTEGRATION_ID)
    except Exception:
        return False
    if not isinstance(db_rows, list) or not foreign_rows:
        return False
    by_id = {
        str(row.get("id")): row for row in db_rows
        if isinstance(row, dict) and row.get("id")
    }
    for row in foreign_rows:
        match = by_id.get(_first_str(row, ("id",)))
        if not isinstance(match, dict):
            return False
        value = match.get("value")
        if not isinstance(value, dict):
            return False
        method = _first_str(value, ("methodID", "methodId", "method")).lower()
        if method and method != "oauth":
            return False
        access = value.get("access")
        if isinstance(access, str):
            if access.strip():
                return False
        elif access not in (None, "", 0, False):
            return False
        try:
            if float(value.get("expires") or 0) > 0:
                return False
        except (TypeError, ValueError):
            return False
    return True


def classify_connections(integration, active_check=None):
    """Return a terminal status, or None when provisioning may proceed."""
    ours = None
    foreign_rows = []
    for row in _connections(integration):
        if not isinstance(row, dict):
            continue
        row_type = _first_str(row, ("type",)).lower()
        if row_type == "credential":
            if _is_pool_row(row):
                ours = row
            else:
                foreign_rows.append(row)
    if ours is not None:
        if _is_inactive(ours, active_check):
            return INACTIVE
        return ALREADY_CONNECTED
    if foreign_rows:
        if _stale_foreign_credentials(foreign_rows, active_check):
            _debug(STALE_FOREIGN_CREDENTIAL)
            return None
        return FOREIGN_CREDENTIAL
    return None


def _attempt(payload):
    if not isinstance(payload, dict):
        return {}
    for holder in (payload, payload.get("attempt"), payload.get("data")):
        if not isinstance(holder, dict):
            continue
        result = {
            "id": _first_str(holder, ("attemptID", "attemptId", "id")),
            "mode": _first_str(holder, ("mode",)).lower(),
            "status": _first_str(holder, ("status",)).lower(),
        }
        if result["id"] or result["mode"] or result["status"]:
            return result
    return {}


def _verify(cli, run_cli):
    payload = api_request(cli, API_GET, INTEGRATION_PATH, run_cli=run_cli, timeout=VERIFY_TIMEOUT)
    integration = _google_integration(payload)
    status = classify_connections(integration)
    # Verification must distinguish "connected now" from an earlier listing.
    result = CONNECTED if status == ALREADY_CONNECTED else VERIFY_FAILED
    _debug(result)
    return result


def ensure_google_connection(cli=None, *, version=None, resolve=True, run_cli=None,
                             active_check=None, stop=None,
                             attempts=RETRY_ATTEMPTS, retry_delay=RETRY_DELAY,
                             is_file=None, sleep=None):
    """Idempotently ensure the Hub pool credential exists.

    ``cli`` normally comes from ``antigravity_manager.get_opencode_cli()``; pass
    ``resolve=False`` when the caller already did that lookup.  ``stop`` is an
    optional callback checked between stages (Hub closing/uninstalled).

    Returns one of the status constants.  Never raises to the UI.
    """
    if not _POOL_LOCK.acquire(blocking=False):
        _debug(IN_PROGRESS)
        return IN_PROGRESS
    try:
        if callable(stop) and stop():
            return SKIP
        if not is_supported_version(expected_version() if version is None else version):
            _debug(SKIP)
            return SKIP

        check_file = is_file or _is_file
        target = cli if cli is not None else (resolve_cli(is_file=check_file) if resolve else None)
        if not target or not check_file(target):
            _debug(CLI_MISSING)
            return CLI_MISSING
        target = str(target)

        # A just-started server may refuse the first GET. The listing is
        # read-only, so it is the only stage we retry.
        payload = None
        for index in range(max(1, int(attempts))):
            if callable(stop) and stop():
                return SKIP
            candidate = api_request(target, API_GET, INTEGRATION_PATH,
                                    run_cli=run_cli, timeout=GET_TIMEOUT)
            if candidate is not None and _google_integration(candidate) is not None:
                payload = candidate
                break
            if index + 1 < attempts:
                try:
                    (sleep or time.sleep)(retry_delay)
                except Exception:
                    pass
        if payload is None:
            _debug(API_ERROR)
            return API_ERROR

        integration = _google_integration(payload)
        methods = _methods(integration)
        if methods is not None and POOL_METHOD_ID not in methods:
            _debug(SKIP)
            return SKIP
        status = classify_connections(integration, active_check)
        if status:
            _debug(status)
            return status

        # Re-read under the lock to close the race with another thread whose
        # attempt finished while this one was waiting for the lock.
        if not (callable(stop) and stop()):
            fresh = api_request(target, API_GET, INTEGRATION_PATH,
                                run_cli=run_cli, timeout=GET_TIMEOUT)
            status = classify_connections(_google_integration(fresh), active_check)
            if status:
                _debug(status)
                return status

        started = api_request(target, API_POST, CONNECT_PATH,
                              {"methodID": POOL_METHOD_ID, "label": POOL_LABEL},
                              run_cli=run_cli, timeout=POST_TIMEOUT)
        attempt = _attempt(started)
        if not attempt["id"] or attempt["mode"] != "auto":
            _debug(API_ERROR)
            return API_ERROR
        if attempt["status"] in _FAILED_STATES:
            _debug(TIMEOUT)
            return TIMEOUT
        if attempt["status"] == "complete":
            return _verify(target, run_cli)

        attempt_id = attempt["id"]
        if not _ATTEMPT_ID_RE.fullmatch(attempt_id):
            _debug(API_ERROR)
            return API_ERROR
        completed = api_request(target, API_POST,
                                f"{CONNECT_PATH}/{quote(attempt_id, safe='')}/complete",
                                {}, run_cli=run_cli, timeout=POST_TIMEOUT)
        if _attempt(completed).get("status") != "complete":
            _debug(TIMEOUT)
            return TIMEOUT
        return _verify(target, run_cli)
    except Exception:
        _debug(API_ERROR)
        return API_ERROR
    finally:
        _POOL_LOCK.release()


# Early name kept as an alias; webview_backend uses ensure_google_connection.
ensure_pool_connection = ensure_google_connection
