"""
Antigravity Hub - Webview2 Frosted Glass Backend Bridge
Provides the Python API layer for the Web frontend (Variant 3 Glassmorphism UI).
"""

import os
import sys
import json
import time
import socket
import threading
import subprocess
import copy
import ipaddress
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse
from pathlib import Path

# Add current directory to path to import helper modules
CURRENT_DIR = Path(__file__).resolve().parent
if str(CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(CURRENT_DIR))

import antigravity_manager
from proxy_config import sync_provider_routes
import opencode_config
import auto_updater
import openai_manager
import win_tray
try:
    import claude_manager
    claude_service = claude_manager.claude_service
except Exception:
    claude_service = None

from vless_manager import get_http_port, get_socks_port, vless_service, VlessParser
import provider_proxy
import auto_router
import dns_tester
import google_smart_dns
import xpiki_manager
import openrouter_manager

CONFIG_DIR = Path(os.path.expanduser("~/.config/opencode"))
ANTIGRAVITY_CONFIG_FILE = CONFIG_DIR / "antigravity.json"
OPENCODE_CONFIG_FILE = CONFIG_DIR / "opencode.json"
LOG_DIR = CONFIG_DIR / "logs"

CLOUDCODE_ENDPOINTS = [
    "daily-cloudcode-pa.googleapis.com",
    "cloudcode-pa.googleapis.com",
    "containers.cloud.google.com",
    "artifactregistry.googleapis.com",
    "oauth2.googleapis.com",
    "clients6.google.com",
]


PROVIDER_DOMAINS = {
    "google": CLOUDCODE_ENDPOINTS,
    "openai": ["chatgpt.com", "auth.openai.com", "api.openai.com"],
    "claude-pro": ["claude.ai", "api.anthropic.com", "console.anthropic.com"],
    "xpiki": ["api.xpiki.com"],
    "openrouter-free": ["openrouter.ai"],
}
PROVIDER_SETTING_IDS = {"antigravity": "google", "openai": "openai", "claude": "claude-pro",
                        "xpiki": "xpiki", "openrouter": "openrouter-free"}


