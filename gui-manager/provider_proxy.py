"""Loopback HTTP proxy that selects an upstream using provider host routes."""

from __future__ import annotations

import base64
import json
import os
import select
import socket
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

HOST = "127.0.0.1"
PORT = 10880
CONFIG_DIR = Path.home() / ".config" / "opencode"
LOCAL_ROUTES = {"google": ("googleapis.com", "google.com", "googleusercontent.com"),
                "openai": ("openai.com", "chatgpt.com"),
                "claude-pro": ("claude.ai", "anthropic.com"),
                "openrouter-free": ("openrouter.ai",),
                "mwapi": ("mwapi.dev",),
                "xpiki": ("xpiki.com",),
                "deepseek-account": ("deepseek.com",),
                "deepseek-web": ("deepseek.com",)}
_server = None
_thread = None
_dns_lock = threading.Lock()
_proxy_pool_lock = threading.Lock()
_proxy_pool_index = 0
_proxy_failures = {}


def _get_candidate_proxies(hub: dict) -> list[str]:
    """Return a list of external proxies from the proxy pool or fallback proxy."""
    pool = hub.get("proxy_pool")
    candidates = []
    if isinstance(pool, list):
        for item in pool:
            url = (item.get("url") if isinstance(item, dict) else str(item)).strip()
            if url and url not in candidates and url != "http://127.0.0.1:51180" and url != f"http://{HOST}:{PORT}":
                candidates.append(url)
    fallback = str(hub.get("proxy") or "").strip()
    if fallback and fallback not in candidates and fallback != "http://127.0.0.1:51180" and fallback != f"http://{HOST}:{PORT}":
        candidates.append(fallback)
    return candidates


def _hub_upstream_proxy(hub: dict) -> str | None:
    """Hub-level proxy from config, ignoring its own route dispatcher (no self-loop)."""
    candidates = _get_candidate_proxies(hub)
    if not candidates:
        return None
    global _proxy_pool_index
    with _proxy_pool_lock:
        idx = _proxy_pool_index % len(candidates)
        return candidates[idx]
def _read_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _host_for_provider(provider: dict) -> str | None:
    for section in ("options", "settings"):
        opts = provider.get(section)
        if isinstance(opts, dict):
            base_url = opts.get("baseURL") or opts.get("baseUrl")
            if isinstance(base_url, str):
                try:
                    return (urlparse(base_url).hostname or "").lower() or None
                except ValueError:
                    pass
    return None


def _matches(host: str, domain: str) -> bool:
    return host == domain or host.endswith("." + domain)


def provider_for_host(host: str, opencode_config: dict | None = None) -> str | None:
    """Resolve common built-in and configured provider hosts to provider IDs."""
    host = host.split(":", 1)[0].strip("[]").lower()
    config = opencode_config if isinstance(opencode_config, dict) else _read_json(CONFIG_DIR / "opencode.json")
    names: list[str] = []
    domains: dict[str, list[str]] = {}
    for section_name in ("provider", "providers"):
        section = config.get(section_name, {})
        if not isinstance(section, dict):
            continue
        for name, provider in section.items():
            if not isinstance(provider, dict):
                continue
            if name not in names:
                names.append(name)
            domains.setdefault(name, [])
            base_host = _host_for_provider(provider)
            if base_host:
                domains[name].append(base_host)
            domains[name].extend(LOCAL_ROUTES.get(name.lower(), ()))
    matches = [(len(domain), name) for name, values in domains.items()
               for domain in values if domain and _matches(host, domain)]
    return max(matches)[1] if matches else None


def select_upstream(host: str, hub_config: dict | None = None,
                    opencode_config: dict | None = None) -> str | None:
    """Return an HTTP proxy URL, or None for a direct connection."""
    hub = hub_config if isinstance(hub_config, dict) else _read_json(CONFIG_DIR / "antigravity.json")
    oc = opencode_config if isinstance(opencode_config, dict) else _read_json(CONFIG_DIR / "opencode.json")
    provider = provider_for_host(host, oc)
    routes = hub.get("provider_routes", {})
    mode = routes.get(provider, "default") if isinstance(routes, dict) else "default"
    http_port = hub.get("vless_http_port", 10879)

    if mode == "google-smart":
        from google_smart_dns import GATE_HOSTS
        if host.lower().rstrip(".") in GATE_HOSTS:
            return "smartdns://google"
        # OAuth and other Google hosts keep the normal route.
        return _legacy_upstream(hub)

    if mode == "direct":
        return None
    if mode == "proxy":
        return _hub_upstream_proxy(hub)
    if mode == "vless":
        return f"http://127.0.0.1:{http_port}"
    if mode == "dns":
        return "dns://hub"

    if provider:
        from auto_router import router
        router.refresh(provider, hub, oc)
        return router.selected_upstream(provider, hub, oc)
    return _legacy_upstream(hub)


