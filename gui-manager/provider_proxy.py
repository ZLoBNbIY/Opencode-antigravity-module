"""Loopback HTTP proxy that selects an upstream using provider host routes."""

from __future__ import annotations

import base64
import json
import os
import select
import socket
import threading
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

    if mode == "direct":
        return None
    if mode == "vless":
        return f"http://127.0.0.1:{http_port}"
    if mode == "dns":
        return "dns://hub"
    if mode == "proxy":
        external = str(hub.get("proxy") or "").strip()
        return external if external and external != "http://127.0.0.1:51180" else None

    if hub.get("vless_enabled") and hub.get("vless_url"):
        return f"http://127.0.0.1:{http_port}"
    external = str(hub.get("proxy") or "").strip()
    if external and external != "http://127.0.0.1:51180":
        return external
    if hub.get("dns_mode") in ("standard", "dot", "doh"):
        return "dns://hub"
    return None


def _resolve_with_hub_dns(host: str) -> str:
    import dns_tester

    hub = _read_json(CONFIG_DIR / "antigravity.json")
    mode = hub.get("dns_mode", "system")
    if mode == "system":
        return host
    with _dns_lock:
        previous = dns_tester.DOMAIN_TO_TEST
        dns_tester.DOMAIN_TO_TEST = host
        try:
            if mode == "doh":
                url = str(hub.get("doh_url", "")).strip()
                query = dns_tester._build_dns_query(host)
                request = urllib.request.Request(
                    url, data=query,
                    headers={"Content-Type": "application/dns-message", "Accept": "application/dns-message"},
                    method="POST",
                )
                opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
                with opener.open(request, timeout=8) as response:
                    answer = dns_tester._parse_a_record_ip(response.read())
                result = {"ok": bool(answer), "resolved_ip": answer}
            elif mode == "dot":
                result = dns_tester.test_dot_endpoint(hub.get("dot_host", ""), timeout=8)
            else:
                servers = hub.get("custom_dns", [])
                server = servers[0] if servers else "143.20.64.55"
                result = dns_tester.test_standard_dns(server, timeout=5)
        finally:
            dns_tester.DOMAIN_TO_TEST = previous
    resolved = result.get("resolved_ip") if isinstance(result, dict) and result.get("ok") else None
    if not resolved or resolved == "OK":
        raise OSError("Hub DNS could not resolve target")
    return resolved


def _connect_upstream(proxy_url: str | None, target_host: str, target_port: int) -> socket.socket:
    if not proxy_url:
        upstream = socket.create_connection((target_host, target_port), timeout=20)
        upstream.settimeout(None)
        return upstream
    if proxy_url == "dns://hub":
        resolved = _resolve_with_hub_dns(target_host)
        upstream = socket.create_connection((resolved, target_port), timeout=20)
        upstream.settimeout(None)
        return upstream
    parsed = urlparse(proxy_url)
    proxy_host = parsed.hostname or "127.0.0.1"
    proxy_port = parsed.port or (443 if parsed.scheme == "https" else 80)
    upstream = socket.create_connection((proxy_host, proxy_port), timeout=20)
    if parsed.scheme == "https":
        import ssl
        upstream = ssl.create_default_context().wrap_socket(upstream, server_hostname=proxy_host)
    auth = ""
    if parsed.username is not None:
        credentials = f"{parsed.username}:{parsed.password or ''}".encode()
        auth = "Proxy-Authorization: Basic " + base64.b64encode(credentials).decode("ascii") + "\r\n"
    request = (f"CONNECT {target_host}:{target_port} HTTP/1.1\r\n"
               f"Host: {target_host}:{target_port}\r\n{auth}Connection: Keep-Alive\r\n\r\n")
    upstream.sendall(request.encode("ascii"))
    response = b""
    while b"\r\n\r\n" not in response and len(response) < 65536:
        part = upstream.recv(4096)
        if not part:
            break
        response += part
    if not response.startswith(b"HTTP/1.0 200") and not response.startswith(b"HTTP/1.1 200"):
        upstream.close()
        raise OSError("Upstream proxy refused CONNECT")
    upstream.settimeout(None)
    return upstream


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
            upstream = _connect_upstream(select_upstream(host), host, target_port)
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
        proxy = select_upstream(host)
        try:
            upstream = _connect_upstream(proxy, host, port)
            path = self.path if proxy else (parsed.path or "/") + (("?" + parsed.query) if parsed.query else "")
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