class HubApi:
    """Exposed to window.pywebview.api in JavaScript."""

    def __init__(self, window_holder=None):
        # pywebview recursively inspects public API attributes. A public Window
        # reference exposes native GUI properties and can block bridge startup.
        self._window_holder = window_holder
        self._config_lock = threading.RLock()
        self._quota_lock = threading.Lock()
        self._quota_refreshing = False
        self._quota_error = None
        self._diagnostics = {}
        self._diagnostic_signatures = {}
        self._diagnostic_checked = {}
        self._diagnostic_lock = threading.Lock()
        self._diagnostic_running = set()
        self._openrouter_models = []
        self._provider_lock = threading.RLock()
        self._core_lock = threading.Lock()

    def load_config(self) -> dict:
        if ANTIGRAVITY_CONFIG_FILE.exists():
            try:
                return {**copy.deepcopy(antigravity_manager.DEFAULT_CONFIG),
                        **json.loads(ANTIGRAVITY_CONFIG_FILE.read_text(encoding="utf-8"))}
            except Exception:
                pass
        return copy.deepcopy(antigravity_manager.DEFAULT_CONFIG)

    def save_config(self, cfg: dict) -> bool:
        try:
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            with self._config_lock:
                pending = ANTIGRAVITY_CONFIG_FILE.with_suffix(".json.tmp")
                pending.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
                pending.replace(ANTIGRAVITY_CONFIG_FILE)
            return True
        except Exception as e:
            print(f"Error saving config: {e}")
            return False

    def is_opencode_running(self) -> bool:
        if sys.platform != "win32":
            return False
        try:
            proc = subprocess.run(
                ["tasklist", "/fi", "imagename eq opencode.exe", "/fo", "csv", "/nh"],
                capture_output=True, text=True, timeout=5, creationflags=0x08000000
            )
            return "opencode.exe" in proc.stdout.lower()
        except Exception:
            return False

    def get_state(self) -> dict:
        """Returns the full reactive state for the glass frontend."""
        raw_accounts = antigravity_manager.export_google_accounts()
        accounts = antigravity_manager.enrich_google_accounts_with_generation_store(raw_accounts)
        disk_accounts = antigravity_manager.enrich_google_accounts_with_generation_store([])
        # Exported credential rows can omit index and incomplete generation rows.
        # Preserve the store's original index rather than numbering filtered rows.
        by_id = {a.get("id"): a for a in disk_accounts if a.get("id")}
        active = antigravity_manager.get_active_google_health_account()
        for i, account in enumerate(accounts):
            disk = by_id.get(account.get("id"), {})
            account["index"] = disk.get("index", account.get("index", i + 1))
            account["is_active"] = bool(active and (
                (active.get("id") and active.get("id") == account.get("id")) or
                (not active.get("id") and active.get("email") == account.get("email"))))
        active_index = antigravity_manager.get_active_google_account_index()

        cfg = self.load_config()
        routes = cfg.get("provider_routes", {})
        try:
            oc = json.loads(OPENCODE_CONFIG_FILE.read_text(encoding="utf-8")) if OPENCODE_CONFIG_FILE.exists() else {}
            disabled = oc.get("disabled_providers", [])
            visibility = dict(cfg.get("providers_visibility", {}))
            for key, provider_id in PROVIDER_SETTING_IDS.items():
                if provider_id in disabled:
                    visibility[key] = False
            cfg["providers_visibility"] = visibility
        except (OSError, ValueError, TypeError):
            pass

        openai_accs = openai_manager.load_openai_accounts() if hasattr(openai_manager, "load_openai_accounts") else []
        claude_accs = claude_service.load_accounts() if claude_service else []
        claude_active = next((index for index, account in enumerate(claude_accs) if account.get("active")),
                             0 if claude_accs else None)

        return {
            "accounts": [{k: a[k] for k in ("id", "email", "index", "is_active", "groups", "candidate", "status") if k in a} for a in accounts],
            "activeIndex": active_index,
            "activeGoogleId": active.get("id") if active else None,
            "openaiAccounts": [{k: a[k] for k in ("id", "accountId", "email", "plan_type", "is_active", "quota") if k in a} for a in openai_accs],
            "claudeAccounts": [{**{k: a[k] for k in ("id", "email", "name", "plan") if k in a},
                                "is_active": index == claude_active} for index, a in enumerate(claude_accs)],
            "openaiRefreshing": self._quota_refreshing,
            "openaiError": self._quota_error,
            "routes": routes,
            "config": cfg,
            "opencodeRunning": self.is_opencode_running(),
            "diagnostics": self.get_cached_diagnostics(),
            "network": self.get_network_state(),
            "providers": self.get_provider_state(),
        }

    def get_network_state(self) -> dict:
        cfg = self.load_config()
        oc = json.loads(OPENCODE_CONFIG_FILE.read_text(encoding="utf-8")) if OPENCODE_CONFIG_FILE.exists() else {}
        auto_states = {}
        for provider in PROVIDER_DOMAINS:
            visibility_key = {"google":"antigravity", "claude-pro":"claude", "openrouter-free":"openrouter"}.get(provider, provider)
            enabled = cfg.get("providers_visibility", {}).get(visibility_key, True) and provider not in oc.get("disabled_providers", [])
            if enabled and cfg.get("provider_routes", {}).get(provider, "default") in ("default", "auto"):
                auto_router.router.refresh(provider, cfg, oc)
            auto_states[provider] = auto_router.router.state(provider, cfg, oc)
        core = vless_service.find_core_executable(cfg.get("vless_core_path"))
        cores = {}
        for kind in ("sing-box", "xray"):
            path = vless_service.find_core_executable(core_type=kind)
            if core and ((kind == "xray") == ("xray" in core.name.lower())):
                path = core
            cores[kind] = {"installed": bool(path), "path": str(path) if path else None,
                           "selected": bool(path and core and path == core)}
        return {"autoRoutes": auto_states, "cores": cores, "vlessRunning": vless_service.is_running(),
                "vlessCore": str(core) if core else None,
                "httpPort": get_http_port(), "socksPort": get_socks_port()}

    def refresh_auto_routes(self, provider: str) -> bool:
        if provider not in PROVIDER_DOMAINS:
            raise ValueError("Неизвестный провайдер")
        cfg = self.load_config()
        oc = json.loads(OPENCODE_CONFIG_FILE.read_text(encoding="utf-8")) if OPENCODE_CONFIG_FILE.exists() else {}
        auto_router.router.refresh(provider, cfg, oc, force=True)
        return True

    def _sync_routes(self, cfg):
        if OPENCODE_CONFIG_FILE.exists():
            oc_data = json.loads(OPENCODE_CONFIG_FILE.read_text(encoding="utf-8"))
            sync_provider_routes(oc_data, cfg, get_http_port(), cfg.get("provider_routes", {}))
            pending = OPENCODE_CONFIG_FILE.with_suffix(".json.hub.tmp")
            pending.write_text(json.dumps(oc_data, indent=2, ensure_ascii=False), encoding="utf-8")
            pending.replace(OPENCODE_CONFIG_FILE)
        if not provider_proxy.start():
            raise RuntimeError("Маршрутизатор Hub недоступен на порту 10880")

    def _diagnostic_signature(self, cfg=None):
        cfg = self.load_config() if cfg is None else cfg
        keys = ("provider_routes", "dns_mode", "custom_dns", "dot_host", "doh_url", "proxy",
                "vless_enabled", "vless_url", "vless_http_port", "google_smart_doh")
        return json.dumps([{key: cfg.get(key) for key in keys},
                           xpiki_manager.load_xpiki_config().get("base_url")], sort_keys=True)

    def get_cached_diagnostics(self) -> dict:
        signature = self._diagnostic_signature()
        with self._diagnostic_lock:
            return {provider: {"rows": list(self._diagnostics.get(provider, []))
                               if self._diagnostic_signatures.get(provider) == signature else [],
                               "checkedAt": self._diagnostic_checked.get(provider)
                               if self._diagnostic_signatures.get(provider) == signature else None,
                               "running": provider in self._diagnostic_running}
                    for provider in PROVIDER_DOMAINS}

    def run_google_diagnostics(self) -> list:
        return self.run_provider_diagnostics("google")

    def run_provider_diagnostics(self, provider: str) -> list:
        if provider not in PROVIDER_DOMAINS:
            raise ValueError("Неизвестный провайдер")
        with self._diagnostic_lock:
            if provider in self._diagnostic_running:
                return list(self._diagnostics.get(provider, []))
            self._diagnostic_running.add(provider)
        cfg = self.load_config()
        signature = self._diagnostic_signature(cfg)
        # Preserve configured provider IDs for the dispatcher's domain matching,
        # including providers that have not yet been connected in OpenCode.
        domains = list(PROVIDER_DOMAINS[provider])
        if provider == "xpiki":
            host = urlparse(xpiki_manager.load_xpiki_config().get("base_url") or xpiki_manager.DEFAULT_BASE_URL).hostname
            if host:
                domains = [host]
        try:
            oc = json.loads(OPENCODE_CONFIG_FILE.read_text(encoding="utf-8")) if OPENCODE_CONFIG_FILE.exists() else {}
            oc = copy.deepcopy(oc)
            entry = oc.setdefault("provider", {}).setdefault(provider, {})
            if provider == "xpiki":
                entry.setdefault("options", {}).setdefault("baseURL", "https://" + domains[0])
            def probe(domain):
                row = {"domain": domain, "status": "error", "latency_ms": None,
                       "route": "Не определён", "ip": None}
                t0 = time.perf_counter()
                try:
                    conn, upstream = provider_proxy.connect_routed(domain, 443, hub_config=cfg, opencode_config=oc)
                    row["route"] = ("SmartDNS · эксперимент" if upstream == "smartdns://google"
                        else "DNS Hub" if upstream == "dns://hub" else "Системный маршрут" if not upstream
                        else "VLESS" if upstream == f"http://127.0.0.1:{get_http_port()}" else "HTTP-прокси")
                    with conn:
                        row.update(status="ok", latency_ms=round((time.perf_counter() - t0) * 1000),
                                   ip=conn.getpeername()[0])
                except Exception as exc:
                    row["error"] = type(exc).__name__
                return row
            with ThreadPoolExecutor(max_workers=4) as executor:
                results = list(executor.map(probe, domains))
            if signature != self._diagnostic_signature():
                return []
            with self._diagnostic_lock:
                self._diagnostics[provider] = results
                self._diagnostic_signatures[provider] = signature
                self._diagnostic_checked[provider] = time.time()
            return results
        finally:
            with self._diagnostic_lock:
                self._diagnostic_running.discard(provider)

    def set_provider_route(self, provider: str, route: str) -> bool:
        provider = {"claude": "claude-pro", "openrouter": "openrouter-free"}.get(provider, provider)
        if provider not in ("google", "openai", "claude-pro", "xpiki", "openrouter-free"):
            raise ValueError("Неизвестный провайдер")
        if route not in ("direct", "default", "auto", "vless", "dns", "proxy", "google-smart"):
            raise ValueError("Неизвестный маршрут")
        if route == "google-smart" and provider != "google":
            raise ValueError("Экспериментальный SmartDNS доступен только для Google")
        with self._config_lock:
            cfg = self.load_config()
            if route == "vless" and not vless_service.is_running():
                raise ValueError("Сначала настройте и запустите VLESS-туннель")
            if route == "proxy" and not cfg.get("proxy"):
                raise ValueError("Сначала укажите внешний прокси")
            cfg.setdefault("provider_routes", {})[provider] = route
            if not self.save_config(cfg):
                raise OSError("Не удалось сохранить маршрут")
            self._sync_routes(cfg)
            with self._diagnostic_lock:
                self._diagnostics.clear()
        if route in ("default", "auto"):
            self.refresh_auto_routes(provider)
        return True

    def save_network_settings(self, settings: dict) -> dict:
        allowed = {"vless_url", "vless_core_path", "vless_kill_switch", "dns_mode", "custom_dns", "dot_host", "doh_url",
                   "google_smart_doh", "proxy"}
        with self._config_lock:
            cfg = self.load_config()
            previous = dict(cfg)
            cfg.update({k: v for k, v in settings.items() if k in allowed})
            mode = cfg.get("dns_mode", "system")
            if mode not in ("system", "standard", "dot", "doh"):
                raise ValueError("Неизвестный режим DNS")
            servers = cfg.get("custom_dns", [])
            if not isinstance(servers, list):
                raise ValueError("Укажите список DNS-серверов")
            for server in servers:
                ipaddress.ip_address(server)
            if mode == "standard" and not servers:
                raise ValueError("Укажите хотя бы один DNS-сервер")
            if mode == "dot" and not str(cfg.get("dot_host", "")).strip():
                raise ValueError("Укажите хост DoT")
            if mode == "doh":
                parsed = urlparse(str(cfg.get("doh_url", "")))
                if parsed.scheme != "https" or not parsed.hostname:
                    raise ValueError("Укажите HTTPS URL для DoH")
            cfg["google_smart_doh"] = google_smart_dns.resolver_url(cfg)
            for key, fallback in (("vless_http_port", 10879), ("vless_socks_port", 10878)):
                port = int(cfg.get(key, fallback))
                if not 1024 <= port <= 65535:
                    raise ValueError("Порты VLESS должны быть от 1024 до 65535")
                cfg[key] = port
            if cfg["vless_http_port"] == cfg["vless_socks_port"]:
                raise ValueError("HTTP и SOCKS порты должны различаться")
            if cfg.get("vless_url"):
                VlessParser.parse_url(cfg["vless_url"])
            proxy = str(cfg.get("proxy") or "").strip()
            if proxy:
                parsed = urlparse(proxy)
                if parsed.scheme not in ("http", "https") or not parsed.hostname:
                    raise ValueError("Внешний прокси: укажите http:// или https:// адрес")
                if parsed.hostname in ("localhost", "127.0.0.1") and parsed.port == provider_proxy.PORT:
                    raise ValueError("Нельзя использовать собственный маршрутизатор как внешний прокси")
            cfg["proxy"] = proxy
            if vless_service.is_running() and any(cfg.get(k) != previous.get(k) for k in
                    ("vless_url", "vless_core_path", "vless_http_port", "vless_socks_port")):
                raise ValueError("Остановите туннель перед изменением ссылки, ядра или портов")
            if not self.save_config(cfg):
                raise OSError("Не удалось сохранить настройки сети")
            self._sync_routes(cfg)
            with self._diagnostic_lock:
                self._diagnostics.clear()
        return {"ok": True, "message": "Настройки сети сохранены. Новые подключения используют выбранный маршрут."}

    def start_vless(self) -> dict:
        with self._config_lock:
            cfg = self.load_config()
            if vless_service.is_running():
                ok, message = True, "VLESS-туннель уже запущен"
            else:
                ok, message = vless_service.start_tunnel(cfg.get("vless_url", ""),
                                                       custom_core_path=cfg.get("vless_core_path"))
            if ok:
                cfg["vless_enabled"] = True
                if not self.save_config(cfg):
                    raise OSError("Туннель запущен, но его настройки не сохранены")
                self._sync_routes(cfg)
            return {"ok": ok, "message": message}

    def stop_vless(self) -> dict:
        with self._config_lock:
            ok, message = vless_service.stop_tunnel()
            cfg = self.load_config()
            cfg["vless_enabled"] = False
            if not self.save_config(cfg):
                raise OSError("Не удалось сохранить состояние туннеля")
            return {"ok": ok, "message": message}

    def test_vless(self) -> dict:
        return vless_service.test_connection()

    def download_vless_core(self, core_type: str = "sing-box") -> dict:
        if core_type not in ("sing-box", "xray"):
            raise ValueError("Неизвестное ядро")
        with self._core_lock:
            ok, message = vless_service.download_core(core_type)
        return {"ok": ok, "message": message}

    def test_dns(self, mode: str, value: str) -> dict:
        # Pass the domain explicitly so concurrent resolver checks are independent.
        domain = "cloudcode-pa.googleapis.com"
        if mode == "standard":
            ipaddress.ip_address(value)
            return dns_tester.test_standard_dns(value, domain=domain)
        if mode == "dot":
            return dns_tester.test_dot_endpoint(value, domain=domain)
        if mode == "doh":
            return dns_tester.test_doh_endpoint(value, domain=domain)
        raise ValueError("Для проверки выберите обычный DNS, DoT или DoH")

    def refresh_openai_quotas(self) -> dict:
        with self._quota_lock:
            if self._quota_refreshing:
                return {"ok": True, "refreshing": True}
            self._quota_refreshing = True
            self._quota_error = None
        def worker():
            try:
                accounts = openai_manager.load_openai_accounts()
                for account in accounts:
                    account["quota"] = openai_manager.fetch_openai_usage(account)
                if accounts and not openai_manager.save_openai_accounts(accounts):
                    raise OSError("Не удалось сохранить лимиты ChatGPT")
            except Exception as exc:
                self._quota_error = str(exc)
            finally:
                with self._quota_lock:
                    self._quota_refreshing = False
        threading.Thread(target=worker, daemon=True, name="hub-openai-quotas").start()
        return {"ok": True, "refreshing": True}

    def get_provider_state(self) -> dict:
        xpiki = xpiki_manager.load_xpiki_config()
        xpiki_key = str(xpiki.get("api_key") or "")
        openrouter_key = openrouter_manager.load_api_key()
        def key_label(key):
            return "••••" + key[-4:] if len(key) > 8 else "Ключ сохранён" if key else None
        selected = []
        try:
            if OPENCODE_CONFIG_FILE.exists():
                oc = json.loads(OPENCODE_CONFIG_FILE.read_text(encoding="utf-8"))
                selected = list(oc.get("provider", {}).get("openrouter-free", {}).get("models", {}))
        except (OSError, ValueError):
            pass
        return {"xpiki": {"connected": bool(xpiki.get("connected") and xpiki_key), "hasKey": bool(xpiki_key),
                          "keyLabel": key_label(xpiki_key),
                          "baseUrl": xpiki.get("base_url") or xpiki_manager.DEFAULT_BASE_URL,
                          "enabledModels": xpiki.get("enabled_models", list(xpiki_manager.XPIKI_MODELS)),
                          "models": [{"id": mid, "name": meta["name"]} for mid, meta in xpiki_manager.XPIKI_MODELS.items()],
                          "quota": xpiki.get("cached_quota") or {}},
                "openrouter": {"hasKey": bool(openrouter_key), "keyLabel": key_label(openrouter_key),
                               "connected": bool(openrouter_key and selected), "selectedModels": selected}}

    def configure_xpiki(self, key: str, base_url: str, models: list) -> dict:
        with self._provider_lock:
            cfg = xpiki_manager.load_xpiki_config()
            key = key.strip() or cfg.get("api_key", "")
            parsed = urlparse(base_url)
            if not key or parsed.scheme != "https" or not parsed.hostname:
                raise ValueError("Укажите ключ Xpiki и HTTPS URL шлюза")
            if not models or any(mid not in xpiki_manager.XPIKI_MODELS for mid in models):
                raise ValueError("Выберите модели Xpiki")
            if not xpiki_manager.configure_opencode(key, base_url, models):
                raise OSError("Не удалось настроить Xpiki в OpenCode")
            cfg.update(api_key=key, base_url=base_url, enabled_models=models, connected=True)
            if not xpiki_manager.save_xpiki_config(cfg):
                raise OSError("Не удалось сохранить настройки Xpiki")
            self._sync_routes(self.load_config())
            return {"ok": True, "message": "Xpiki добавлен в OpenCode"}

    def refresh_xpiki_quota(self) -> dict:
        cfg = xpiki_manager.load_xpiki_config()
        if not cfg.get("api_key"):
            raise ValueError("Сначала сохраните API-ключ Xpiki")
        return xpiki_manager.fetch_xpiki_quota(cfg["api_key"], cfg.get("base_url") or xpiki_manager.DEFAULT_BASE_URL)

    def disconnect_xpiki(self) -> bool:
        with self._provider_lock:
            if not xpiki_manager.disconnect_xpiki():
                raise OSError("Не удалось отключить Xpiki")
        return True

    def load_openrouter_models(self, key: str = "") -> list:
        with self._provider_lock:
            key = key.strip() or openrouter_manager.load_api_key()
            if not key:
                raise ValueError("Укажите API-ключ OpenRouter")
            models = openrouter_manager.fetch_free_models(key)
            openrouter_manager.save_api_key(key)
            self._openrouter_models = models
            return models

    def apply_openrouter_models(self, model_ids: list) -> bool:
        with self._provider_lock:
            selected = [m for m in self._openrouter_models if m["id"] in model_ids]
            if not selected or len(selected) != len(set(model_ids)):
                raise ValueError("Загрузите каталог и выберите бесплатные модели")
            key = openrouter_manager.load_api_key()
            if not key:
                raise ValueError("Сначала сохраните ключ OpenRouter")
            openrouter_manager.sync_opencode_credential(key)
            openrouter_manager.configure_models(selected)
            self._sync_routes(self.load_config())
            return True

    def disconnect_openrouter(self) -> bool:
        with self._provider_lock:
            openrouter_manager.disconnect()
            self._openrouter_models = []
        return True

    def add_google_account(self) -> dict:
        node_exe = antigravity_manager.get_node_executable()
        cli_js = antigravity_manager.get_cli_js()
        if not (os.path.exists(node_exe) and os.path.exists(cli_js)):
            return {"status": "error", "message": "Файлы Node/CLI не найдены"}

        # Launch auth in browser
        subprocess.Popen([node_exe, cli_js, "auth"])
        return {"status": "ok", "message": "Браузер запущен. Завершите вход в Google"}

    def activate_google_account(self, idx: int) -> bool:
        if not isinstance(idx, int) or idx < 0:
            raise ValueError("Некорректный индекс аккаунта")
        if not antigravity_manager.set_active_google_account_index(idx):
            raise RuntimeError("Не удалось переключить активный Google-аккаунт")
        return True

    def delete_google_account(self, aid_or_email: str) -> bool:
        return antigravity_manager.delete_google_account(aid_or_email)

    def test_google_account(self, aid_or_email: str) -> str:
        acc = next((a for a in antigravity_manager.export_google_accounts()
                    if a.get("id") == aid_or_email or a.get("email") == aid_or_email), None)
        if not acc:
            return "Аккаунт не найден"
        try:
            import google_health_auth
            node_exe = antigravity_manager.get_node_executable()
            cli_js = antigravity_manager.get_cli_js()
            refreshed = google_health_auth.refresh_google_health_account(
                acc, antigravity_manager.run_google_route_cmd, node_exe, cli_js
            )
            return "Аккаунт успешно проверен, токены активны"
        except Exception as e:
            return f"Результат проверки: {e}"

    def toggle_google_candidate(self, aid_or_email: str, enabled: bool) -> bool:
        return antigravity_manager.set_google_account_candidate(aid_or_email, enabled)

    def add_openai_account(self) -> bool:
        def _bg():
            openai_manager.login_openai_browser(timeout=300)
        threading.Thread(target=_bg, daemon=True).start()
        return True

    def add_claude_account(self) -> bool:
        if not claude_service:
            return False
        def _bg():
            claude_service.login_claude_browser(mode="browser", timeout=300)
        threading.Thread(target=_bg, daemon=True).start()
        return True

    def set_strategy(self, strat: str) -> bool:
        with self._config_lock:
            cfg = self.load_config()
            cfg["account_selection_strategy"] = strat
            return self.save_config(cfg)

    def save_general_settings(self, settings: dict) -> bool:
        with self._config_lock:
            cfg = self.load_config()
            previous = copy.deepcopy(cfg)
            cfg.update({k: v for k, v in settings.items() if k == "switch_on_first_rate_limit"})
            oc = None
            if "providers_visibility" in settings:
                visibility = settings["providers_visibility"]
                if not isinstance(visibility, dict) or any(key not in PROVIDER_SETTING_IDS or not isinstance(value, bool)
                                                          for key, value in visibility.items()):
                    raise ValueError("Неверные настройки провайдеров")
                oc = json.loads(OPENCODE_CONFIG_FILE.read_text(encoding="utf-8")) if OPENCODE_CONFIG_FILE.exists() else {}
                disabled = oc.get("disabled_providers", [])
                if not isinstance(disabled, list):
                    raise ValueError("disabled_providers должен быть списком")
                disabled = list(disabled)
                for key, enabled in visibility.items():
                    provider_id = PROVIDER_SETTING_IDS[key]
                    disabled = [item for item in disabled if item != provider_id]
                    if not enabled:
                        disabled.append(provider_id)
                oc["disabled_providers"] = disabled
                cfg["providers_visibility"] = {**cfg.get("providers_visibility", {}), **visibility}
            if not self.save_config(cfg):
                return False
            if oc is not None:
                try:
                    pending = OPENCODE_CONFIG_FILE.with_suffix(".json.hub.tmp")
                    pending.write_text(json.dumps(oc, indent=2, ensure_ascii=False), encoding="utf-8")
                    pending.replace(OPENCODE_CONFIG_FILE)
                except Exception:
                    self.save_config(previous)
                    raise
            return True

    def restart_opencode(self) -> bool:
        self.stop_opencode()
        time.sleep(1)
        return self.start_opencode()

    def stop_opencode(self) -> bool:
        if sys.platform != "win32":
            return False
        try:
            subprocess.run(["taskkill", "/f", "/im", "opencode.exe"], capture_output=True, timeout=5, creationflags=0x08000000)
            return True
        except Exception:
            return False

    def start_opencode(self) -> bool:
        exe = antigravity_manager.get_opencode_exe()
        if os.path.exists(exe):
            try:
                subprocess.Popen([exe], cwd=os.path.dirname(exe))
                return True
            except Exception:
                pass
        return False

    def fix_session_title(self) -> str:
        try:
            _, msg = opencode_config.ensure_session_title_config()
            return msg
        except Exception as e:
            return str(e)

    def open_folder(self, folder_type: str) -> bool:
        target = LOG_DIR if folder_type == "logs" else CONFIG_DIR
        if target.exists() and sys.platform == "win32":
            os.startfile(target)
            return True
        return False

    def check_updates(self) -> str:
        try:
            repo_dir = CURRENT_DIR.parent
            info = auto_updater.check_update_git(repo_dir)
            if info and info.get("has_update"):
                return f"Доступно обновление: {info.get('remote_sha', '')[:7]}"
            return "Установлена последняя версия"
        except Exception as e:
            return f"Проверка обновлений: {e}"


