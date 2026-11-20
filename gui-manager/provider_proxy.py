"""Loopback HTTP proxy that selects an upstream using provider host routes."""

from __future__ import annotations

import base64
import http.client
import ipaddress
import json
import os
import re
import socket
import ssl
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from contextvars import ContextVar
from pathlib import Path
from urllib.parse import unquote, urlparse, urlsplit

import jsonc_config

HOST = "127.0.0.1"
PORT = 10880
CONFIG_DIR = Path.home() / ".config" / "opencode"
LOCAL_ROUTES = {
    "google": (
        "googleapis.com",
        "google.com",
        "googleusercontent.com",
        "gstatic.com",
        "googlehosted.com",
        "googlevideo.com",
        "gvt1.com",
        "gvt2.com",
        "deepmind.com",
        "google",
    ),
    "openai": (
        "openai.com",
        "chatgpt.com",
        "oaistatic.com",
        "oaiusercontent.com",
    ),
    "claude-pro": (
        "claude.ai",
        "anthropic.com",
        "claudeusercontent.com",
    ),
    "openrouter-free": ("openrouter.ai",),
    "xpiki": ("api.xpiki.com", "xpiki.com"),
    "deepseek-account": ("api.deepseek.com", "platform.deepseek.com"),
    "tokenlavka": ("tokenlavka.com",),
    "nvidia-nim": ("integrate.api.nvidia.com", "nvidia.com"),
}
# Plain-HTTP reverse endpoints: baseURL on the OpenCode side is rewritten to
# http://127.0.0.1:10880/r/<provider>/... so no CONNECT proxy is involved.
REVERSE_PREFIX = "/r/"
PROVIDER_ENDPOINTS = {"tokenlavka": "https://tokenlavka.com/v1"}
# The process proxy is also inherited by OpenCode's updater and package resolver.
APP_HOSTS = {"opencode.ai", "models.dev", "api.github.com", "github.com", "raw.githubusercontent.com",
             "objects.githubusercontent.com", "release-assets.githubusercontent.com",
             "codeload.github.com", "registry.npmjs.org", "registry.npmjs.com"}
MAX_BODY = 16 * 1024 * 1024
HEADER_TIMEOUT = 10
RELAY_IDLE = 120
RELAY_LIFETIME = 600
MAX_RELAY_BYTES = 128 * 1024 * 1024  # per direction
_public_connect_deadline = ContextVar("public_connect_deadline", default=None)
_server = None
_thread = None
_start_lock = threading.Lock()


def _get_candidate_proxies(hub: dict) -> list[str]:
    """Return a list of external proxies from the proxy pool or fallback proxy."""
    pool = hub.get("proxy_pool")
    candidates = []
    if isinstance(pool, list):
        for item in pool:
            url = str((item.get("url") if isinstance(item, dict) else item) or "").strip()
            if url and url not in candidates and url != "http://127.0.0.1:51180" and url != f"http://{HOST}:{PORT}":
                candidates.append(url)
    fallback = str(hub.get("proxy") or "").strip()
    if fallback and fallback not in candidates and fallback != "http://127.0.0.1:51180" and fallback != f"http://{HOST}:{PORT}":
        candidates.append(fallback)
    return candidates


def _hub_upstream_proxy(hub: dict) -> str | None:
    """Return the highest-priority configured proxy, ignoring the dispatcher itself."""
    candidates = _get_candidate_proxies(hub)
    return candidates[0] if candidates else None


def _read_json(path: Path) -> dict:
    try:
        if path.name == "opencode.json":
            path = jsonc_config.config_path(path.parent)
        with path.open(encoding="utf-8-sig") as stream:
            text = stream.read(4 * 1024 * 1024 + 1)
        if len(text) > 4 * 1024 * 1024:
            return {}
        if path.name in ("opencode.json", "opencode.jsonc"):
            return jsonc_config.parse_config(text)
        data = json.loads(text)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _provider_options(config):
    for section in ("provider", "providers"):
        entries = config.get(section)
        if not isinstance(entries, dict):
            continue
        for name, entry in entries.items():
            if isinstance(entry, dict):
                for key in ("options", "settings"):
                    if isinstance(entry.get(key), dict):
                        yield name, entry[key]


