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
    "openai": ("chatgpt.com",), "claude-pro": ("claude.ai",),
    "xpiki": ("api.xpiki.com",), "openrouter-free": ("openrouter.ai",),
}
REFRESH_SECONDS = 60
PROBE_SECONDS = 6


class AutoRouteUnavailable(OSError):
    pass


def configured_routes(hub):
    """Only explicitly configured transports; direct and experimental SmartDNS are opt-in manual routes."""
    routes = []
    if hub.get("vless_enabled") and hub.get("vless_url"):
        routes.append(("vless", f"http://127.0.0.1:{hub.get('vless_http_port', 10879)}"))
    if hub.get("dns_mode") in ("standard", "dot", "doh"):
        routes.append(("dns", "dns://hub"))
    proxy = str(hub.get("proxy") or "").strip()
    try:
        parsed = urlparse(proxy)
        proxy_port = parsed.port
    except ValueError:
        return routes
    if parsed.scheme in ("http", "https") and parsed.hostname:
        local = parsed.hostname.lower() in ("127.0.0.1", "localhost", "::1")
        own_port = local and proxy_port in (10880, 51180)
        if not own_port and proxy not in [upstream for _, upstream in routes]:
            routes.append(("proxy", proxy))
    return routes


def probe_hosts(provider, opencode):
    for section in ("provider", "providers"):
        data = opencode.get(section, {}).get(provider, {})
        for key in ("options", "settings"):
            options = data.get(key) or {}
            host = urlparse(options.get("baseURL") or options.get("baseUrl") or "").hostname
            if host and host not in ("127.0.0.1", "localhost", "::1"):
                return (host,)
    return DEFAULT_HOSTS.get(provider, ())


class AutoRouter:
    def __init__(self, connector, probe=None, clock=time.monotonic):
        self._connector = connector
        self._probe = probe or self._probe_https
        self._clock = clock
        self._lock = threading.RLock()
        self._entries = {}

    def _key(self, provider, hub, opencode):
        keys = ("vless_enabled", "vless_url", "vless_http_port", "dns_mode", "custom_dns", "dot_host", "doh_url", "proxy")
        data = [{key: hub.get(key) for key in keys}, probe_hosts(provider, opencode)]
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
            path = "/backend-api/wham/usage" if host == "chatgpt.com" else "/api/v1/models" if host == "openrouter.ai" else "/"
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
        successful = [check for check in checks if check.get("ok")]
        latencies = [check["latency_ms"] for check in successful if check.get("latency_ms") is not None]
        return {"mode": mode, "available": bool(successful), "passed": len(successful),
                "total": len(checks), "latency_ms": statistics.median(latencies) if latencies else None,
                "checks": checks}

    @staticmethod
    def _rank(rows):
        return sorted((row for row in rows if row["available"]),
                      key=lambda row: (-row["passed"], row["latency_ms"] if row["latency_ms"] is not None else float("inf")))

    def refresh(self, provider, hub, opencode, force=False):
        key = self._key(provider, hub, opencode)
        with self._lock:
            entry = self._entries.get(key)
            if entry and (entry["running"] or (not force and self._clock() < entry["expires"])):
                return entry["event"]
            if entry is None:
                entry = {"running": False, "rows": [], "selected": None, "checkedAt": None,
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
            routes = configured_routes(hub)
            hosts = probe_hosts(provider, opencode)
            rows = []
            if routes and hosts:
                with ThreadPoolExecutor(max_workers=len(routes)) as pool:
                    futures = [pool.submit(self._measure, mode, upstream, hosts, hub) for mode, upstream in routes]
                    rows = [future.result() for future in futures]
            ranked = self._rank(rows)
            with self._lock:
                entry["failed_hosts"] = {key: until for key, until in entry["failed_hosts"].items() if until > self._clock()}
                entry.update(rows=rows, selected=ranked[0]["mode"] if ranked else None,
                             checkedAt=time.time(), expires=self._clock() + (REFRESH_SECONDS if ranked else 10))
        finally:
            with self._lock:
                entry["running"] = False
                entry["event"].set()

    def state(self, provider, hub, opencode):
        with self._lock:
            entry = self._entries.get(self._key(provider, hub, opencode))
            if entry is None:
                return {"selected": None, "running": False, "rows": [], "checkedAt": None,
                        "status": "pending" if configured_routes(hub) else "not-configured"}
            return {"selected": entry["selected"], "running": entry["running"],
                    "rows": copy.deepcopy(entry["rows"]), "checkedAt": entry["checkedAt"],
                    "status": "ready" if entry["selected"] else "checking" if entry["running"]
                    else "unavailable" if configured_routes(hub) else "not-configured"}

    def selected_upstream(self, provider, hub, opencode):
        state = self.state(provider, hub, opencode)
        routes = dict(configured_routes(hub))
        if state["selected"] in routes:
            return routes[state["selected"]]
        raise AutoRouteUnavailable("Auto: маршрут ещё не выбран или все настроенные маршруты недоступны")

    def connect(self, provider, host, port, hub, opencode):
        routes = dict(configured_routes(hub))
        if not routes:
            raise AutoRouteUnavailable("Auto: настройте VLESS, DNS или HTTP-прокси")
        ready = self.refresh(provider, hub, opencode)
        state = self.state(provider, hub, opencode)
        if not state["selected"]:
            if not ready.wait(PROBE_SECONDS * max(1, len(probe_hosts(provider, opencode))) + 2):
                raise AutoRouteUnavailable("Auto: проверка маршрутов ещё выполняется")
        key = self._key(provider, hub, opencode)
        with self._lock:
            entry = self._entries.get(key)
            ranked = self._rank(entry["rows"]) if entry else []
            # A partial provider result must not send a request to a host
            # that this particular route already failed to reach over HTTPS.
            ranked = [row for row in ranked if not any(check.get("host") == host and not check.get("ok")
                                                       for check in row["checks"])]
            ranked = [row for row in ranked if entry["failed_hosts"].get((row["mode"], host), 0) <= self._clock()]
        if not ranked:
            raise AutoRouteUnavailable("Auto: все настроенные маршруты недоступны")
        # Retry only before opening the tunnel to the client. No HTTP request
        # body or generation is ever replayed after a connection has opened.
        for row in ranked:
            mode = row["mode"]
            try:
                conn = self._connector(routes[mode], host, port, hub_config=hub, timeout=PROBE_SECONDS)
                with self._lock:
                    if entry and host in probe_hosts(provider, opencode) and any(
                            result["mode"] == mode and result["available"] for result in entry["rows"]):
                        entry["selected"] = mode
                return conn, routes[mode]
            except Exception:
                with self._lock:
                    if entry:
                        entry["failed_hosts"][(mode, host)] = self._clock() + 10
                        if host in probe_hosts(provider, opencode):
                            for result in entry["rows"]:
                                if result["mode"] == mode:
                                    result.update(available=False, passed=0)
                            alternatives = self._rank(entry["rows"])
                            entry["selected"] = alternatives[0]["mode"] if alternatives else None
                        entry["expires"] = min(entry["expires"], self._clock() + 10)
        raise AutoRouteUnavailable("Auto: не удалось подключиться ни по одному проверенному маршруту")


def _connector(*args, **kwargs):
    import provider_proxy
    return provider_proxy._connect_upstream(*args, **kwargs)


router = AutoRouter(_connector)
