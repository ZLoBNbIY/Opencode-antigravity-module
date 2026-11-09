"""Connection to a locally hosted OpenAI-compatible Muse AI gateway."""
import json
import os
import secrets
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import zipfile
from io import BytesIO
from pathlib import Path
from urllib.parse import quote, urlparse

import deepseek_storage
import deepseek_config
import openai_manager

CONFIG_DIR = Path.home() / ".config" / "opencode"
SECRET_FILE = Path.home() / ".local" / "share" / "antigravity-hub" / "museai.json"
SECRET_PURPOSE = "museai-gateway-credentials"
DEFAULT_BASE_URL = "http://127.0.0.1:18610/v1"
PROVIDER_ID = "museai"
MUSEAI_COOKIE_ALLOWLIST = frozenset({
    "hatch_sess", "hatch_gw", "hatch_native_auth_device", "hatch_vml", "datr",
})
APP_DATA = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "AntigravityHub"
GATEWAY_DIR = APP_DATA / "museai-gateway"
GATEWAY_DATA = APP_DATA / "museai-data"
_job_lock = threading.RLock()
_job_state = {"running": False, "stage": "idle", "message": "", "error": ""}
_gateway_process = None
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def load_config():
    try:
        data = json.loads(SECRET_FILE.read_text(encoding="utf-8"))
        return {"api_key": "", "base_url": DEFAULT_BASE_URL, "connected": False, "models": [],
                **deepseek_storage.unprotect_secret(data, SECRET_PURPOSE)}
    except Exception:
        return {"api_key": "", "base_url": DEFAULT_BASE_URL, "connected": False, "models": []}


def save_config(data):
    merged = load_config()
    merged.update(data)
    record = deepseek_storage.protect_secret(SECRET_PURPOSE, merged)
    deepseek_storage.atomic_write(SECRET_FILE, json.dumps(record))


