"""Measured provider routing. Probes never include provider tokens or generation requests."""

from __future__ import annotations

import copy
import hashlib
import http.client
import json
import ssl
import statistics
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse

DEFAULT_HOSTS = {
    "google": ("daily-cloudcode-pa.googleapis.com", "cloudcode-pa.googleapis.com"),
    "openai": ("api.openai.com", "chatgpt.com"), "claude-pro": ("claude.ai",),
    "xpiki": ("api.xpiki.com",), "openrouter-free": ("openrouter.ai",),
    "deepseek-account": ("api.deepseek.com",),
    "tokenlavka": ("tokenlavka.com",),
    "nvidia-nim": ("integrate.api.nvidia.com",),
}
REFRESH_SECONDS = 60
PROBE_SECONDS = 6
RETRY_SECONDS = 10
PROBE_WORKERS = 8


class AutoRouteUnavailable(OSError):
    pass


def configured_routes(hub, provider=None):
    """Only explicitly configured transports; direct connections are opt-in manual routes."""
    from provider_proxy import _get_candidate_proxies, _vless_upstream

    routes = []
    if hub.get("vless_enabled") and hub.get("vless_url"):
        routes.append(("vless", _vless_upstream(hub)))
        modes = hub.get("provider_routes")
        mode = modes.get(provider, "default") if isinstance(modes, dict) else "default"
        # The UI switch protects only Claude Auto; explicitly selected modes
        # are handled independently by the dispatcher.
        if provider == "claude-pro" and mode in ("default", "auto") and hub.get("vless_kill_switch") is not False:
            return routes
    if hub.get("dns_mode") in ("standard", "dot", "doh"):
        routes.append(("dns", "dns://hub"))
    existing = {upstream for _, upstream in routes}
    proxies = _get_candidate_proxies(hub)
    if not hub.get("proxy_failover", True):
        proxies = proxies[:1]
    routes.extend(("proxy", url) for url in proxies if url not in existing)
    return routes


def probe_hosts(provider, opencode):
    names = (provider,)
    if provider == "deepseek-account":
        # OpenCode usually registers this provider simply as "deepseek".
        names = ("deepseek-account", "deepseek")
    for section in ("provider", "providers"):
        sec_data = opencode.get(section)
        if not isinstance(sec_data, dict):
            continue
        for name in names:
            data = sec_data.get(name)
            if not isinstance(data, dict):
                continue
            for key in ("options", "settings"):
                options = data.get(key) or {}
                if not isinstance(options, dict):
                    continue
                host = urlparse(options.get("baseURL") or options.get("baseUrl") or "").hostname
                if host and host not in ("127.0.0.1", "localhost", "::1"):
                    return (host,)
    if provider == "deepseek-account":
        # Respect a custom Base URL saved in the Hub's DeepSeek tab.
        try:
            import deepseek_api
            host = urlparse(deepseek_api.api_origin()).hostname
            if host and host not in ("127.0.0.1", "localhost", "::1"):
                return (host,)
        except Exception:
            pass
    return DEFAULT_HOSTS.get(provider, ())