# Transparent-proxy resolvers (sing-box, xray, Clash, OpenWrt packages) answer
# with these ranges instead of real addresses. They are intentionally not
# public, but the local resolver routes them through the tunnel, and direct
# connections to allowlisted hosts must follow the same path.
FAKE_IP_NETWORKS = (ipaddress.ip_network("198.18.0.0/15"), ipaddress.ip_network("fc00::/7"))


def _global_ip(ip):
    address = ipaddress.ip_address(ip)
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
        address = address.ipv4_mapped
    return address.is_global and not address.is_multicast and not address.is_reserved


def _fake_ip(ip):
    address = ipaddress.ip_address(ip)
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
        address = address.ipv4_mapped
    return any(address in network for network in FAKE_IP_NETWORKS)


def _public_host(host):
    host = host.lower()
    if "%" in host:
        raise ValueError("Scoped hosts are not accepted")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        if (len(host) > 253 or "." not in host or
                not re.fullmatch(r"(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z](?:[a-z0-9-]{0,61}[a-z0-9])?", host)
                or host.endswith((".localhost", ".local", ".internal", ".home.arpa"))):
            raise ValueError("Invalid public destination host")
        return host
    if not _global_ip(address):
        raise ValueError("Non-public destination")
    return str(address)


def _origin(value):
    if not isinstance(value, str) or re.search(r"[\x00-\x20\x7f\\]", value):
        raise ValueError("Invalid destination URL")
    url = urlsplit(value)
    if url.scheme not in ("http", "https") or not url.hostname or url.fragment:
        raise ValueError("Only HTTP(S) destinations are accepted")
    if not re.fullmatch(r"(?:[a-zA-Z0-9.-]+|\[[a-fA-F0-9:.]+\])(?::[0-9]{1,5})?", url.netloc):
        raise ValueError("Invalid destination authority")
    port = url.port if url.port is not None else (443 if url.scheme == "https" else 80)
    if port not in (80, 443) and port < 1024:
        raise ValueError("Destination port is not a web port")
    return url, _public_host(url.hostname), port


def _builtin_host(host):
    # APP_HOSTS entries are suffixes: models.opencode.ai belongs to opencode.ai.
    return (any(_matches(host, domain) for domain in APP_HOSTS)
            or any(_matches(host, domain)
                   for domains in LOCAL_ROUTES.values() for domain in domains))


def _configured_urls(config):
    for _, options in _provider_options(config):
        yield from (options.get(key) for key in ("baseURL", "baseUrl", "hubBaseURL"))
    # DeepSeek's setup fetches the catalog after saving its Hub configuration,
    # but before adding the OpenCode entry.
    import hub_paths
    yield _read_json(hub_paths.ACCOUNTS_DIR / "deepseek-api.json").get("base_url")
    from xpiki_manager import load_xpiki_config
    yield load_xpiki_config().get("base_url")
    from claude_manager import claude_service
    active = claude_service.get_active_account()
    if active and active.get("token_type") == "api_token":
        yield active.get("base_url")


def _destination_allowed(host, port, scheme, config):
    """Default public HTTPS for built-ins; other origins require exact configuration."""
    if scheme in (None, "https") and port == 443:
        if _builtin_host(host):
            return True
        import gemini_routes
        if gemini_routes.matches(host):
            return True
    for value in _configured_urls(config):
        try:
            url, configured_host, configured_port = _origin(value)
        except ValueError:
            continue
        if (host, port) == (configured_host, configured_port) and scheme in (None, url.scheme):
            return True
    return False


def _matches(host: str, domain: str) -> bool:
    return host == domain or host.endswith("." + domain)


def _strip_host_port(host: str) -> str:
    raw = (host or "").strip()
    if raw.startswith("["):
        end = raw.find("]")
        if end != -1:
            return raw[1:end].lower()
    if raw.count(":") == 1:
        return raw.split(":", 1)[0].lower()
    return raw.strip("[]").lower()