def _legacy_upstream(hub):
    # Unknown, non-provider hosts retain the Hub's ordinary system routing.
    if hub.get("vless_enabled") and hub.get("vless_url"):
        return f"http://127.0.0.1:{hub.get('vless_http_port', 10879)}"
    if external := _hub_upstream_proxy(hub):
        return external
    if hub.get("dns_mode") in ("standard", "dot", "doh"):
        return "dns://hub"
    return None


def connect_routed(host, port, hub_config=None, opencode_config=None):
    hub = hub_config if isinstance(hub_config, dict) else _read_json(CONFIG_DIR / "antigravity.json")
    oc = opencode_config if isinstance(opencode_config, dict) else _read_json(CONFIG_DIR / "opencode.json")
    provider = provider_for_host(host, oc)
    mode = hub.get("provider_routes", {}).get(provider, "default")
    if provider and mode in ("default", "auto"):
        from auto_router import router
        return router.connect(provider, host, port, hub, oc)

    upstream = select_upstream(host, hub, oc)

    # If routing through external proxy and failover/rotation is enabled, try pool candidates
    candidates = _get_candidate_proxies(hub)
    if upstream in candidates and len(candidates) > 1 and hub.get("proxy_failover", True):
        global _proxy_pool_index
        last_error = None
        with _proxy_pool_lock:
            start_idx = _proxy_pool_index % len(candidates)

        for attempt in range(len(candidates)):
            cand_idx = (start_idx + attempt) % len(candidates)
            cand_url = candidates[cand_idx]
            try:
                sock = _connect_upstream(cand_url, host, port, hub_config=hub)
                with _proxy_pool_lock:
                    _proxy_pool_index = cand_idx
                return sock, cand_url
            except Exception as e:
                last_error = e
                continue
        if last_error:
            raise last_error

    return _connect_upstream(upstream, host, port, hub_config=hub), upstream


def _resolve_with_hub_dns(host: str, hub_config=None, timeout=8) -> str:
    import dns_tester

    hub = hub_config if isinstance(hub_config, dict) else _read_json(CONFIG_DIR / "antigravity.json")
    mode = hub.get("dns_mode", "system")
    if mode == "system":
        return host
    deadline = time.monotonic() + timeout
    if mode == "doh":
        query = dns_tester._build_dns_query(host)
        request = urllib.request.Request(hub.get("doh_url", ""), data=query,
            headers={"Content-Type": "application/dns-message", "Accept": "application/dns-message"}, method="POST")
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(request, timeout=timeout) as response:
            answer = dns_tester._parse_a_record_ip(response.read())
        result = {"ok": bool(answer), "resolved_ip": answer}
    elif mode == "dot":
        result = dns_tester.test_dot_endpoint(hub.get("dot_host", ""), timeout=timeout, domain=host)
    else:
        servers = hub.get("custom_dns") or ["143.20.64.55"]
        result = {}
        for server in servers:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            result = dns_tester.test_standard_dns(server, timeout=min(3, remaining), domain=host)
            if result.get("ok") and result.get("resolved_ip") not in (None, "OK"):
                break
    resolved = result.get("resolved_ip") if isinstance(result, dict) and result.get("ok") else None
    if not resolved or resolved == "OK":
        raise OSError("Hub DNS could not resolve target")
    return resolved


def _connect_upstream(proxy_url: str | None, target_host: str, target_port: int,
                      hub_config=None, timeout=20) -> socket.socket:
    if proxy_url == "smartdns://google":
        import google_smart_dns
        return google_smart_dns.connect(target_host, target_port,
            hub_config if isinstance(hub_config, dict) else _read_json(CONFIG_DIR / "antigravity.json"))
    deadline = time.monotonic() + timeout
    upstream = None
    def remaining():
        budget = deadline - time.monotonic()
        if budget <= 0:
            raise TimeoutError("Upstream connection timed out")
        return budget
    try:
        if not proxy_url or proxy_url == "dns://hub":
            resolved = _resolve_with_hub_dns(target_host, hub_config, remaining()) if proxy_url else target_host
            upstream = socket.create_connection((resolved, target_port), timeout=remaining())
        else:
            parsed = urlparse(proxy_url)
            proxy_host = parsed.hostname or "127.0.0.1"
            proxy_port = parsed.port or (443 if parsed.scheme == "https" else 80)
            upstream = socket.create_connection((proxy_host, proxy_port), timeout=remaining())
            if parsed.scheme == "https":
                import ssl
                upstream.settimeout(remaining())
                upstream = ssl.create_default_context().wrap_socket(upstream, server_hostname=proxy_host)
            auth = ""
            if parsed.username is not None:
                from urllib.parse import unquote
                credentials = f"{unquote(parsed.username)}:{unquote(parsed.password or '')}".encode()
                auth = "Proxy-Authorization: Basic " + base64.b64encode(credentials).decode("ascii") + "\r\n"
            request = (f"CONNECT {target_host}:{target_port} HTTP/1.1\r\n"
                       f"Host: {target_host}:{target_port}\r\n{auth}Connection: Keep-Alive\r\n\r\n")
            upstream.settimeout(remaining())
            upstream.sendall(request.encode("ascii"))
            response = b""
            while b"\r\n\r\n" not in response and len(response) < 65536:
                upstream.settimeout(remaining())
                part = upstream.recv(4096)
                if not part:
                    break
                response += part
            if not response.startswith(b"HTTP/1.0 200") and not response.startswith(b"HTTP/1.1 200"):
                raise OSError("Upstream proxy refused CONNECT")
        upstream.settimeout(None)
        return upstream
    except Exception:
        if upstream is not None:
            upstream.close()
        raise