class AutoRouter:
    def __init__(self, connector, probe=None, clock=time.monotonic, *, vless_ready=None, vless_revision=None):
        self._connector = connector
        self._probe = probe or self._probe_https
        self._clock = clock
        self._vless_ready = vless_ready
        self._vless_revision = vless_revision
        self._lock = threading.RLock()
        self._entries = {}

    def _key(self, provider, hub, opencode):
        keys = ("vless_enabled", "vless_url", "vless_http_port", "dns_mode", "custom_dns", "dot_host", "doh_url")
        routes = configured_routes(hub, provider)
        revision = self._vless_revision() if self._vless_revision and any(mode == "vless" for mode, _ in routes) else None
        data = [{key: hub.get(key) for key in keys}, routes, revision,
                bool(hub.get("proxy_failover", True)), probe_hosts(provider, opencode)]
        return provider, hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()

    def _probe_https(self, upstream, host, hub):
        started = self._clock()
        raw = tls = response = None
        try:
            raw = self._connector(upstream, host, 443, hub_config=hub, timeout=PROBE_SECONDS)
            remaining = PROBE_SECONDS - (self._clock() - started)
            if remaining <= 0:
                raise TimeoutError()
            raw.settimeout(remaining)
            tls = ssl.create_default_context().wrap_socket(raw, server_hostname=host)
            remaining = PROBE_SECONDS - (self._clock() - started)
            if remaining <= 0:
                raise TimeoutError()
            tls.settimeout(remaining)
            path = "/backend-api/wham/usage" if host == "chatgpt.com" else "/api/v1/models" if host == "openrouter.ai" else "/v1/models" if host == "api.openai.com" else "/"
            tls.sendall((f"GET {path} HTTP/1.1\r\nHost: {host}\r\nUser-Agent: AntigravityHub-RouteProbe\r\nConnection: close\r\n\r\n").encode("ascii"))
            response = http.client.HTTPResponse(tls)
            response.begin()
            # Authentication-required / missing GET handlers prove that HTTPS
            # reached the service. Geoblocks, gateway failures and 5xx do not.
            ok = 200 <= response.status < 400 or response.status in (401, 404, 405, 429)
            return {"host": host, "ok": ok, "http_status": response.status,
                    "latency_ms": round((self._clock() - started) * 1000, 1),
                    "error": None if ok else f"HTTP {response.status}"}
        except Exception as exc:
            return {"host": host, "ok": False, "latency_ms": None, "error": type(exc).__name__}
        finally:
            if response is not None:
                response.close()
            if tls is not None:
                tls.close()
            elif raw is not None:
                raw.close()

    def _measure(self, mode, upstream, hosts, hub):
        checks = []
        for host in hosts:
            try:
                checks.append(self._probe(upstream, host, hub))
            except Exception as exc:
                checks.append({"host": host, "ok": False, "latency_ms": None, "error": type(exc).__name__})
        return self._summarize(mode, checks)

    @staticmethod
    def _summarize(mode, checks):
        successful = [check for check in checks if check.get("ok")]
        latencies = [check["latency_ms"] for check in successful if check.get("latency_ms") is not None]
        return {"mode": mode, "available": bool(successful), "passed": len(successful),
                "total": len(checks), "latency_ms": statistics.median(latencies) if latencies else None,
                "checks": checks}

    def _rank(self, entry, host=None):
        """Rank transports by measurements, keeping candidate priority within a transport."""
        by_mode = {}
        now = self._clock()
        failures = entry["failed_hosts"]
        for upstream, row in entry["rows"]:
            if row["available"] and row["mode"] == "vless" and self._vless_ready and not self._vless_ready(upstream):
                if host is not None:
                    continue
                row = self._summarize("vless", [dict(check, ok=False, latency_ms=None, error="VlessUnavailable")
                                                for check in row["checks"]])
            if host is not None and failures.get((upstream, host), 0) > now:
                continue
            checks = row["checks"]
            if host is None:
                checks = [dict(check, ok=False, latency_ms=None, error="ConnectionFailed")
                          if failures.get((upstream, check["host"]), 0) > now else check
                          for check in checks]
                row = self._summarize(row["mode"], checks)
            elif any(check["host"] == host and not check.get("ok") for check in checks):
                # A partial result can still serve the hosts that passed.
                continue
            by_mode.setdefault(row["mode"], []).append((upstream, row))

        groups = [[item for item in group if item[1]["available"]] for group in by_mode.values()]

        def score(group):
            row = group[0][1]
            return -row["passed"], row["latency_ms"] if row["latency_ms"] is not None else float("inf")

        ranked = [item for group in sorted(filter(None, groups), key=score) for item in group]
        return ranked, by_mode

    def refresh(self, provider, hub, opencode, force=False):
        key = self._key(provider, hub, opencode)
        with self._lock:
            entry = self._entries.get(key)
            if entry and (entry["running"] or (not force and self._clock() < entry["expires"])):
                return entry["event"]
            if entry is None:
                entry = {"running": False, "rows": [], "checkedAt": None,
                         "expires": 0, "event": threading.Event(), "failed_hosts": {}}
                self._entries[key] = entry
            entry["running"] = True
            entry["event"].clear()
            # Expired configurations must not grow the cache indefinitely.
            for old in list(self._entries):
                if len(self._entries) <= 64:
                    break
                if old != key and not self._entries[old]["running"]:
                    del self._entries[old]
        threading.Thread(target=self._refresh, args=(entry, provider, copy.deepcopy(hub), copy.deepcopy(opencode)),
                         daemon=True, name=f"auto-route-{provider}").start()
        return entry["event"]

    def _refresh(self, entry, provider, hub, opencode):
        try:
            routes = configured_routes(hub, provider)
            hosts = probe_hosts(provider, opencode)
            rows = []
            if routes and hosts:
                with ThreadPoolExecutor(max_workers=min(PROBE_WORKERS, len(routes))) as pool:
                    futures = [(upstream, pool.submit(self._measure, mode, upstream, hosts, hub))
                               for mode, upstream in routes]
                    rows = [(upstream, future.result()) for upstream, future in futures]
            with self._lock:
                entry["failed_hosts"] = {key: until for key, until in entry["failed_hosts"].items() if until > self._clock()}
                entry.update(rows=rows, checkedAt=time.time())
                ranked, _ = self._rank(entry)
                entry["expires"] = self._clock() + (REFRESH_SECONDS if ranked else RETRY_SECONDS)
        except Exception:
            with self._lock:
                entry["expires"] = self._clock() + RETRY_SECONDS
        finally:
            with self._lock:
                entry["running"] = False
                entry["event"].set()

    def state(self, provider, hub, opencode):
        with self._lock:
            entry = self._entries.get(self._key(provider, hub, opencode))
            if entry is None:
                return {"selected": None, "running": False, "rows": [], "checkedAt": None,
                         "status": "pending" if configured_routes(hub, provider) else "not-configured"}
            ranked, by_mode = self._rank(entry)
            selected = ranked[0][1]["mode"] if ranked else None
            # Keep one credential-free UI row per transport, even when Auto has
            # measured several proxy candidates.
            rows = [next((row for _, row in group if row["available"]), group[0][1])
                    for group in by_mode.values()]
            return {"selected": selected, "running": entry["running"],
                    "rows": copy.deepcopy(rows), "checkedAt": entry["checkedAt"],
                    "status": "ready" if selected else "checking" if entry["running"]
                    else "unavailable" if configured_routes(hub, provider) else "not-configured"}

    def selected_upstream(self, provider, hub, opencode, *, host=None):
        if host is not None:
            host = host.lower().rstrip(".")
        key = self._key(provider, hub, opencode)
        with self._lock:
            entry = self._entries.get(key)
            if entry:
                ranked, _ = self._rank(entry, host)
                if ranked:
                    return ranked[0][0]
        raise AutoRouteUnavailable("Auto: маршрут ещё не выбран или все настроенные маршруты недоступны")

    def connect(self, provider, host, port, hub, opencode):
        if not configured_routes(hub, provider):
            raise AutoRouteUnavailable("Auto: настройте VLESS, DNS или HTTP-прокси")
        route_host = host.lower().rstrip(".")
        ready = self.refresh(provider, hub, opencode)
        key = self._key(provider, hub, opencode)

        def candidates():
            with self._lock:
                entry = self._entries.get(key)
                ranked, _ = self._rank(entry, route_host) if entry else ([], {})
                return entry, [upstream for upstream, _ in ranked]

        entry, upstreams = candidates()
        if not upstreams:
            if not ready.wait(PROBE_SECONDS * max(1, len(probe_hosts(provider, opencode))) + 2):
                raise AutoRouteUnavailable("Auto: проверка маршрутов ещё выполняется")
            entry, upstreams = candidates()
        if not upstreams:
            raise AutoRouteUnavailable("Auto: все настроенные маршруты недоступны")
        # Retry only before opening the tunnel to the client. No HTTP request
        # body or generation is ever replayed after a connection has opened.
        for upstream in upstreams:
            try:
                return self._connector(upstream, host, port, hub_config=hub, timeout=20), upstream
            except Exception:
                with self._lock:
                    if entry:
                        retry_at = self._clock() + RETRY_SECONDS
                        entry["failed_hosts"][(upstream, route_host)] = retry_at
                        entry["expires"] = min(entry["expires"], retry_at)
        raise AutoRouteUnavailable("Auto: не удалось подключиться ни по одному проверенному маршруту")


def _connector(*args, **kwargs):
    import provider_proxy
    hub = kwargs["hub_config"]
    if hub.get("vless_enabled") and hub.get("vless_url") and args[0] == provider_proxy._vless_upstream(hub):
        return provider_proxy._connect_vless(*args, **kwargs)
    return provider_proxy._connect_upstream(*args, **kwargs)


def _vless_ready(upstream):
    import provider_proxy
    return provider_proxy._managed_vless_ready(upstream)


def _vless_revision():
    from vless_manager import vless_service
    return vless_service.exit_generation()


router = AutoRouter(_connector, vless_ready=_vless_ready, vless_revision=_vless_revision)