def _split_host_port(authority: str, default_port: int = 443) -> tuple[str, int]:
    raw = (authority or "").strip()
    if raw.startswith("["):
        end = raw.find("]")
        if end != -1:
            host = raw[1:end]
            rest = raw[end + 1:]
            if rest.startswith(":") and rest[1:].isdigit():
                return host, int(rest[1:])
            return host, default_port
    if raw.count(":") == 1:
        host, _, port_str = raw.partition(":")
        if port_str.isdigit():
            return host, int(port_str)
    return raw, default_port


def provider_for_host(host: str, opencode_config: dict | None = None) -> str | None:
    """Resolve common built-in and configured provider hosts to provider IDs."""
    host = _strip_host_port(host)
    config = opencode_config if isinstance(opencode_config, dict) else _read_json(CONFIG_DIR / "opencode.json")
    domains: dict[str, list[str]] = {}
    explicit = []
    for name, options in _provider_options(config):
        for key in ("baseURL", "baseUrl", "hubBaseURL"):
            base = options.get(key)
            if isinstance(base, str):
                try:
                    if urlsplit(base).hostname == host:
                        explicit.append(name)
                except ValueError:
                    pass
        domains[name] = LOCAL_ROUTES.get(name.lower(), ())
    if explicit:
        return explicit[0]
    matches = [(len(domain), name) for name, values in domains.items()
               for domain in values if domain and _matches(host, domain)]
    if matches:
        return max(matches)[1]
    # Gemini's maintained list also contains Google AI domains outside the
    # usual googleapis.com/google.com suffixes (for example gemini.google).
    import gemini_routes
    if gemini_routes.matches(host):
        return "google"
    # Built-in providers may use OpenCode defaults and have no config entry.
    # Explicit configured endpoints above retain priority. Ambiguous built-in
    # aliases (e.g. two DeepSeek integrations) need a configured provider.
    builtins = {name for name, values in LOCAL_ROUTES.items()
                for domain in values if _matches(host, domain)}
    return next(iter(builtins)) if len(builtins) == 1 else None


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
    routes = hub.get("provider_routes")
    mode = routes.get(provider, "default") if isinstance(routes, dict) else "default"
    if provider and mode in ("default", "auto"):
        from auto_router import router
        return router.connect(provider, host, port, hub, oc)

    upstream = select_upstream(host, hub, oc)

    # If routing through external proxy and failover/rotation is enabled, try pool candidates
    candidates = _get_candidate_proxies(hub)
    if upstream in candidates and len(candidates) > 1 and hub.get("proxy_failover", True):
        last_error = None
        for cand_url in candidates:
            try:
                sock = _connect_upstream(cand_url, host, port, hub_config=hub)
                return sock, cand_url
            except Exception as e:
                last_error = e
                continue
        if last_error:
            raise last_error

    return _connect_upstream(upstream, host, port, hub_config=hub), upstream


def _resolve_with_hub_dns(host: str, hub_config=None, timeout=8) -> str:
    import dns_tester

    clean_host = (host or "").strip().strip("[]")
    try:
        ipaddress.ip_address(clean_host)
        return clean_host
    except ValueError:
        pass

    hub = hub_config if isinstance(hub_config, dict) else _read_json(CONFIG_DIR / "antigravity.json")
    mode = hub.get("dns_mode", "system")
    if mode == "system":
        return host
    deadline = time.monotonic() + timeout
    if mode == "doh":
        doh_url = str(hub.get("doh_url") or "").strip()
        if not doh_url.startswith("https://"):
            raise OSError("Invalid DoH URL")
        query = dns_tester._build_dns_query(host)
        request = urllib.request.Request(doh_url, data=query,
            headers={"Content-Type": "application/dns-message", "Accept": "application/dns-message"}, method="POST")
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        remaining = max(0.5, deadline - time.monotonic())
        with opener.open(request, timeout=remaining) as response:
            answer = dns_tester._parse_a_record_ip(response.read(65536))
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


