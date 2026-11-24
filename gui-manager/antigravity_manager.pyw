"""Antigravity Hub WebView2 application entry point and shared backend helpers."""

import os
import sys
import json
import math
import hashlib
import time
import datetime
import subprocess
import threading
import uuid
import secrets
from pathlib import Path
import shutil

sys.path.insert(0, str(Path(__file__).resolve().parent))

from hub_paths import get_opencode_config_dir

# Keep the Windows mutex handle alive for the lifetime of this process.
_SINGLE_INSTANCE_MUTEX = None
_google_store_lock = threading.RLock()


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{secrets.token_hex(6)}.tmp")
    fd = os.open(
        tmp,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0),
        0o600,
    )
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            if os.name != "nt" and hasattr(os, "fchmod"):
                os.fchmod(stream.fileno(), 0o600)
            os.fsync(stream.fileno())
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def _atomic_write_json(path: Path, data: dict) -> None:
    payload = (json.dumps(data, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    _atomic_write_bytes(path, payload)


def _google_row_ref(cfg: dict, row_id: str) -> dict:
    pool_rows = (cfg.get("commonAuthPool") or {}).get("rows") or {}
    row_entry = pool_rows.get(row_id) if isinstance(pool_rows, dict) else None
    epoch = row_entry.get("credentialEpoch") if isinstance(row_entry, dict) else None
    if not isinstance(epoch, int) or isinstance(epoch, bool) or epoch < 1:
        epoch = 1
    ref: dict = {"id": row_id, "credentialEpoch": epoch}
    for acc in cfg.get("accounts") or []:
        if isinstance(acc, dict) and acc.get("id") == row_id:
            identity = acc.get("accountId")
            if isinstance(identity, str) and identity.strip():
                ref["identity"] = identity.strip()
            break
    return ref


def _expects_v2_google_store(config_dir: Path) -> bool:
    pointer_file = config_dir / "antigravity-accounts.json.store.pointer.json"
    if pointer_file.exists() or has_relocated_google_store(config_dir):
        return True
    try:
        import cloudcode_route_patch
        expected = cloudcode_route_patch.get_expected_plugin_version()
        if isinstance(expected, str):
            parts = expected.split(".")
            if len(parts) == 3 and all(p.isdigit() for p in parts):
                if tuple(int(p) for p in parts) >= (3, 1, 0):
                    return True
    except Exception:
        pass
    return False


def acquire_single_instance():
    """Acquire the Hub mutex once in a normal GUI entry point, before GUI startup."""
    global _SINGLE_INSTANCE_MUTEX
    if sys.platform != "win32" or _SINGLE_INSTANCE_MUTEX is not None:
        return True
    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
        kernel32.CreateMutexW.restype = wintypes.HANDLE
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        ctypes.set_last_error(0)
        handle = kernel32.CreateMutexW(None, True, "Local\\AntigravityHub.SingleInstance")
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())
        if ctypes.get_last_error() == 183:  # ERROR_ALREADY_EXISTS
            kernel32.CloseHandle(handle)
            return False
        _SINGLE_INSTANCE_MUTEX = handle
        return True
    except Exception as e:
        # Fail closed: do not risk launching a second Hub if the mutex cannot be checked.
        print(f"Could not acquire Antigravity Hub single-instance mutex: {e}")
        return False


def set_windows_taskbar_identity():
    """Give taskbar windows a Hub identity instead of Python's default identity."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        result = ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("AntigravityHub.Desktop")
        if result != 0:
            raise OSError(f"SetCurrentProcessExplicitAppUserModelID failed: 0x{result & 0xffffffff:08X}")
    except Exception as exc:
        print(f"Could not set Antigravity Hub taskbar identity: {exc}")


# --- Paths & Dynamic Resolution ---
def get_node_executable():
    if getattr(sys, "frozen", False):
        return str(Path(sys._MEIPASS) / "playwright" / "driver" / "node.exe")
    node = shutil.which("node")
    if node and os.path.exists(node):
        return node
    candidates = [
        Path("C:/Program Files/nodejs/node.exe"),
        Path("C:/Program Files (x86)/nodejs/node.exe"),
        Path.home() / "AppData/Local/Programs/cursor/resources/app/resources/helpers/node.exe",
        Path.home() / "AppData/Local/Programs/DeepSeek Harness/resources/runtime/primary-runtime/dependencies/node/bin/node.exe",
        Path.home() / "AppData/Local/Programs/Python/Python312/Lib/site-packages/playwright/driver/node.exe",
        Path.home() / "AppData/Local/Programs/Python/Python311/Lib/site-packages/playwright/driver/node.exe",
    ]
    for c in candidates:
        if c.exists():
            return str(c)
    return "node"

def get_cli_js():
    if getattr(sys, "frozen", False):
        return str(Path(sys._MEIPASS) / "plugin" / "dist" / "cli.js")
    local_cli = Path(__file__).resolve().parent.parent / "plugin" / "dist" / "cli.js"
    if local_cli.exists():
        return str(local_cli)

    npm_dir = Path.home() / ".cache" / "opencode" / "npm"
    if npm_dir.exists():
        matches = list(npm_dir.glob("**/@cortexkit/opencode-antigravity-auth/dist/cli.js"))
        if matches and matches[0].exists():
            return str(matches[0])
        matches_multi = list(npm_dir.glob("**/opencode-antigravity-multi-auth/dist/cli.js"))
        if matches_multi and matches_multi[0].exists():
            return str(matches_multi[0])

    cache_cli = Path.home() / ".cache" / "opencode" / "packages" / "@cortexkit" / "opencode-antigravity-auth@latest" / "node_modules" / "@cortexkit" / "opencode-antigravity-auth" / "dist" / "cli.js"
    if cache_cli.exists():
        return str(cache_cli)
    return str(local_cli)

def get_opencode_exe():
    candidates = [
        # Current installer layout (OpenCode Desktop >= 2.2)
        Path.home() / "AppData" / "Local" / "Programs" / "ai.opencode.desktop" / "OpenCode.exe",
        Path.home() / "AppData" / "Local" / "Programs" / "@opencodedesktop" / "OpenCode.exe",
        Path.home() / "AppData" / "Local" / "Programs" / "@opencode-desktop" / "OpenCode.exe",
        Path.home() / "AppData" / "Local" / "Programs" / "@opencode-aidesktop" / "OpenCode.exe",
        Path.home() / "AppData" / "Local" / "Programs" / "opencode" / "OpenCode.exe",
    ]
    for c in candidates:
        if c.exists():
            return str(c)
    which_opencode = shutil.which("opencode")
    if which_opencode:
        return which_opencode
    which_opencode_cap = shutil.which("OpenCode")
    if which_opencode_cap:
        return which_opencode_cap
    return str(candidates[0])

def get_opencode_cli():
    """Locate opencode-cli.exe without depending on an install folder name.

    Order: PATH, generic ``Programs\\*\\resources`` glob (newest install first),
    beside the detected desktop app, then the Roaming CLI cache.  A missing
    executable is never reported as a successful lookup.
    """
    candidates = []
    path_cli = shutil.which("opencode-cli") or shutil.which("opencode")
    if path_cli:
        candidates.append(Path(path_cli))
    programs = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / "Programs"
    if programs.is_dir():
        installed = [p for p in programs.glob("*/resources/opencode-cli.exe") if p.is_file()]
        installed.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        candidates.extend(installed)
    exe = get_opencode_exe()
    if exe:
        candidates.append(Path(exe).parent / "resources" / "opencode-cli.exe")
    roaming_cli = Path.home() / "AppData" / "Roaming" / "ai.opencode.desktop" / "cli"
    if roaming_cli.exists():
        candidates.extend(sorted(roaming_cli.glob("*/opencode-cli.exe"), reverse=True))
    for c in candidates:
        try:
            if c.is_file():
                return str(c)
        except OSError:
            continue
    return None

def cleanup_opencode_locks():
    try:
        state_dir = Path(os.path.expanduser("~/.local/state/opencode"))
        if state_dir.exists():
            for f in state_dir.glob("service.json*"):
                try:
                    f.unlink()
                except Exception:
                    pass
    except Exception:
        pass

NODE_EXE = get_node_executable()
CLI_JS = get_cli_js()
OPENCODE_EXE = get_opencode_exe()
CONFIG_DIR = get_opencode_config_dir()


def ordered_generation_dirs(config_dir: Path | None = None) -> list[Path]:
    """Generation stores with the pointer-selected (canonical) store first.

    The account store keeps a pointer file next to one or more ``*.generation``
    directories.  A raw ``glob`` returns them in filesystem order, which can
    pick a stale store while a migration is still settling.  Always prefer the
    pointer target, then fall back to newest-by-mtime.  All account readers and
    writers must use this helper instead of ``list(glob(...))[0]``.
    """
    base = Path(config_dir) if config_dir else get_opencode_config_dir()
    active = get_active_generation_dir(base)
    dirs = _generation_dirs(base)
    if active is not None:
        # A schema-2 pointer can relocate the live store outside the config
        # directory; in that case the canonical directory is not in `dirs`.
        return [active] + [p for p in dirs if p != active]
    def _safe_mtime(p: Path) -> float:
        try:
            return p.stat().st_mtime
        except OSError:
            return 0.0
    return sorted(dirs, key=_safe_mtime, reverse=True)


DEFAULT_CONFIG = {
    "$schema": "https://raw.githubusercontent.com/cortexkit/opencode-antigravity-auth/main/schema.json",
    # Keep the updater off: a plugin self-update replaces the bundles patched
    # by the Hub and silently reintroduces the Google 429 regression.
    "auto_update": False,
    # 3.1.x moved the account store and leaves a schema-2 pointer that older
    # releases refuse to open. Pin a version that understands this layout.
    "plugin_pin_version": "3.1.13",
    # Extended request cloaking (UA, system prompt, requestType, one retry)
    # is opt-in. The safe sanitizer/quota fixes are always enabled.
    "cloaking_v2": False,
    "account_selection_strategy": "hybrid",
    "soft_quota_threshold_percent": 100,
    "switch_on_first_rate_limit": True,
    "max_account_switches": 10,
    "quota_style_fallback": True,
    "debug": False,
    "vless_enabled": False,
    "vless_url": "",
    "vless_core_path": None,
    "vless_kill_switch": True,
    "vless_http_port": 10879,
    "vless_socks_port": 10878,
    "providers_visibility": {
        "antigravity": True,
        "openai": True,
        "claude": True,
        "openrouter": True,
        "xpiki": True,
        "deepseek": True,
        "tokenlavka": True,
        "nvidia": True,
    },
    "close_to_tray": True,
    "autostart_on_login": False,
    "max_rate_limit_wait_seconds": 300,
}

def _list_opencode_desktop_pids():
    """PIDs of every running OpenCode desktop process (Windows, locale-safe)."""
    if sys.platform != "win32":
        return []
    result = run_silent_cmd(
        ["tasklist", "/fi", "imagename eq OpenCode.exe", "/fo", "csv", "/nh"], timeout=10)
    pids = []
    for line in (result.stdout or "").splitlines():
        columns = [column.strip().strip('"') for column in line.split('","')]
        if len(columns) < 2 or columns[0].lower() != "opencode.exe" or not columns[1].isdigit():
            continue
        pid = int(columns[1])
        if pid != os.getpid():
            pids.append(pid)
    return pids


def terminate_opencode_desktop():
    """Close every OpenCode desktop window, including ones the Hub did not start.

    The Hub only tracks processes it launched itself in ``_opencode_process``.
    A window opened by the user from Explorer (or after an auto-update) has a
    different parent and would otherwise survive the restart, so the plugin
    code stays loaded and the restart button appears to do nothing.
    """
    if sys.platform != "win32":
        return {"ok": True, "closed": 0, "failed": 0, "message": "Not a Windows host."}
    pids = _list_opencode_desktop_pids()
    if not pids:
        return {"ok": True, "closed": 0, "failed": 0, "message": "No desktop process."}
    killed = run_silent_cmd(["taskkill", "/F", "/T", "/IM", "OpenCode.exe"], timeout=20)
    # Wait for the windows to actually exit: a new Popen can otherwise be
    # handed to the old single-instance Electron process.
    deadline = time.monotonic() + 10
    remaining = pids
    while remaining and time.monotonic() < deadline:
        time.sleep(0.3)
        remaining = _list_opencode_desktop_pids()
    if remaining:
        return {"ok": False, "closed": len(pids) - len(remaining), "failed": len(remaining),
                "message": f"OpenCode processes still running: {remaining}"}
    return {"ok": True, "closed": len(pids), "failed": 0,
            "message": f"Closed {len(pids)} process(es). taskkill rc={killed.returncode}"}


def run_silent_cmd(cmd, timeout=30, env=None):
    flags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
    startupinfo = None
    if sys.platform == "win32":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = subprocess.SW_HIDE
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            timeout=timeout,
            creationflags=flags,
            startupinfo=startupinfo,
            env=env,
        )
        stdout_str = proc.stdout.decode("utf-8", errors="replace") if proc.stdout else ""
        stderr_str = proc.stderr.decode("utf-8", errors="replace") if proc.stderr else ""
    except Exception as e:
        return type("SilentResult", (), {"returncode": 1, "stdout": "", "stderr": str(e)})()

    return type("SilentResult", (), {"returncode": proc.returncode, "stdout": stdout_str, "stderr": stderr_str})()


def provider_route_environment():
    """Environment for helper CLIs that fetch provider models or quotas."""
    import provider_proxy
    return provider_proxy.proxy_environment()


def run_google_route_cmd(cmd, timeout=30):
    return run_silent_cmd(cmd, timeout=timeout, env=provider_route_environment())


def get_active_google_account_index() -> int:
    config_dir = get_opencode_config_dir()
    gen_dirs = ordered_generation_dirs(config_dir)
    if gen_dirs:
        cfg_file = gen_dirs[0] / "config.json"
        if cfg_file.exists():
            try:
                cfg = json.loads(cfg_file.read_text(encoding="utf-8-sig")) or {}
                routing = cfg.get("antigravityRouting") or {}
                accounts = cfg.get("accounts") or []
                # Check active row for gemini first, then general activeRow
                active_row_by_family = routing.get("activeRowByFamily") or {}
                gemini_row = active_row_by_family.get("gemini") if isinstance(active_row_by_family, dict) else None
                active_row = routing.get("activeRow")
                active_row_id = (
                    (gemini_row.get("id") if isinstance(gemini_row, dict) else None)
                    or (active_row.get("id") if isinstance(active_row, dict) else None)
                )
                if active_row_id:
                    for i, acc in enumerate(accounts):
                        if acc.get("id") == active_row_id:
                            return i
                idx = routing.get("activeIndexByFamily", {}).get("gemini")
                if idx is not None and 0 <= int(idx) < len(accounts):
                    return int(idx)
                idx = routing.get("activeIndex")
                if idx is not None and 0 <= int(idx) < len(accounts):
                    return int(idx)
            except Exception:
                pass
    legacy_file = config_dir / "antigravity-accounts.json"
    if legacy_file.exists():
        try:
            data = json.loads(legacy_file.read_text(encoding="utf-8-sig")) or {}
            return int(data.get("activeIndex", 0))
        except Exception:
            pass
    return 0


def set_active_google_account_index(target_index: int) -> bool:
    with _google_store_lock:
        config_dir = get_opencode_config_dir()
        gen_dirs = ordered_generation_dirs(config_dir)
        changed = False
        if gen_dirs:
            cfg_file = gen_dirs[0] / "config.json"
            state_file = gen_dirs[0] / "state.json"
            if cfg_file.exists():
                try:
                    orig_cfg_bytes = cfg_file.read_bytes()
                    cfg = json.loads(orig_cfg_bytes.decode("utf-8-sig"))
                    accounts = cfg.get("accounts", [])
                    if 0 <= target_index < len(accounts):
                        target_id = accounts[target_index].get("id")
                        routing = cfg.get("antigravityRouting") or {}
                        routing["activeIndex"] = target_index
                        routing["activeIndexByFamily"] = {"claude": target_index, "gemini": target_index}
                        if target_id:
                            row_ref = _google_row_ref(cfg, target_id)
                            routing["activeRow"] = dict(row_ref)
                            routing["activeRowByFamily"] = {
                                "claude": dict(row_ref),
                                "gemini": dict(row_ref),
                            }
                        # Ensure selected account is enabled in commonAuthPool
                        rows = cfg.get("commonAuthPool", {}).get("rows", {})
                        if target_id in rows:
                            rows[target_id]["enabled"] = True
                            rows[target_id]["usable"] = True
                        accounts[target_index]["enabled"] = True
                        accounts[target_index]["candidate"] = True

                        cfg["antigravityRouting"] = routing
                        _atomic_write_json(cfg_file, cfg)
                        if target_id and state_file.exists():
                            try:
                                state = json.loads(state_file.read_text(encoding="utf-8-sig"))
                                if target_id in state.get("accounts", {}):
                                    meta = state["accounts"][target_id].setdefault("commonAuthProviderState", {}).setdefault("metadata", {})
                                    if meta.get("enabled") is not True:
                                        meta["enabled"] = True
                                        _atomic_write_json(state_file, state)
                            except Exception:
                                _atomic_write_bytes(cfg_file, orig_cfg_bytes)
                                raise
                        changed = True
                except Exception as e:
                    print(f"Error updating generation config: {e}")

        legacy_file = config_dir / "antigravity-accounts.json"
        if legacy_file.exists():
            try:
                legacy_data = json.loads(legacy_file.read_text(encoding="utf-8-sig"))
                legacy_data["activeIndex"] = target_index
                if "activeIndexByFamily" in legacy_data:
                    legacy_data["activeIndexByFamily"] = {"claude": target_index, "gemini": target_index}
                _atomic_write_json(legacy_file, legacy_data)
                changed = True
            except Exception:
                pass

        return changed


def set_google_account_candidate(target_email_or_id: str, candidate: bool) -> bool:
    """Persists account auto-rotation candidate flag without disabling the account itself."""
    with _google_store_lock:
        config_dir = get_opencode_config_dir()
        gen_dirs = ordered_generation_dirs(config_dir)
        changed = False

        if gen_dirs:
            gen_dir = gen_dirs[0]
            cfg_file = gen_dir / "config.json"
            state_file = gen_dir / "state.json"
            if cfg_file.exists():
                try:
                    cfg = json.loads(cfg_file.read_text(encoding="utf-8-sig"))
                    target_id = None

                    if state_file.exists():
                        try:
                            state = json.loads(state_file.read_text(encoding="utf-8-sig"))
                            for aid, st in state.get("accounts", {}).items():
                                meta = st.get("commonAuthProviderState", {}).get("metadata", {})
                                if aid == target_email_or_id or meta.get("email") == target_email_or_id:
                                    target_id = aid
                                    break
                        except Exception:
                            pass

                    if not target_id:
                        for acc in cfg.get("accounts", []):
                            if acc.get("id") == target_email_or_id or acc.get("email") == target_email_or_id:
                                target_id = acc.get("id")
                                break

                    if target_id:
                        rows = cfg.get("commonAuthPool", {}).get("rows", {})
                        if target_id in rows:
                            rows[target_id]["usable"] = candidate
                        for acc in cfg.get("accounts", []):
                            if acc.get("id") == target_id:
                                acc["candidate"] = candidate

                        _atomic_write_json(cfg_file, cfg)
                        changed = True
                except Exception as e:
                    print(f"Error updating candidate in generation config: {e}")

        legacy_file = config_dir / "antigravity-accounts.json"
        if legacy_file.exists():
            try:
                legacy_data = json.loads(legacy_file.read_text(encoding="utf-8-sig"))
                legacy_changed = False
                for acc in legacy_data.get("accounts", []):
                    if acc.get("id") == target_email_or_id or acc.get("email") == target_email_or_id:
                        acc["candidate"] = candidate
                        legacy_changed = True
                if legacy_changed:
                    _atomic_write_json(legacy_file, legacy_data)
                    changed = True
            except Exception:
                pass

        return changed


def set_google_account_enabled(target_email_or_id: str, enabled: bool) -> bool:
    """Persists account enabled/disabled state to commonAuthPool and config."""
    with _google_store_lock:
        config_dir = get_opencode_config_dir()
        gen_dirs = ordered_generation_dirs(config_dir)
        changed = False

        if gen_dirs:
            gen_dir = gen_dirs[0]
            cfg_file = gen_dir / "config.json"
            state_file = gen_dir / "state.json"
            if cfg_file.exists():
                try:
                    orig_cfg_bytes = cfg_file.read_bytes()
                    cfg = json.loads(orig_cfg_bytes.decode("utf-8-sig"))
                    target_id = None

                    if state_file.exists():
                        try:
                            state = json.loads(state_file.read_text(encoding="utf-8-sig"))
                            for aid, st in state.get("accounts", {}).items():
                                meta = st.get("commonAuthProviderState", {}).get("metadata", {})
                                if aid == target_email_or_id or meta.get("email") == target_email_or_id:
                                    target_id = aid
                                    break
                        except Exception:
                            pass

                    if not target_id:
                        for acc in cfg.get("accounts", []):
                            if acc.get("id") == target_email_or_id or acc.get("email") == target_email_or_id:
                                target_id = acc.get("id")
                                break

                    if target_id:
                        rows = cfg.get("commonAuthPool", {}).get("rows", {})
                        current_cand = True
                        for acc in cfg.get("accounts", []):
                            if acc.get("id") == target_id:
                                current_cand = acc.get("candidate", True)
                                acc["enabled"] = enabled
                                break

                        if target_id in rows:
                            rows[target_id]["enabled"] = enabled
                            rows[target_id]["usable"] = enabled and current_cand

                        _atomic_write_json(cfg_file, cfg)

                        if state_file.exists():
                            try:
                                state = json.loads(state_file.read_text(encoding="utf-8-sig"))
                                if target_id in state.get("accounts", {}):
                                    meta = state["accounts"][target_id].setdefault("commonAuthProviderState", {}).setdefault("metadata", {})
                                    meta["enabled"] = enabled
                                    _atomic_write_json(state_file, state)
                            except Exception:
                                _atomic_write_bytes(cfg_file, orig_cfg_bytes)
                                raise
                        changed = True
                except Exception as e:
                    print(f"Error updating enabled in generation config: {e}")

        legacy_file = config_dir / "antigravity-accounts.json"
        if legacy_file.exists():
            try:
                legacy_data = json.loads(legacy_file.read_text(encoding="utf-8-sig"))
                legacy_changed = False
                for acc in legacy_data.get("accounts", []):
                    if acc.get("id") == target_email_or_id or acc.get("email") == target_email_or_id:
                        acc["enabled"] = enabled
                        legacy_changed = True
                if legacy_changed:
                    _atomic_write_json(legacy_file, legacy_data)
                    changed = True
            except Exception:
                pass

        return changed

def export_google_accounts() -> list[dict]:
    config_dir = get_opencode_config_dir()
    gen_dirs = ordered_generation_dirs(config_dir)
    accounts = []
    if gen_dirs:
        gen_dir = gen_dirs[0]
        cfg_file = gen_dir / "config.json"
        state_file = gen_dir / "state.json"
        if cfg_file.exists() and state_file.exists():
            try:
                cfg = json.loads(cfg_file.read_text(encoding="utf-8-sig")) or {}
                state = json.loads(state_file.read_text(encoding="utf-8-sig")) or {}
                state_accounts = state.get("accounts") or {}
                for idx, acc in enumerate(cfg.get("accounts") or [], start=1):
                    if not isinstance(acc, dict):
                        continue
                    aid = acc.get("id")
                    st = state_accounts.get(aid) or {}
                    meta = (st.get("commonAuthProviderState") or {}).get("metadata") or {}
                    email = meta.get("email") or f"Account {idx}"
                    refresh = st.get("refresh")
                    if refresh:
                        accounts.append({
                            "id": aid,
                            "email": email,
                            "refreshToken": refresh,
                            "accessToken": st.get("access", ""),
                            "expires": st.get("expires", 0),
                            "projectId": meta.get("projectId", "aicode-consumers"),
                            "addedAt": meta.get("addedAt") or acc.get("addedAt"),
                            "label": meta.get("label", ""),
                            "enabled": meta.get("enabled", True),
                            "fingerprint": meta.get("fingerprint"),
                        })
            except Exception as e:
                print(f"Error reading generation accounts: {e}")

    legacy_file = config_dir / "antigravity-accounts.json"
    if not accounts and legacy_file.exists():
        try:
            data = json.loads(legacy_file.read_text(encoding="utf-8-sig")) or {}
            accounts = data.get("accounts") or []
        except Exception:
            pass

    return accounts

def get_active_google_health_account():
    """Match the stored active row by ID; exported rows can omit incomplete accounts."""
    accounts = export_google_accounts()
    index = get_active_google_account_index()
    generations = ordered_generation_dirs(get_opencode_config_dir())
    if generations and (generations[0] / "config.json").exists():
        try:
            config = json.loads((generations[0] / "config.json").read_text(encoding="utf-8-sig")) or {}
            rows = config.get("accounts") or []
        except Exception:
            return None
        if 0 <= index < len(rows):
            active_id = rows[index].get("id")
            return next((account for account in accounts if account.get("id") == active_id), None)
        return None
    return accounts[index] if 0 <= index < len(accounts) else None


def delete_google_account(target_email_or_id: str) -> bool:
    with _google_store_lock:
        config_dir = get_opencode_config_dir()
        gen_dirs = ordered_generation_dirs(config_dir)
        deleted = False

        if gen_dirs:
            gen_dir = gen_dirs[0]
            cfg_file = gen_dir / "config.json"
            state_file = gen_dir / "state.json"
            if cfg_file.exists() and state_file.exists():
                try:
                    orig_cfg_bytes = cfg_file.read_bytes()
                    cfg = json.loads(orig_cfg_bytes.decode("utf-8-sig")) or {}
                    state = json.loads(state_file.read_text(encoding="utf-8-sig")) or {}
                    state_accounts = state.get("accounts") or {}
                    target_id = None
                    for acc in cfg.get("accounts") or []:
                        aid = acc.get("id")
                        st = state_accounts.get(aid) or {}
                        email = ((st.get("commonAuthProviderState") or {}).get("metadata") or {}).get("email")
                        if aid == target_email_or_id or email == target_email_or_id:
                            target_id = aid
                            break

                    if target_id:
                        cfg["accounts"] = [a for a in cfg.get("accounts", []) if a.get("id") != target_id]
                        pool = cfg.setdefault("commonAuthPool", {})
                        rows = pool.setdefault("rows", {})
                        old_entry = rows.pop(target_id, None)
                        old_epoch = old_entry.get("credentialEpoch") if isinstance(old_entry, dict) else None
                        if not isinstance(old_epoch, int) or isinstance(old_epoch, bool) or old_epoch < 1:
                            old_epoch = 1
                        retired = pool.get("retiredEpochs")
                        if not isinstance(retired, dict):
                            retired = {}
                        prev_retired = retired.get(target_id)
                        if isinstance(prev_retired, int) and not isinstance(prev_retired, bool) and prev_retired >= 1:
                            retired[target_id] = max(prev_retired, old_epoch)
                        else:
                            retired[target_id] = old_epoch
                        pool["retiredEpochs"] = retired

                        routing = cfg.get("antigravityRouting") or {}
                        active_row = routing.get("activeRow")
                        active_row_id = active_row.get("id") if isinstance(active_row, dict) else None
                        remaining = cfg.get("accounts", [])
                        if active_row_id == target_id:
                            if remaining:
                                new_id = remaining[0]["id"]
                                new_ref = _google_row_ref(cfg, new_id)
                                routing["activeIndex"] = 0
                                routing["activeIndexByFamily"] = {"claude": 0, "gemini": 0}
                                routing["activeRow"] = dict(new_ref)
                                routing["activeRowByFamily"] = {
                                    "claude": dict(new_ref),
                                    "gemini": dict(new_ref),
                                }
                            else:
                                routing["activeIndex"] = 0
                                routing["activeRow"] = None
                                routing["activeIndexByFamily"] = {"claude": 0, "gemini": 0}
                                routing["activeRowByFamily"] = {"claude": None, "gemini": None}
                        else:
                            for i, a in enumerate(remaining):
                                if a.get("id") == active_row_id:
                                    routing["activeIndex"] = i
                                    routing["activeIndexByFamily"] = {"claude": i, "gemini": i}
                                    break
                            row_by_family = routing.get("activeRowByFamily")
                            if isinstance(row_by_family, dict):
                                for fam in ("claude", "gemini"):
                                    fam_row = row_by_family.get(fam)
                                    if isinstance(fam_row, dict) and fam_row.get("id") == target_id:
                                        if remaining:
                                            row_by_family[fam] = _google_row_ref(cfg, remaining[0]["id"])
                                        else:
                                            row_by_family[fam] = None
                        cfg["antigravityRouting"] = routing
                        _atomic_write_json(cfg_file, cfg)

                        try:
                            if "accounts" in state:
                                state["accounts"].pop(target_id, None)
                            _atomic_write_json(state_file, state)
                        except Exception:
                            _atomic_write_bytes(cfg_file, orig_cfg_bytes)
                            raise
                        deleted = True
                except Exception as e:
                    print(f"Error deleting account: {e}")

        legacy_file = config_dir / "antigravity-accounts.json"
        if legacy_file.exists():
            try:
                legacy_data = json.loads(legacy_file.read_text(encoding="utf-8-sig")) or {}
                old_accounts = legacy_data.get("accounts") or []
                new_accounts = [
                    a for a in old_accounts
                    if a.get("email") != target_email_or_id and a.get("id") != target_email_or_id
                ]
                if len(new_accounts) != len(old_accounts):
                    legacy_data["accounts"] = new_accounts
                    cur_idx = legacy_data.get("activeIndex", 0)
                    if cur_idx >= len(new_accounts):
                        legacy_data["activeIndex"] = max(0, len(new_accounts) - 1)
                    _atomic_write_json(legacy_file, legacy_data)
                    deleted = True
            except Exception:
                pass

        return deleted

def enrich_google_accounts_with_generation_store(accounts: list[dict]) -> list[dict]:
    config_dir = get_opencode_config_dir()
    gen_dirs = ordered_generation_dirs(config_dir)
    if not gen_dirs:
        return accounts

    cfg_p = gen_dirs[0] / "config.json"
    state_p = gen_dirs[0] / "state.json"
    if not (cfg_p.exists() and state_p.exists()):
        return accounts

    try:
        cfg = json.loads(cfg_p.read_text(encoding="utf-8-sig")) or {}
        state = json.loads(state_p.read_text(encoding="utf-8-sig")) or {}
    except Exception:
        return accounts

    disk_accounts = []
    pool_rows = (cfg.get("commonAuthPool") or {}).get("rows") or {}
    state_accounts = state.get("accounts") or {}
    for idx, acc in enumerate(cfg.get("accounts") or [], start=1):
        if not isinstance(acc, dict):
            continue
        aid = acc.get("id")
        row = pool_rows.get(aid) or {}
        st = state_accounts.get(aid) or {}
        meta = (st.get("commonAuthProviderState") or {}).get("metadata") or {}
        email = meta.get("email") or f"Account {idx}"
        added_at = meta.get("addedAt") or acc.get("addedAt")
        cached = (row.get("quota") or {}).get("cachedQuota") or {}

        groups = []
        for g_name in ["gemini", "non-gemini"]:
            g_data = cached.get(g_name)
            if not g_data or not isinstance(g_data, dict):
                continue
            rem_frac = g_data.get("remainingFraction")
            rem_pct = round(rem_frac * 100, 1) if rem_frac is not None else None
            windows = []
            for w in g_data.get("windows", []):
                w_frac = w.get("remainingFraction")
                windows.append({
                    "window": w.get("window"),
                    "remainingPercent": round(w_frac * 100, 1) if w_frac is not None else None,
                    "resetTime": w.get("resetTime"),
                })
            groups.append({
                "name": g_name,
                "remainingPercent": rem_pct,
                "resetTime": g_data.get("resetTime"),
                "windows": windows,
            })

        is_enabled = row.get("enabled", True)
        is_candidate = acc.get("candidate", row.get("usable", is_enabled))
        disk_accounts.append({
            "index": idx,
            "id": aid,
            "email": email,
            "addedAt": added_at,
            "enabled": is_enabled,
            "status": "ok" if is_enabled else "disabled",
            "candidate": is_candidate,
            "groups": groups,
        })

    if not accounts:
        return disk_accounts

    for idx, acc in enumerate(accounts):
        account_id = acc.get("id") or acc.get("accountId")
        email = (acc.get("email") or "").strip().lower()
        disk_acc = next(
            (
                item for item in disk_accounts
                if (account_id and item.get("id") == account_id)
                or (email and item.get("email", "").strip().lower() == email)
            ),
            None,
        )
        # Older CLI output omits stable identifiers; only then use its ordering.
        if disk_acc is None and not account_id and not email and idx < len(disk_accounts):
            disk_acc = disk_accounts[idx]
        if disk_acc:
            acc["enabled"] = disk_acc.get("enabled", True)
            acc["candidate"] = disk_acc.get("candidate", True)
            acc["status"] = disk_acc.get("status", "ok")
            if not acc.get("email") or acc.get("email", "").startswith("Account "):
                acc["email"] = disk_acc["email"]
            if not acc.get("addedAt"):
                acc["addedAt"] = disk_acc.get("addedAt")
            if not acc.get("id"):
                acc["id"] = disk_acc.get("id")

            if not acc.get("groups"):
                acc["groups"] = disk_acc.get("groups", [])
            else:
                for g in acc.get("groups", []):
                    g_name = g.get("name")
                    if not g.get("windows"):
                        matching_dg = next((dg for dg in disk_acc.get("groups", []) if dg.get("name") == g_name), None)
                        if matching_dg and matching_dg.get("windows"):
                            g["windows"] = matching_dg["windows"]

    return accounts

def repair_legacy_google_account_file(config_dir=None) -> str | None:
    """Normalize known legacy credential metadata before the plugin migration."""
    config_dir = Path(config_dir) if config_dir else get_opencode_config_dir()
    legacy_file = config_dir / "antigravity-accounts.json"
    if not legacy_file.exists():
        return None
    try:
        data = json.loads(legacy_file.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        return f"Не удалось прочитать файл аккаунтов Google: {exc}"
    if not isinstance(data, dict) or not isinstance(data.get("accounts"), list):
        return "Файл аккаунтов Google имеет неизвестный формат; он оставлен без изменений."

    changed = False
    for index, account in enumerate(data["accounts"]):
        if not isinstance(account, dict):
            return f"Запись Google-аккаунта #{index + 1} имеет неверный формат; файл оставлен без изменений."

        # Older Hub exports wrapped provider fields in `metadata`. The current
        # migration expects a flat legacy row and rejects credential material
        # inside provider metadata. Preserve non-credential fields, but never
        # copy access tokens into the new metadata shape.
        nested = account.get("metadata")
        if nested is not None:
            if not isinstance(nested, dict):
                return f"Metadata записи Google-аккаунта #{index + 1} имеет неверный формат; файл оставлен без изменений."
            nested_refresh = nested.get("refreshToken") or nested.get("refresh")
            if not account.get("refreshToken") and isinstance(nested_refresh, str) and nested_refresh:
                account["refreshToken"] = nested_refresh
            for key, value in nested.items():
                if key not in {"refreshToken", "refresh", "accessToken", "access", "expires", "apiKey"}:
                    account.setdefault(key, value)
            del account["metadata"]
            changed = True

        if not account.get("refreshToken"):
            alias = account.get("refresh")
            if isinstance(alias, str) and alias:
                account["refreshToken"] = alias
                changed = True
        if not isinstance(account.get("refreshToken"), str) or not account["refreshToken"]:
            return f"У записи Google-аккаунта #{index + 1} отсутствует refresh token; файл оставлен без изменений."

        # Access tokens are short-lived. The plugin refreshes them using the
        # refresh token and accepts credentials only in its credential field.
        for key in ("accessToken", "access", "refresh", "expires", "apiKey"):
            if key in account:
                del account[key]
                changed = True

        added_at = account.get("addedAt")
        if not isinstance(added_at, (int, float)) or isinstance(added_at, bool) or not math.isfinite(added_at):
            account["addedAt"] = int(time.time() * 1000)
            changed = True
        last_used = account.get("lastUsed")
        if not isinstance(last_used, (int, float)) or isinstance(last_used, bool) or not math.isfinite(last_used):
            account["lastUsed"] = 0
            changed = True
    if not changed:
        return None

    backup = legacy_file.with_name(
        legacy_file.name + ".pre-repair-" + datetime.datetime.now().strftime("%Y%m%d-%H%M%S-%f") + ".bak"
    )
    temporary = legacy_file.with_name(legacy_file.name + "." + secrets.token_hex(6) + ".tmp")
    try:
        shutil.copy2(legacy_file, backup)
        temporary.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        os.replace(temporary, legacy_file)
    except OSError as exc:
        temporary.unlink(missing_ok=True)
        return f"Не удалось исправить файл аккаунтов Google: {exc}"
    return None


def compute_google_credential_digest(refresh_token: str) -> str:
    secret = f"oauth\x00{refresh_token}"
    return hashlib.sha256(f"credential-stamp\x00{secret}".encode("utf-8")).hexdigest()


def compute_google_dispatch_digest(access_token: str | None, refresh_token: str, expires: int | float | None) -> str:
    parts = [
        "oauth",
        access_token if isinstance(access_token, str) and access_token else None,
        refresh_token,
        int(expires) if isinstance(expires, (int, float)) and not isinstance(expires, bool) and math.isfinite(expires) and expires > 0 else None
    ]
    parts_json = json.dumps(parts, separators=(',', ':'))
    return hashlib.sha256(f"credential-dispatch\x00{parts_json}".encode("utf-8")).hexdigest()


def _generation_dirs(config_dir: Path) -> list[Path]:
    root = config_dir.resolve()
    dirs = []
    for entry in config_dir.glob("*.generation"):
        try:
            resolved = entry.resolve()
            if resolved.parent == root and resolved.name == entry.name and resolved.is_dir():
                dirs.append(resolved)
        except (OSError, RuntimeError):
            continue
    return dirs


def get_active_generation_dir(config_dir: Path) -> Path | None:
    dirs = _generation_dirs(config_dir)
    pointer_file = config_dir / "antigravity-accounts.json.store.pointer.json"
    if pointer_file.exists():
        ptr = None
        try:
            ptr = json.loads(pointer_file.read_text(encoding="utf-8-sig"))
            # Plugin 3.1.x moves the canonical store into its own state folder
            # and leaves a schema-2 forward pointer here. Hub account readers
            # must follow it before `directoryBasename`: that basename still
            # names the stale pre-migration snapshot under the config folder.
            relocated = ptr.get("relocatedTo") if isinstance(ptr, dict) else None
            if isinstance(relocated, dict):
                rid = relocated.get("id")
                legacy = relocated.get("legacyPath")
                if isinstance(legacy, str) and legacy:
                    legacy_target = Path(legacy).expanduser()
                    parent = legacy_target.parent
                    sub_pointer = parent / f"{legacy_target.name}.store.pointer.json"
                    if sub_pointer.exists():
                        try:
                            sub_ptr = json.loads(sub_pointer.read_text(encoding="utf-8-sig"))
                            sub_dir = sub_ptr.get("directoryBasename") if isinstance(sub_ptr, dict) else None
                            if isinstance(sub_dir, str) and sub_dir:
                                sub_candidate = parent / sub_dir
                                if sub_candidate.is_dir():
                                    return sub_candidate.resolve()
                        except Exception:
                            pass
                    if isinstance(rid, str) and rid:
                        expected = parent / f"antigravity-accounts.json.store.{rid}.generation"
                        if expected.is_dir():
                            return expected.resolve()
                        for entry in parent.glob("*.generation"):
                            if rid in entry.name and entry.is_dir():
                                return entry.resolve()
        except Exception:
            pass
        dirname = ptr.get("directoryBasename") if isinstance(ptr, dict) else None
        if isinstance(dirname, str):
            selected = next((path for path in dirs if path.name == dirname), None)
            if selected is not None:
                return selected
    def _safe_mtime(p: Path) -> float:
        try:
            return p.stat().st_mtime
        except OSError:
            return 0.0
    gen_dirs = sorted(dirs, key=_safe_mtime, reverse=True)
    return gen_dirs[0] if gen_dirs else None


def has_relocated_google_store(config_dir: Path | None = None) -> bool:
    base = Path(config_dir) if config_dir else get_opencode_config_dir()
    pointer_file = base / "antigravity-accounts.json.store.pointer.json"
    if not pointer_file.exists():
        return False
    try:
        ptr = json.loads(pointer_file.read_text(encoding="utf-8-sig"))
    except Exception:
        return False
    if not isinstance(ptr, dict):
        return False
    return ptr.get("schemaVersion") == 2 or isinstance(ptr.get("relocatedTo"), dict)


def import_google_accounts(accounts_list: list[dict]) -> int:
    """
    Imports Google accounts into the active generation store or legacy store.
    Generates proper credential digest & dispatch stamps and fixes routing.
    """
    if not accounts_list:
        return 0

    with _google_store_lock:
        config_dir = get_opencode_config_dir()
        config_dir.mkdir(parents=True, exist_ok=True)
        gen_dir = get_active_generation_dir(config_dir)

        count = 0
        now_ms = int(time.time() * 1000)

        if gen_dir:
            cfg_file = gen_dir / "config.json"
            state_file = gen_dir / "state.json"
            if not (cfg_file.exists() and state_file.exists()):
                # Partially broken generation store: never fall back to legacy 3.0.0.
                return 0
            try:
                orig_cfg_bytes = cfg_file.read_bytes()
                cfg = json.loads(orig_cfg_bytes.decode("utf-8-sig"))
                state = json.loads(state_file.read_text(encoding="utf-8-sig"))
                if not isinstance(cfg, dict) or not isinstance(state, dict):
                    return 0
                cfg_accounts = cfg.setdefault("accounts", [])
                pool = cfg.setdefault("commonAuthPool", {})
                pool["schemaVersion"] = 1
                pool_rows = pool.setdefault("rows", {})
                state_accounts = state.setdefault("accounts", {})
                state["version"] = 1

                for item in accounts_list:
                    if not isinstance(item, dict):
                        continue
                    nested = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
                    email = item.get("email") or nested.get("email")
                    refresh_token = item.get("refreshToken") or item.get("refresh") or nested.get("refreshToken") or nested.get("refresh")
                    if not email or not refresh_token:
                        continue

                    project_id = item.get("projectId") or nested.get("projectId") or "aicode-consumers"
                    added_at = item.get("addedAt") or nested.get("addedAt")
                    if not isinstance(added_at, (int, float)) or isinstance(added_at, bool) or not math.isfinite(added_at) or added_at <= 0:
                        added_at = now_ms
                    label = item.get("label") or nested.get("label") or email.split("@")[0]

                    raw_access = item.get("accessToken")
                    if raw_access is None:
                        raw_access = item.get("access")
                    access_token = raw_access if isinstance(raw_access, str) and raw_access else None

                    raw_expires = item.get("expires")
                    expires = (
                        int(raw_expires)
                        if isinstance(raw_expires, (int, float)) and not isinstance(raw_expires, bool)
                        and math.isfinite(raw_expires) and raw_expires > 0
                        else None
                    )

                    raw_enabled = item.get("enabled")
                    if raw_enabled is None:
                        raw_enabled = nested.get("enabled")
                    enabled = True if raw_enabled is None else bool(raw_enabled)

                    raw_account_id = item.get("accountId") or nested.get("accountId")
                    item_identity = raw_account_id.strip() if isinstance(raw_account_id, str) and raw_account_id.strip() else None

                    digest = compute_google_credential_digest(refresh_token)
                    dispatch = compute_google_dispatch_digest(access_token, refresh_token, expires)

                    # Look for existing account by email or id
                    aid = None
                    target_id = item.get("id")
                    for existing_aid, existing_st in state_accounts.items():
                        st_email = (existing_st.get("commonAuthProviderState") or {}).get("metadata", {}).get("email")
                        if isinstance(st_email, str) and st_email.lower() == email.lower():
                            aid = existing_aid
                            break
                        if target_id and existing_aid == target_id:
                            aid = existing_aid
                            break
                    if aid is None and target_id:
                        for existing_acc in cfg_accounts:
                            if isinstance(existing_acc, dict) and existing_acc.get("id") == target_id:
                                aid = target_id
                                break

                    if aid is None:
                        aid = target_id or str(uuid.uuid4())

                    existing_roster = next((a for a in cfg_accounts if isinstance(a, dict) and a.get("id") == aid), None)
                    existing_st = state_accounts.get(aid, {})
                    existing_stamp = existing_st.get("commonAuthPool") if isinstance(existing_st.get("commonAuthPool"), dict) else {}
                    existing_binding = existing_stamp.get("binding") if isinstance(existing_stamp.get("binding"), dict) else {}

                    identity = item_identity
                    if not identity and isinstance(existing_roster, dict):
                        roster_acct = existing_roster.get("accountId")
                        if isinstance(roster_acct, str) and roster_acct.strip():
                            identity = roster_acct.strip()
                    if not identity and isinstance(existing_binding.get("identity"), str) and existing_binding["identity"].strip():
                        identity = existing_binding["identity"].strip()

                    if isinstance(existing_roster, dict):
                        existing_roster["type"] = existing_roster.get("type") or "oauth"
                        existing_roster.setdefault("addedAt", int(added_at))
                        existing_roster["enabled"] = enabled
                        if identity:
                            existing_roster["accountId"] = identity
                    else:
                        new_roster = {
                            "id": aid,
                            "type": "oauth",
                            "addedAt": int(added_at),
                            "enabled": enabled,
                        }
                        if identity:
                            new_roster["accountId"] = identity
                        cfg_accounts.append(new_roster)

                    existing_row = pool_rows.get(aid) if isinstance(pool_rows.get(aid), dict) else None
                    prev_epoch = existing_row.get("credentialEpoch") if existing_row else None
                    if not isinstance(prev_epoch, int) or isinstance(prev_epoch, bool) or prev_epoch < 1:
                        prev_epoch = None
                    retired_epochs = pool.get("retiredEpochs")
                    if not isinstance(retired_epochs, dict):
                        retired_epochs = {}
                    prev_retired = retired_epochs.get(aid)
                    if not isinstance(prev_retired, int) or isinstance(prev_retired, bool) or prev_retired < 1:
                        prev_retired = 0

                    prev_digest = existing_stamp.get("digest")
                    prev_refresh = existing_st.get("refresh")
                    credential_changed = bool(
                        existing_st and (
                            (isinstance(prev_digest, str) and prev_digest != digest)
                            or (isinstance(prev_refresh, str) and prev_refresh != refresh_token)
                        )
                    )
                    if prev_epoch is not None:
                        if credential_changed:
                            retired_epoch = max(prev_retired, prev_epoch)
                            retired_epochs[aid] = retired_epoch
                            pool["retiredEpochs"] = retired_epochs
                            epoch = retired_epoch + 1
                        else:
                            epoch = prev_epoch
                    else:
                        epoch = prev_retired + 1 if prev_retired else 1

                    row_entry = {
                        "credentialEpoch": epoch,
                        "needsFirstReading": False,
                        "enabled": enabled,
                    }
                    if existing_row and not credential_changed and "quota" in existing_row:
                        row_entry["quota"] = existing_row["quota"]
                    pool_rows[aid] = row_entry

                    existing_meta = existing_st.get("commonAuthProviderState", {}).get("metadata", {})
                    fingerprint = item.get("fingerprint") or existing_meta.get("fingerprint") or {
                        "deviceId": str(uuid.uuid4()),
                        "sessionToken": secrets.token_hex(16),
                        "userAgent": "antigravity/cli/1.1.24 (aidev_client; os_type=windows; arch=amd64; cl=974782877; auth_method=consumer)",
                        "apiClient": "antigravity-cli",
                        "clientMetadata": {
                            "ideType": "ANTIGRAVITY",
                            "platform": "WINDOWS",
                            "pluginType": "GEMINI"
                        },
                        "createdAt": now_ms
                    }

                    new_binding = {
                        k: v for k, v in existing_binding.items()
                        if k in ("identity", "baseURL", "authHeader")
                    }
                    if identity:
                        new_binding["identity"] = identity

                    pool_stamp = {
                        "credentialEpoch": epoch,
                        "digest": digest,
                        "dispatch": dispatch,
                        "binding": new_binding,
                    }
                    if not credential_changed and isinstance(existing_stamp.get("providerState"), str) and existing_stamp["providerState"]:
                        pool_stamp["providerState"] = existing_stamp["providerState"]

                    new_state = {
                        "commonAuthProviderState": {
                            "schemaVersion": 1,
                            "metadata": {
                                "addedAt": int(added_at),
                                "lastUsed": now_ms,
                                "enabled": enabled,
                                "label": label,
                                "email": email,
                                "projectId": project_id,
                                "fingerprint": fingerprint,
                                "fingerprintHistory": existing_meta.get("fingerprintHistory", []),
                                "managedProjectId": project_id,
                                "dailyRequestCounts": existing_meta.get("dailyRequestCounts", {
                                    "date": datetime.date.today().isoformat(),
                                    "claude": 0,
                                    "gemini": 0
                                }),
                                "rateLimitResetTimes": existing_meta.get("rateLimitResetTimes", {})
                            }
                        },
                        "commonAuthPool": pool_stamp,
                        "refresh": refresh_token,
                        "lastRefreshedAt": now_ms
                    }
                    if access_token is not None:
                        new_state["access"] = access_token
                    if expires is not None:
                        new_state["expires"] = expires

                    state_accounts[aid] = new_state
                    count += 1

                if cfg_accounts:
                    routing = cfg.setdefault("antigravityRouting", {})
                    routing["schemaVersion"] = 1
                    active_idx = routing.get("activeIndex", 0)
                    if not (0 <= active_idx < len(cfg_accounts)):
                        active_idx = 0
                    routing["activeIndex"] = active_idx
                    routing["activeIndexByFamily"] = {"claude": active_idx, "gemini": active_idx}
                    active_row_id = cfg_accounts[active_idx]["id"]
                    active_ref = _google_row_ref(cfg, active_row_id)
                    routing["activeRow"] = dict(active_ref)
                    routing["activeRowByFamily"] = {
                        "claude": dict(active_ref),
                        "gemini": dict(active_ref),
                    }

                _atomic_write_json(cfg_file, cfg)
                try:
                    _atomic_write_json(state_file, state)
                except Exception:
                    _atomic_write_bytes(cfg_file, orig_cfg_bytes)
                    raise

                # IMPORTANT: ensure legacy file does not exist to avoid "legacy source was recreated after activation"
                legacy_file = config_dir / "antigravity-accounts.json"
                if legacy_file.exists():
                    try:
                        legacy_file.unlink(missing_ok=True)
                    except Exception:
                        pass

                return count
            except Exception as e:
                print(f"Error importing into generation store: {e}")
                return 0

        # Refuse to write incompatible 3.0.0 legacy fallback if a 3.1.x/generation store is expected or broken.
        legacy_file = config_dir / "antigravity-accounts.json"
        if _expects_v2_google_store(config_dir) and not legacy_file.exists():
            return 0
        if (config_dir / "antigravity-accounts.json.store.pointer.json").exists() or has_relocated_google_store(config_dir):
            return 0

        # Fallback when no generation store directory exists (3.0.0 legacy mode)
        legacy_data = {"version": 4, "activeIndex": 0, "accounts": []}
        if legacy_file.exists():
            try:
                legacy_data = json.loads(legacy_file.read_text(encoding="utf-8-sig"))
                if not isinstance(legacy_data, dict) or not isinstance(legacy_data.get("accounts", []), list):
                    return 0
            except (OSError, ValueError):
                return 0
        old_accs = legacy_data.setdefault("accounts", [])
        for item in accounts_list:
            if not isinstance(item, dict):
                continue
            nested = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
            email = item.get("email") or nested.get("email")
            refresh_token = item.get("refreshToken") or item.get("refresh") or nested.get("refreshToken") or nested.get("refresh")
            if not email or not refresh_token:
                continue
            existing = next((a for a in old_accs if a.get("email", "").lower() == email.lower()), None)
            if existing:
                existing["refreshToken"] = refresh_token
                existing["projectId"] = item.get("projectId") or nested.get("projectId") or existing.get("projectId", "aicode-consumers")
            else:
                old_accs.append({
                    "email": email,
                    "refreshToken": refresh_token,
                    "projectId": item.get("projectId") or nested.get("projectId") or "aicode-consumers",
                    "addedAt": item.get("addedAt") or now_ms,
                    "lastUsed": 0
                })
            count += 1

        _atomic_write_json(legacy_file, legacy_data)
        try:
            node_exe = get_node_executable()
            cli_js = get_cli_js()
            if node_exe and cli_js and Path(node_exe).exists() and Path(cli_js).exists():
                run_silent_cmd([node_exe, cli_js, "migrate", "--offline", "--yes"], timeout=30)
        except Exception:
            pass

        return count


def import_google_account(account_dict: dict) -> bool:
    return import_google_accounts([account_dict]) > 0


if __name__ == "__main__":
    sys.modules["antigravity_manager"] = sys.modules[__name__]
    if getattr(sys, "frozen", False):
        bundle = Path(sys._MEIPASS)
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(bundle / "browsers")
        if len(sys.argv) == 3 and sys.argv[1] == "--restart-after":
            from hub_restart import relaunch_packaged
            sys.exit(relaunch_packaged(sys.argv[2]))
        if len(sys.argv) == 3 and sys.argv[1] == "--package-self-test":
            os.environ["ANTIGRAVITY_HUB_DATA_DIR"] = str(Path(sys.argv[2]).with_suffix(".data"))
            from package_smoke import check_bundle
            sys.exit(check_bundle(bundle, Path(sys.argv[2])))
    if not acquire_single_instance():
        sys.exit(0)
    import hub_paths
    import hub_logging

    hub_logging.configure(hub_paths.LOG_DIR)
    hub_logging.log.info("Hub startup (packaged=%s)", bool(getattr(sys, "frozen", False)))

    def log_thread_failure(args):
        hub_logging.failed("Hub background thread", args.exc_value)
        threading.__excepthook__(args)

    threading.excepthook = log_thread_failure
    try:
        set_windows_taskbar_identity()
        import webview_backend
        webview_backend.run_webview_app()
    except Exception as exc:
        hub_logging.failed("Hub startup", exc)
        raise