def fetch_models(base_url, api_key, timeout=15):
    base_url = str(base_url or "").strip().rstrip("/")
    parsed = urlparse(base_url)
    local_hosts = {"localhost", "127.0.0.1", "::1"}
    if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Укажите корректный HTTP(S) URL Muse AI gateway без логина и пароля в URL")
    if parsed.scheme == "http" and parsed.hostname.lower() not in local_hosts:
        raise ValueError("Незашифрованный HTTP разрешён только для localhost; удалённый gateway должен использовать HTTPS")
    if not api_key:
        raise ValueError("Укажите API-ключ шлюза Muse AI")
    req = urllib.request.Request(f"{base_url}/models", headers={
        "Authorization": f"Bearer {api_key}", "Accept": "application/json",
        "User-Agent": "Antigravity-Hub-MuseAI",
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            raise ValueError("Muse AI gateway отклонил API-ключ (401)") from None
        raise ValueError(f"Muse AI gateway вернул HTTP {exc.code}") from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise ValueError("Не удалось подключиться к Muse AI gateway. Убедитесь, что он запущен и URL верен.") from None
    items = payload.get("data", []) if isinstance(payload, dict) else []
    models = []
    for item in items:
        mid = item.get("id") if isinstance(item, dict) else None
        if isinstance(mid, str) and mid and len(mid) <= 200:
            models.append({"id": mid, "name": item.get("name") or mid})
    if not models:
        raise ValueError("Каталог /models не вернул модели")
    return models


def sync_credential(api_key):
    cli = openai_manager.find_opencode_cli()
    if not cli:
        raise ValueError("Не найден OpenCode CLI для сохранения credentials")
    records = [{"id":"cred_museai_hub", "integrationID":PROVIDER_ID,
                "label":"Muse AI (Antigravity Hub)", "active":True,
                "value":{"type":"key", "key":api_key}}]
    result = subprocess.run([cli, "auth", "import"], input=json.dumps(records),
                            capture_output=True, text=True, timeout=15)
    if result.returncode:
        raise ValueError("OpenCode не принял ключ Muse AI")


def configure_opencode(base_url, models, config_dir=None):
    path = deepseek_config.config_path(Path(config_dir) if config_dir else CONFIG_DIR)
    original = path.read_text(encoding="utf-8-sig") if path.exists() else "{}\n"
    data = deepseek_config.parse_config(original)
    providers = data.get("provider", {})
    if not isinstance(providers, dict):
        raise ValueError("Поле provider в конфигурации OpenCode должно быть объектом")
    models_cfg = {item["id"]: {"name": item["name"], "limit":{"context":128000,"output":8192}}
                  for item in models}
    updated = deepseek_config.set_property(original, ("provider", PROVIDER_ID), {
        "npm":"@ai-sdk/openai-compatible", "name":"Muse AI",
        "options":{"baseURL":base_url.rstrip("/")}, "models":models_cfg,
    })
    if "$schema" not in data:
        updated = deepseek_config.set_property(updated, ("$schema",), "https://opencode.ai/config.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    deepseek_storage.atomic_write(path, updated)


def connect(base_url, api_key, selected_ids):
    cfg = load_config()
    api_key = (api_key or cfg.get("api_key") or "").strip()
    base_url = (base_url or DEFAULT_BASE_URL).strip().rstrip("/")
    models = fetch_models(base_url, api_key)
    selected = set(selected_ids or [])
    chosen = [model for model in models if model["id"] in selected]
    if not chosen:
        raise ValueError("Выберите хотя бы одну модель")
    sync_credential(api_key)
    configure_opencode(base_url, chosen)
    save_config({"api_key":api_key,"base_url":base_url,"connected":True,
                 "models":models,"enabled_models":[m["id"] for m in chosen]})
    return models


def disconnect():
    cli = openai_manager.find_opencode_cli()
    if not cli:
        raise ValueError("Не найден OpenCode CLI; ключ Hub оставлен без изменений")
    result = subprocess.run([cli, "auth", "logout", PROVIDER_ID], capture_output=True, timeout=15)
    if result.returncode:
        raise ValueError("OpenCode не удалил сохранённые учётные данные; ключ Hub оставлен без изменений")
    path = deepseek_config.config_path(CONFIG_DIR)
    if path.exists():
        original = path.read_text(encoding="utf-8-sig")
        data = deepseek_config.parse_config(original)
        if PROVIDER_ID in (data.get("provider") or {}):
            deepseek_storage.atomic_write(path, deepseek_config.set_property(original, ("provider",),
                {k:v for k,v in data.get("provider", {}).items() if k != PROVIDER_ID}))
    stop_gateway()
    (GATEWAY_DATA / "accounts.json").unlink(missing_ok=True)
    SECRET_FILE.unlink(missing_ok=True)


def _set_job(stage, message, error="", running=True):
    with _job_lock:
        _job_state.update(running=running, stage=stage, message=message, error=error)


def setup_state():
    with _job_lock:
        return dict(_job_state)


def _gateway_keys():
    cfg = load_config()
    api_key = cfg.get("gateway_api_key") or ("muse-" + secrets.token_urlsafe(32))
    admin_key = cfg.get("gateway_admin_key") or ("muse-admin-" + secrets.token_urlsafe(32))
    save_config({"gateway_api_key": api_key, "gateway_admin_key": admin_key})
    return api_key, admin_key


def _install_gateway():
    global _job_state
    GATEWAY_DIR.parent.mkdir(parents=True, exist_ok=True)
    project = GATEWAY_DIR / "museai-main"
    if not (project / "pyproject.toml").exists():
        _set_job("download", "Загружаем исходники Muse AI gateway…")
        url = "https://codeload.github.com/d4ncboz/museai/zip/refs/heads/main"
        with urllib.request.urlopen(url, timeout=60) as response:
            archive = response.read(50 * 1024 * 1024 + 1)
        if len(archive) > 50 * 1024 * 1024:
            raise RuntimeError("Архив gateway неожиданно велик")
        with zipfile.ZipFile(BytesIO(archive)) as bundle:
            root = "museai-main/"
            for item in bundle.infolist():
                if not item.filename.startswith(root):
                    continue
                relative = Path(item.filename[len(root):])
                if not relative.parts or ".." in relative.parts:
                    continue
                target = project / relative
                if item.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(bundle.read(item))
    venv_python = GATEWAY_DIR / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if not venv_python.exists():
        _set_job("venv", "Создаём отдельное Python-окружение…")
        subprocess.run([sys.executable, "-m", "venv", str(GATEWAY_DIR / ".venv")],
                       check=True, capture_output=True, timeout=120, creationflags=_NO_WINDOW)
    marker = GATEWAY_DIR / ".installed"
    if not marker.exists():
        _set_job("dependencies", "Устанавливаем Python-зависимости gateway; окно входа откроется после установки…")
        subprocess.run([str(venv_python), "-m", "pip", "install", "-e", str(project), "playwright>=1.48"],
                       check=True, capture_output=True, timeout=900, creationflags=_NO_WINDOW)
        install_env = os.environ.copy()
        install_env["PLAYWRIGHT_BROWSERS_PATH"] = str(GATEWAY_DIR / "browsers")
        _set_job("browser_install", "Загружаем Chromium; после этого откроется окно Muse.ai для входа…")
        subprocess.run([str(venv_python), "-m", "playwright", "install", "chromium"], env=install_env,
                       check=True, capture_output=True, timeout=900, creationflags=_NO_WINDOW)
        marker.write_text("installed\n", encoding="utf-8")
    return project, venv_python


def _gateway_running(api_key):
    try:
        req = urllib.request.Request("http://127.0.0.1:18610/healthz",
                                     headers={"Authorization": f"Bearer {api_key}"})
        with urllib.request.urlopen(req, timeout=2) as response:
            return response.status == 200
    except Exception:
        return False


def gateway_status():
    cfg = load_config()
    api_key = str(cfg.get("gateway_api_key") or "")
    return bool(api_key and _gateway_running(api_key))


def ensure_gateway_on_startup():
    """Restore a previously configured local gateway without reopening Muse login."""
    cfg = load_config()
    if not (cfg.get("connected") and cfg.get("gateway_api_key") and cfg.get("gateway_admin_key")):
        return False
    if _gateway_running(cfg["gateway_api_key"]):
        return True
    with _job_lock:
        if _job_state["running"]:
            return True
        _job_state.update(running=True, stage="recovering",
                          message="Восстанавливаем локальный Muse AI gateway…", error="")
    threading.Thread(target=_recover_saved_gateway, daemon=True,
                     name="museai-gateway-recovery").start()
    return True


def _recover_saved_gateway():
    try:
        cfg = load_config()
        project, python = _install_gateway()
        _start_gateway(project, python, cfg["gateway_api_key"], cfg["gateway_admin_key"])
        models = fetch_models(DEFAULT_BASE_URL, cfg["gateway_api_key"])
        save_config({"models": models})
        _set_job("done", f"Gateway запущен; моделей доступно: {len(models)}", running=False)
    except Exception as exc:
        _set_job("error", "Не удалось запустить Muse AI gateway",
                 error=str(exc)[:300], running=False)


def _playwright_chromium_path(python):
    env = os.environ.copy()
    env["PLAYWRIGHT_BROWSERS_PATH"] = str(GATEWAY_DIR / "browsers")
    probe = subprocess.run(
        [str(python), "-c", "from playwright.sync_api import sync_playwright; p=sync_playwright().start(); print(p.chromium.executable_path); p.stop()"],
        capture_output=True, text=True, timeout=30, env=env, creationflags=_NO_WINDOW,
    )
    executable = probe.stdout.strip().splitlines()[-1] if probe.returncode == 0 and probe.stdout.strip() else ""
    if not executable or not Path(executable).is_file():
        raise RuntimeError("Playwright не нашёл скачанный Chromium. Повторите установку gateway.")
    return executable


def _start_gateway(project, python, api_key, admin_key):
    global _gateway_process
    import provider_proxy
    route_proxy = provider_proxy.proxy_url_for_hub_requests()
    if _gateway_running(api_key):
        return
    chromium_path = _playwright_chromium_path(python)
    env = os.environ.copy()
    env.update({"MUSE2API_HOST":"127.0.0.1", "MUSE2API_PORT":"18610",
                "MUSE2API_DRIVER":"browser", "MUSE2API_API_KEY":api_key,
                "MUSE2API_ADMIN_KEY":admin_key, "MUSE2API_DATA_DIR":str(GATEWAY_DATA),
                "MUSE2API_HEADLESS":"true", "PYTHONUNBUFFERED":"1",
                "PLAYWRIGHT_BROWSERS_PATH":str(GATEWAY_DIR / "browsers"),
                "MUSE2API_CHROMIUM_PATH":chromium_path,
                "MUSE2API_BROWSER_PROXY":route_proxy})
    log_path = APP_DATA / "museai-gateway.log"
    with log_path.open("a", encoding="utf-8") as log_stream:
        _gateway_process = subprocess.Popen([str(python), "-m", "museai"], cwd=project, env=env,
                                            stdin=subprocess.DEVNULL, stdout=log_stream,
                                            stderr=subprocess.STDOUT,
                                            creationflags=_NO_WINDOW)
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        if _gateway_running(api_key):
            return
        if _gateway_process.poll() is not None:
            raise RuntimeError(f"Gateway завершился при запуске. Лог: {log_path}")
        time.sleep(0.5)
    raise RuntimeError("Muse AI gateway не ответил на localhost:18610")


_LOGIN_SCRIPT = r'''import json, os, sys, time
from playwright.sync_api import sync_playwright
profile = sys.argv[1]
required = {"hatch_sess", "hatch_gw", "hatch_native_auth_device"}
print("LOGIN_WAIT_MISSING:" + ",".join(sorted(required)), flush=True)
with sync_playwright() as p:
    proxy = os.environ.get("MUSEAI_HUB_BROWSER_PROXY")
    context = p.chromium.launch_persistent_context(profile, headless=False, proxy={"server":proxy} if proxy else None,
        args=["--disable-blink-features=AutomationControlled"])
    page = context.pages[0] if context.pages else context.new_page()
    page.goto("https://muse.ai", wait_until="domcontentloaded", timeout=60000)
    print("Muse.ai открыта. Войдите в своём аккаунте в открытом окне; при необходимости завершите MFA/CAPTCHA.", file=sys.stderr, flush=True)
    deadline = time.monotonic() + 600
    result = None
    selected = {}
    last_report = 0
    session_probe_done = False
    while time.monotonic() < deadline:
        # Do not URL-filter here: Muse's login can set host-only cookies on a
        # Muse subdomain, which context.cookies(["https://muse.ai"]) omits.
        cookies = context.cookies()
        selected = {c["name"]: c for c in cookies
                    if (c.get("domain", "").lstrip(".").lower() == "muse.ai"
                        or c.get("domain", "").lstrip(".").lower().endswith(".muse.ai"))}
        # Muse may issue hatch_gw only after its session endpoint is queried.
        # Once the user's two primary auth cookies exist, make that same-origin
        # request once and let Chromium retain any Set-Cookie response.
        if (not session_probe_done
                and {"hatch_sess", "hatch_native_auth_device"}.issubset(selected)
                and "hatch_gw" not in selected):
            session_probe_done = True
            try:
                status = page.evaluate("""async () => {
                    try {
                        const response = await fetch('/api/session', {
                            credentials: 'include', headers: {accept: 'application/json'}
                        });
                        return response.status;
                    } catch (_) { return 0; }
                }""")
            except Exception:
                status = 0
            print("LOGIN_SESSION_PROBE:" + str(status), flush=True)
            cookies = context.cookies()
            selected = {c["name"]: c for c in cookies
                        if (c.get("domain", "").lstrip(".").lower() == "muse.ai"
                            or c.get("domain", "").lstrip(".").lower().endswith(".muse.ai"))}
        if required.issubset(selected):
            exported = {name: item for name, item in selected.items()
                        if name in {"hatch_sess", "hatch_gw", "hatch_native_auth_device", "hatch_vml", "datr"}}
            result = {"cookies": {name: item["value"] for name, item in exported.items()},
                      "cookie_expires": {name: item.get("expires", 0) for name, item in exported.items()}}
            break
        if time.monotonic() - last_report >= 10:
            print("LOGIN_WAIT_MISSING:" + ",".join(sorted(required - set(selected))), flush=True)
            last_report = time.monotonic()
        time.sleep(2)
    context.close()
    if not result:
        print("LOGIN_TIMEOUT_MISSING:" + ",".join(sorted(required - set(selected))), flush=True)
        sys.exit(2)
    print("MUSE_COOKIES:" + json.dumps(result, separators=(",", ":")), flush=True)
'''


def _login_and_import(python, api_key, admin_key):
    profile = APP_DATA / "museai-login-profile"
    profile.mkdir(parents=True, exist_ok=True)
    _set_job("login", "Войдите в Muse.ai в открывшемся окне браузера…")
    env = os.environ.copy()
    env["PLAYWRIGHT_BROWSERS_PATH"] = str(GATEWAY_DIR / "browsers")
    import provider_proxy
    env["MUSEAI_HUB_BROWSER_PROXY"] = provider_proxy.proxy_url_for_hub_requests()
    process = subprocess.Popen([str(python), "-c", _LOGIN_SCRIPT, str(profile)],
                               stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                               text=True, encoding="utf-8", bufsize=1, env=env,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    output_lines = []
    try:
        # Progress lines contain only missing cookie names. The final cookies
        # line remains in memory and is never copied into status or logs.
        for raw_line in process.stdout:
            line = raw_line.rstrip("\r\n")
            if line.startswith("LOGIN_WAIT_MISSING:"):
                missing = line.split(":", 1)[1]
                message = "Ожидаем вход Muse.ai в открытом браузере."
                if missing:
                    message += f" Не найдены cookie: {missing}."
                _set_job("login", message)
            elif line.startswith("LOGIN_SESSION_PROBE:"):
                status = line.split(":", 1)[1]
                _set_job("login", f"Проверка сессии Muse.ai завершилась HTTP {status}; ожидаем cookie hatch_gw.")
            else:
                output_lines.append(line)
        process.wait(timeout=10)
    except Exception:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=10)
        shutil.rmtree(profile, ignore_errors=True)
        raise RuntimeError("Не удалось завершить процесс входа в браузере") from None
    # The session cookies are now held by the gateway; remove the temporary
    # interactive browser profile so this is not a second persistent cookie jar.
    shutil.rmtree(profile, ignore_errors=True)
    line = next((line for line in output_lines if line.startswith("MUSE_COOKIES:")), None)
    if process.returncode or not line:
        missing = next((line.split(":", 1)[1] for line in output_lines
                        if line.startswith("LOGIN_TIMEOUT_MISSING:")), "")
        if missing:
            raise RuntimeError(f"Веб-вход выполнен, но не найдены обязательные cookies: {missing}. Повторите вход; проверьте, что Muse открыта на muse.ai.")
        raise RuntimeError("Не удалось получить cookies сессии. Проверьте вход в браузере и повторите попытку.")
    payload = json.loads(line[len("MUSE_COOKIES:"):])
    payload["cookies"] = filter_museai_cookies(payload.get("cookies"))
    payload["cookie_expires"] = {
        name: expiry for name, expiry in normalize_cookie_expiry(payload.get("cookie_expires")).items()
        if name in payload["cookies"]
    }
    _set_job("import", "Сохраняем сессию в локальном gateway…")
    _upsert_gateway_account(admin_key, payload)


def _upsert_gateway_account(admin_key, payload):
    """Replace this Hub-managed account on re-login; never accumulate stale sessions."""
    base = "http://127.0.0.1:18610/admin/accounts"
    headers = {"Authorization":f"Bearer {admin_key}", "Content-Type":"application/json"}
    try:
        req = urllib.request.Request(base, headers=headers)
        with urllib.request.urlopen(req, timeout=20) as response:
            accounts = json.loads(response.read().decode("utf-8")).get("data", [])
        account = next((item for item in accounts
                        if isinstance(item, dict) and item.get("label") == "primary-account"), None)
        method = "PATCH" if account and account.get("id") else "POST"
        url = f"{base}/{quote(account['id'], safe='')}" if method == "PATCH" else base
        body = json.dumps({"label":"primary-account", **payload}).encode("utf-8")
        req = urllib.request.Request(url, data=body, method=method, headers=headers)
        with urllib.request.urlopen(req, timeout=20) as response:
            if response.status not in (200, 201):
                raise RuntimeError("Gateway отклонил импорт сессии")
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            body = json.loads(exc.read().decode("utf-8"))
            # The gateway's validation handler returns field names/messages, not submitted values.
            detail = str((body.get("error") or {}).get("message") or "")[:240]
        except Exception:
            pass
        raise RuntimeError(f"Gateway отклонил импорт cookies (HTTP {exc.code})" + (f": {detail}" if detail else "")) from None


def normalize_cookie_expiry(expirations):
    """Convert Playwright's numeric expiry values to gateway-required unix ints."""
    if not isinstance(expirations, dict):
        return {}
    result = {}
    for name, expiry in expirations.items():
        if expiry is None:
            continue
        try:
            result[str(name)] = int(float(expiry))
        except (TypeError, ValueError, OverflowError):
            continue
    return result


def filter_museai_cookies(cookies):
    """Keep only cookies the Muse gateway uses; notably drop __Host-* cookies."""
    if not isinstance(cookies, dict):
        return {}
    return {name: value for name, value in cookies.items()
            if name in MUSEAI_COOKIE_ALLOWLIST and isinstance(value, str) and value}


def _setup_worker():
    try:
        api_key, admin_key = _gateway_keys()
        project, python = _install_gateway()
        _start_gateway(project, python, api_key, admin_key)
        _login_and_import(python, api_key, admin_key)
        models = fetch_models(DEFAULT_BASE_URL, api_key)
        selected = [model["id"] for model in models]
        connect(DEFAULT_BASE_URL, api_key, selected)
        _set_job("done", f"Muse AI подключён; доступно моделей: {len(models)}", running=False)
    except Exception as exc:
        # Keep secrets and subprocess output out of the UI error message.
        message = str(exc)
        if "MUSE_COOKIES" in message or "hatch_" in message:
            message = "Не удалось завершить безопасный вход. Повторите попытку и проверьте авторизацию в браузере."
        _set_job("error", "Настройка не завершена", error=message[:300], running=False)


def start_setup(force_login=False):
    cfg = load_config()
    worker = _setup_worker
    if (not force_login and cfg.get("connected") and cfg.get("gateway_api_key")
            and cfg.get("gateway_admin_key")):
        worker = _recover_saved_gateway
    with _job_lock:
        if _job_state["running"]:
            return dict(_job_state)
        _job_state.update(running=True, stage="starting", message="Подготовка…", error="")
    name = "museai-gateway-recovery" if worker is _recover_saved_gateway else "museai-first-login"
    threading.Thread(target=worker, daemon=True, name=name).start()
    return setup_state()


def stop_gateway():
    global _gateway_process
    if _gateway_process and _gateway_process.poll() is None:
        _gateway_process.terminate()
        _gateway_process = None