def _resolve_public(host, port, allow_fake_ip=False):
    addresses = list(dict.fromkeys(info[4][0] for info in socket.getaddrinfo(
        host, port, type=socket.SOCK_STREAM)))
    if not addresses:
        raise OSError("Destination did not resolve to an address")
    if all(_global_ip(address) for address in addresses):
        return addresses
    # A local transparent-proxy resolver may return fake-IP for every answer.
    # Only accept that for direct tunnels: an external proxy must resolve the
    # host itself, and mixed answers stay rejected.
    if allow_fake_ip and all(_fake_ip(address) for address in addresses):
        return addresses
    raise OSError("Destination did not resolve exclusively to public addresses")


def connect_public_routed(host, port, opencode_config=None):
    """Route an already authorized public destination without relaxing the listener."""
    context = _public_connect_deadline.set(time.monotonic() + 45)
    try:
        return connect_routed(host, port, opencode_config=opencode_config)
    finally:
        _public_connect_deadline.reset(context)


def _connect_upstream(proxy_url: str | None, target_host: str, target_port: int,
                      hub_config=None, timeout=20) -> socket.socket:
    deadline = time.monotonic() + timeout
    public_deadline = _public_connect_deadline.get()
    if public_deadline is not None:
        deadline = min(deadline, public_deadline)
    upstream = None
    def remaining():
        budget = deadline - time.monotonic()
        if budget <= 0:
            raise TimeoutError("Upstream connection timed out")
        return budget
    try:
        remaining()
        constrained = public_deadline is not None
        if not proxy_url or proxy_url == "dns://hub":
            resolved = _resolve_with_hub_dns(target_host, hub_config, remaining()) if proxy_url else target_host
            addresses = (_resolve_public(resolved, target_port, allow_fake_ip=not proxy_url)
                         if constrained else [resolved])
            for address in addresses:
                try:
                    upstream = socket.create_connection((address, target_port), timeout=remaining())
                    break
                except OSError:
                    if address == addresses[-1]:
                        raise
        else:
            if any(c in str(target_host) for c in "\r\n\x00 \t"):
                raise ValueError("Invalid target host")
            parsed = urlparse(proxy_url)
            if parsed.scheme not in ("http", "https") or not parsed.hostname:
                raise OSError("Unsupported proxy URL")
            # Configured upstreams own DNS for built-in service domains.
            # Pin other origins to a validated public address, so remote
            # resolution cannot change an explicitly configured destination.
            destination = target_host
            if constrained and not _builtin_host(target_host):
                destination = _resolve_public(target_host, target_port)[0]
            proxy_host = parsed.hostname
            proxy_port = parsed.port or (443 if parsed.scheme == "https" else 80)
            upstream = socket.create_connection((proxy_host, proxy_port), timeout=remaining())
            if parsed.scheme == "https":
                upstream.settimeout(remaining())
                upstream = ssl.create_default_context().wrap_socket(upstream, server_hostname=proxy_host)
            auth = ""
            if parsed.username is not None:
                from urllib.parse import unquote
                credentials = f"{unquote(parsed.username)}:{unquote(parsed.password or '')}".encode()
                auth = "Proxy-Authorization: Basic " + base64.b64encode(credentials).decode("ascii") + "\r\n"
            connect_host = f"[{destination}]" if ":" in destination and not destination.startswith("[") else destination
            request = (f"CONNECT {connect_host}:{target_port} HTTP/1.1\r\n"
                       f"Host: {connect_host}:{target_port}\r\n{auth}Connection: Keep-Alive\r\n\r\n")
            upstream.settimeout(remaining())
            upstream.sendall(request.encode("ascii"))
            response = b""
            while b"\r\n\r\n" not in response and len(response) < 65536:
                upstream.settimeout(remaining())
                # Do not consume tunnel data beyond the CONNECT response.
                part = upstream.recv(1)
                if not part:
                    break
                response += part
            if not response.endswith(b"\r\n\r\n") or not re.match(rb"HTTP/1\.[01] 200(?: |\r\n)", response):
                raise OSError("Upstream proxy refused CONNECT")
        upstream.settimeout(None)
        return upstream
    except Exception:
        if upstream is not None:
            upstream.close()
        raise