def _relay(left: socket.socket, right: socket.socket) -> None:
    sockets = [left, right]
    try:
        while sockets:
            readable, _, exceptional = select.select(sockets, [], sockets)
            if exceptional:
                return
            for src in readable:
                dst = right if src is left else left
                chunk = src.recv(65536)
                if not chunk:
                    return
                dst.sendall(chunk)
    except OSError:
        pass
    finally:
        for sock in (left, right):
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                sock.close()
            except OSError:
                pass


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def do_GET(self):
        if self.path == "/_antigravity_provider_proxy_health":
            body = b"antigravity-provider-proxy"
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self._plain_http()

    def do_CONNECT(self):
        host, _, port = self.path.rpartition(":")
        try:
            target_port = int(port) if port else 443
            if host in (HOST, "localhost") and target_port == PORT:
                raise OSError("Proxy loop")
            upstream, _ = connect_routed(host, target_port)
            self.send_response(200, "Connection Established")
            self.end_headers()
            _relay(self.connection, upstream)
        except Exception:
            try:
                self.send_error(502, "Unable to establish routed connection")
            except OSError:
                pass

    def _plain_http(self):
        parsed = urlparse(self.path)
        host = parsed.hostname or self.headers.get("Host", "")
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        try:
            upstream, _ = connect_routed(host, port)
            path = (parsed.path or "/") + (("?" + parsed.query) if parsed.query else "")
            request = f"{self.command} {path} {self.request_version}\r\n"
            for key, value in self.headers.items():
                if key.lower() not in ("proxy-authorization", "proxy-connection"):
                    request += f"{key}: {value}\r\n"
            upstream.sendall((request + "\r\n").encode("latin-1"))
            length = int(self.headers.get("Content-Length", "0") or 0)
            if length:
                upstream.sendall(self.rfile.read(length))
            _relay(self.connection, upstream)
        except Exception:
            try:
                self.send_error(502, "Unable to establish routed connection")
            except OSError:
                pass

    do_POST = _plain_http
    do_PUT = _plain_http
    do_DELETE = _plain_http
    do_PATCH = _plain_http


class _ThreadingServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def start() -> bool:
    global _server, _thread
    if _server is not None:
        _install_process_proxy_environment()
        return True
    try:
        _server = _ThreadingServer((HOST, PORT), _Handler)
        _thread = threading.Thread(target=_server.serve_forever, daemon=True, name="provider-route-proxy")
        _thread.start()
        threading.Thread(target=_maintain_auto_routes, daemon=True, name="provider-auto-routes").start()
        _install_process_proxy_environment()
        return True
    except OSError:
        # A listener already on the dedicated port might belong to an existing Hub instance.
        try:
            with socket.create_connection((HOST, PORT), timeout=0.3) as probe:
                probe.sendall(b"GET /_antigravity_provider_proxy_health HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n")
                response = probe.recv(512)
            if b"antigravity-provider-proxy" in response:
                _install_process_proxy_environment()
                return True
        except OSError:
            pass
        return False


def _maintain_auto_routes():
    from auto_router import router
    visibility_keys = {"google":"antigravity", "claude-pro":"claude", "openrouter-free":"openrouter"}
    while True:
        try:
            hub = _read_json(CONFIG_DIR / "antigravity.json")
            oc = _read_json(CONFIG_DIR / "opencode.json")
            names = set(oc.get("provider", {})) | set(oc.get("providers", {}))
            for name in names:
                enabled = hub.get("providers_visibility", {}).get(visibility_keys.get(name, name), True)
                if enabled and name not in oc.get("disabled_providers", []) and hub.get("provider_routes", {}).get(name, "default") in ("default", "auto"):
                    router.refresh(name, hub, oc)
        except Exception:
            pass
        time.sleep(5)


def _install_process_proxy_environment() -> None:
    proxy = f"http://{HOST}:{PORT}"
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        os.environ[name] = proxy
    for name in ("NO_PROXY", "no_proxy"):
        os.environ[name] = "localhost,127.0.0.1,::1"


def proxy_url_for_hub_requests() -> str:
    if not start():
        raise OSError("Provider route proxy is unavailable")
    return f"http://{HOST}:{PORT}"


def proxy_environment(base: dict | None = None) -> dict:
    env = dict(os.environ if base is None else base)
    proxy = proxy_url_for_hub_requests()
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        env[name] = proxy
    env["NO_PROXY"] = "localhost,127.0.0.1,::1"
    env["no_proxy"] = env["NO_PROXY"]
    return env