def run_webview_app():
    """Starts the native WebView2 Frosted Glass UI with taskbar icon and system tray."""
    import webview

    html_file = CURRENT_DIR / "web" / "index.html"
    icon_file = CURRENT_DIR / "icon.ico"
    icon_str = str(icon_file.resolve()) if icon_file.exists() else None

    api = HubApi()

    # Ensure Windows taskbar groups windows under Antigravity Hub, not Python
    try:
        antigravity_manager.set_windows_taskbar_identity()
    except Exception:
        pass

    window = webview.create_window(
        title="Antigravity Hub - AI аккаунты и сеть для Windows",
        url=str(html_file.resolve()),
        js_api=api,
        width=1420,
        height=890,
        min_size=(1140, 720),
        background_color="#090d12",
    )
    api._window_holder = window

    # System Tray & Close-to-Tray setup
    tray = None
    balloon_shown = [False]

    def on_tray_show():
        try:
            window.show()
            window.restore()
        except Exception:
            pass

    def on_tray_refresh():
        try:
            api.refresh_all_quotas()
        except Exception:
            pass

    def on_tray_exit():
        try:
            if tray:
                tray.remove()
        except Exception:
            pass
        try:
            vless_service.stop_tunnel()
        except Exception:
            pass
        try:
            window.destroy()
        except Exception:
            pass
        os._exit(0)

    try:
        tray = win_tray.WindowsTrayIcon(
            title="Antigravity Hub",
            icon_path=icon_str,
            on_show=on_tray_show,
            on_refresh=on_tray_refresh,
            on_exit=on_tray_exit,
        )
        tray.start()
    except Exception as e:
        print(f"Tray initialization warning: {e}")

    def on_window_closing():
        cfg = api.load_config()
        close_to_tray = cfg.get("close_to_tray", True)
        if close_to_tray:
            try:
                window.hide()
                if tray and not balloon_shown[0]:
                    balloon_shown[0] = True
                    tray.show_balloon(
                        "Antigravity Hub свёрнут",
                        "Приложение работает в трее. Кликните левой кнопкой для открытия или правой для меню.",
                    )
            except Exception:
                pass
            return False
        else:
            try:
                if tray:
                    tray.remove()
            except Exception:
                pass
            try:
                vless_service.stop_tunnel()
            except Exception:
                pass
            return True

    window.events.closing += on_window_closing

    # Ensure custom window & taskbar icon via Win32 WM_SETICON
    def apply_native_window_icon():
        time.sleep(1.5)
        if sys.platform != "win32" or not icon_str:
            return
        try:
            import ctypes
            hwnd = ctypes.windll.user32.FindWindowW(None, "Antigravity Hub - AI аккаунты и сеть для Windows")
            if hwnd:
                h_icon = ctypes.windll.user32.LoadImageW(
                    None, icon_str, 1, 0, 0, 0x00000010 | 0x00000040
                )
                if h_icon:
                    ctypes.windll.user32.SendMessageW(hwnd, 0x0080, 1, h_icon)  # ICON_BIG
                    ctypes.windll.user32.SendMessageW(hwnd, 0x0080, 0, h_icon)  # ICON_SMALL
        except Exception:
            pass

    threading.Thread(target=apply_native_window_icon, daemon=True).start()

    # Run background token refresh thread
    def bg_refresher():
        cfg = api.load_config()
        try:
            if cfg.get("vless_enabled") and cfg.get("vless_url"):
                result = api.start_vless()
                if not result["ok"]:
                    print(result["message"])
            provider_proxy.start()
        except Exception as exc:
            print(f"Network startup: {exc}")
        while True:
            api.refresh_openai_quotas()
            time.sleep(300)
            try:
                node_exe = antigravity_manager.get_node_executable()
                cli_js = antigravity_manager.get_cli_js()
                if os.path.exists(node_exe) and os.path.exists(cli_js):
                    antigravity_manager.run_silent_cmd(
                        [node_exe, cli_js, "quota", "--refresh", "--json"],
                        timeout=25, env=antigravity_manager.provider_route_environment()
                    )
            except Exception:
                pass

    threading.Thread(target=bg_refresher, daemon=True).start()

    webview.start(icon=icon_str)


if __name__ == "__main__":
    run_webview_app()