def _relay(left: socket.socket, right: socket.socket, *, response_only=False) -> None:
    for sock in (left, right):
        sock.settimeout(min(10, RELAY_IDLE))
    deadline = time.monotonic() + RELAY_LIFETIME
    last_activity = time.monotonic()
    activity_lock = threading.Lock()

    def shutdown():
        for sock in (left, right):
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

    def pump(src: socket.socket, dst: socket.socket) -> None:
        nonlocal last_activity
        try:
            budget = MAX_RELAY_BYTES
            while budget and time.monotonic() < deadline:
                try:
                    chunk = src.recv(min(65536, budget))
                except TimeoutError:
                    with activity_lock:
                        if time.monotonic() - last_activity >= RELAY_IDLE:
                            break
                    continue
                if not chunk:
                    try:
                        dst.shutdown(socket.SHUT_WR)
                    except OSError:
                        pass
                    return
                dst.sendall(chunk)
                with activity_lock:
                    last_activity = time.monotonic()
                budget -= len(chunk)
        except OSError:
            pass
        shutdown()

    directions = [(right, left)] if response_only else [(left, right), (right, left)]
    threads = [threading.Thread(target=pump, args=pair, daemon=True) for pair in directions]
    try:
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(max(0, deadline - time.monotonic()))
    finally:
        shutdown()
        for thread in threads:
            if thread.ident is not None:
                thread.join()
        for sock in (left, right):
            try:
                sock.close()
            except OSError:
                pass


class _HeaderReader:
    """Unbuffered header reads with a size limit and wall-clock deadline."""

    def __init__(self, stream, connection):
        self.stream = stream
        self.connection = connection
        self.deadline = time.monotonic() + HEADER_TIMEOUT
        self.remaining = 65536

    def readline(self, size):
        line = bytearray()
        while len(line) < size:
            self.remaining -= 1
            timeout = self.deadline - time.monotonic()
            if self.remaining < 0 or timeout <= 0:
                raise TimeoutError("HTTP header limit exceeded")
            self.connection.settimeout(timeout)
            char = self.stream.read(1)
            if not char:
                break
            line += char
            if char == b"\n":
                break
        return bytes(line)


class _BoundedHandler(BaseHTTPRequestHandler):
    # rfile must be unbuffered: some clients (Bun/OpenCode) send the first TLS
    # bytes together with CONNECT. A buffered readline() would swallow them and
    # the tunnel would hang until "Timed out waiting for response headers".
    rbufsize = 0

    def handle_one_request(self):
        original = self.rfile
        self.rfile = _HeaderReader(original, self.connection)
        try:
            super().handle_one_request()
        finally:
            self.rfile = original

    def parse_request(self):
        try:
            if not super().parse_request():
                return False
            if self.requestline.split()[1] != self.path:
                self.send_error(400, "Invalid request target")
                return False
            return True
        finally:
            self.rfile = self.rfile.stream
            self.connection.settimeout(HEADER_TIMEOUT)

    def _read_body(self, max_size=MAX_BODY, *, required=False):
        lengths = self.headers.get_all("Content-Length", [])
        if (self.headers.get_all("Transfer-Encoding") or len(lengths) > 1 or
                (lengths and not re.fullmatch(r"[0-9]{1,10}", lengths[0]))):
            self.send_error(400, "Unsupported request body framing")
            return None
        length = int(lengths[0]) if lengths else 0
        if length > max_size:
            self.send_error(413, "Payload Too Large")
            return None
        if required and not length:
            self.send_error(400, "Request body required")
            return None
        body = bytearray()
        deadline = time.monotonic() + 30
        while len(body) < length:
            timeout = deadline - time.monotonic()
            if timeout <= 0:
                raise TimeoutError("HTTP body read timed out")
            self.connection.settimeout(min(HEADER_TIMEOUT, timeout))
            chunk = self.rfile.read(min(65536, length - len(body)))
            if not chunk:
                self.send_error(400, "Incomplete request body")
                return None
            body.extend(chunk)
        self.connection.settimeout(HEADER_TIMEOUT)
        return body

    def log_message(self, *_args):
        pass


class _Handler(_BoundedHandler):
    def do_GET(self):
        if self.path == "/_antigravity_provider_proxy_health":
            body = b"antigravity-provider-proxy"
            self.send_response(200)
            self.send_header("X-Antigravity-Proxy-Policy", "2")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self._dispatch()

    def _dispatch(self):
        if self.path.startswith(REVERSE_PREFIX):
            self._reverse_proxy()
        else:
            self._plain_http()

    def _reverse_target(self, provider, config=None):
        oc = _read_json(CONFIG_DIR / "opencode.json") if config is None else config
        for name, opts in _provider_options(oc):
            if name == provider and "hubBaseURL" in opts:
                return opts["hubBaseURL"]
        return PROVIDER_ENDPOINTS.get(provider)

    def _reverse_proxy(self):
        """Forward a plain-HTTP request to a provider through the Hub route."""
        if "Origin" in self.headers or "Sec-Fetch-Site" in self.headers:
            self.send_error(403, "Browser requests are not permitted")
            return
        if re.search(r"[\x00-\x20\x7f\\]", self.path):
            self.send_error(400, "Invalid reverse path")
            return
        parsed = urlsplit(self.path)
        provider, _, tail = parsed.path[len(REVERSE_PREFIX):].partition("/")
        config = _read_json(CONFIG_DIR / "opencode.json")
        base = self._reverse_target(provider, config)
        if not base:
            self.send_error(404, "Unknown reverse provider")
            return
        try:
            target, host, port = _origin(base)
            if target.query or parsed.fragment or not _safe_path(target.path) or not _safe_path(tail):
                raise ValueError("Invalid reverse path")
        except ValueError:
            self.send_error(400, "Invalid reverse destination or path")
            return
        base_path = target.path.rstrip("/")
        # The local baseURL already repeats the upstream prefix (/v1), so drop
        # it from the incoming path before appending the real endpoint path.
        prefix = base_path.lstrip("/")
        if prefix and (tail == prefix or tail.startswith(prefix + "/")):
            tail = tail[len(prefix):].lstrip("/")
        path = f"{base_path}/{tail}" if tail else (base_path or "/")
        if parsed.query:
            path += "?" + parsed.query
        self._forward_http(target, host, port, path, config)

    def do_CONNECT(self):
        config = _read_json(CONFIG_DIR / "opencode.json")
        try:
            if not re.fullmatch(r"(?:[a-zA-Z0-9.-]+|\[[a-fA-F0-9:.]+\]):[0-9]{1,5}", self.path):
                raise ValueError("Invalid CONNECT authority")
            _, host, target_port = _origin("https://" + self.path)
        except ValueError:
            self.send_error(400, "Invalid CONNECT authority")
            return
        if not _destination_allowed(host, target_port, None, config):
            self.send_error(403, "Destination is not configured")
            return
        try:
            upstream, _ = connect_public_routed(host, target_port, config)
        except Exception:
            self.send_error(502, "Unable to establish routed connection")
            return
        with upstream:
            self.send_response(200, "Connection Established")
            self.end_headers()
            _relay(self.connection, upstream)

    def _plain_http(self):
        config = _read_json(CONFIG_DIR / "opencode.json")
        try:
            parsed, host, port = _origin(self.path)
        except ValueError:
            self.send_error(400, "Expected an absolute HTTP(S) proxy URL")
            return
        if not _destination_allowed(host, port, parsed.scheme, config):
            self.send_error(403, "Destination is not configured")
            return
        path = (parsed.path or "/") + (("?" + parsed.query) if parsed.query else "")
        self._forward_http(parsed, host, port, path, config)

    def _forward_http(self, url, host, port, path, config):
        if re.search(r"[\x00-\x20\x7f\\]", path) or not _safe_path(path.split("?", 1)[0]):
            self.send_error(400, "Invalid HTTP path")
            return
        if any("\n" in value or "\r" in value for _, value in self.headers.items()) or self.headers.defects:
            self.send_error(400, "Invalid HTTP headers")
            return
        body = self._read_body()
        if body is None:
            return
        hop_headers = {"host", "proxy-authorization", "proxy-authenticate", "proxy-connection",
                       "connection", "keep-alive", "te", "trailer", "transfer-encoding",
                       "upgrade", "content-length", "expect"}
        hop_headers.update(token.strip().lower()
                           for value in self.headers.get_all("Connection", [])
                           for token in value.split(","))
        authority = f"[{host}]" if ":" in host else host
        if port != (443 if url.scheme == "https" else 80):
            authority += f":{port}"
        request = f"{self.command} {path} HTTP/1.1\r\n"
        for key, value in self.headers.items():
            if key.lower() not in hop_headers:
                request += f"{key}: {value}\r\n"
        if body or "Content-Length" in self.headers:
            request += f"Content-Length: {len(body)}\r\n"
        request += f"Host: {authority}\r\nConnection: close\r\n\r\n"
        upstream = None
        try:
            upstream, _ = connect_public_routed(host, port, config)
            upstream.settimeout(HEADER_TIMEOUT)
            if url.scheme == "https":
                upstream = ssl.create_default_context().wrap_socket(upstream, server_hostname=host)
            upstream.sendall(request.encode("latin-1"))
            if body:
                upstream.sendall(body)
        except Exception:
            if upstream is not None:
                upstream.close()
            self.send_error(502, "Unable to establish routed connection")
            return
        with upstream:
            _relay(self.connection, upstream, response_only=True)

    do_POST = _dispatch
    do_PUT = _dispatch
    do_DELETE = _dispatch
    do_PATCH = _dispatch
    do_HEAD = _dispatch


def _safe_path(path):
    decoded = unquote(path)
    return not (decoded.startswith("//") or "%" in decoded or any(
        part in (".", "..") for part in decoded.split("/"))
        or re.search(r"[\x00-\x1f\x7f\\]", decoded))


class _ThreadingServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    # Default backlog is only 5; parallel model retries exhaust it.
    request_queue_size = 128
    max_workers = 32

    def __init__(self, *args, **kwargs):
        self._workers = threading.BoundedSemaphore(self.max_workers)
        super().__init__(*args, **kwargs)

    def process_request(self, request, client_address):
        if not self._workers.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self._workers.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._workers.release()


def start() -> bool:
    with _start_lock:
        return _start()


def _start() -> bool:
    global _server, _thread
    import gemini_routes
    gemini_routes.refresh_async()
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
        # Do not fall back to a running dispatcher with the old unrestricted policy.
        probe = http.client.HTTPConnection(HOST, PORT, timeout=0.3)
        try:
            probe.request("GET", "/_antigravity_provider_proxy_health")
            with probe.getresponse() as response:
                compatible = response.status == 200 and response.getheader("X-Antigravity-Proxy-Policy") == "2"
            if compatible:
                _install_process_proxy_environment()
                return True
        except (OSError, http.client.HTTPException):
            pass
        finally:
            probe.close()
        return False


def _maintain_auto_routes():
    from auto_router import router
    visibility_keys = {"google":"antigravity", "claude-pro":"claude", "openrouter-free":"openrouter",
                       "tokenlavka":"tokenlavka"}
    while True:
        try:
            hub = _read_json(CONFIG_DIR / "antigravity.json")
            oc = _read_json(CONFIG_DIR / "opencode.json")
            names = set(oc.get("provider") or {}) | set(oc.get("providers") or {})
            visibility = hub.get("providers_visibility") or {}
            routes = hub.get("provider_routes") or {}
            disabled = oc.get("disabled_providers") or []
            for name in names:
                enabled = visibility.get(visibility_keys.get(name, name), True)
                if enabled and name not in disabled and routes.get(name, "default") in ("default", "auto"):
                    router.refresh(name, hub, oc)
        except Exception:
            pass
        time.sleep(5)


def _install_process_proxy_environment() -> None:
    # Existing clients (including the OpenCode child process) inherit these
    # settings; compatibility relies on the restricted dispatcher above.
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
