"""
Robust and lightweight embedded local HTTP/HTTPS CONNECT proxy for Antigravity Hub.
Resolves destinations using configured DoH / DoT / SmartDNS and tunnels OpenAI/ChatGPT traffic cleanly.
"""

import sys
import ipaddress
import socket
import threading
import json
import time
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler
import urllib.parse
import urllib.request

try:
    import dns_tester
except ImportError:
    from . import dns_tester

PROXY_HOST = "127.0.0.1"
PROXY_PORT = 51180

def get_config_dns_settings() -> dict:
    config_path = Path.home() / ".config" / "opencode" / "antigravity.json"
    if config_path.exists():
        try:
            data = json.loads(config_path.read_text(encoding="utf-8"))
            return {
                "dns_mode": data.get("dns_mode", "standard"),
                "custom_dns": data.get("custom_dns", ["143.20.64.55", "31.58.216.201"]),
                "dot_host": data.get("dot_host", "dns.bezmezhau.com"),
                "doh_url": data.get("doh_url", "https://dns.bezmezhau.com/dns-query"),
            }
        except Exception:
            pass
    return {
        "dns_mode": "standard",
        "custom_dns": ["143.20.64.55", "31.58.216.201"],
        "dot_host": "dns.bezmezhau.com",
        "doh_url": "https://dns.bezmezhau.com/dns-query",
    }

# DNS cache: domain -> (ip, timestamp)
_dns_cache: dict[str, tuple[str, float]] = {}
_cache_lock = threading.Lock()

def resolve_target(host: str) -> str:
    # If host is already an IP, return as is
    clean_host = (host or "").strip().strip("[]")
    try:
        ipaddress.ip_address(clean_host)
        return clean_host
    except ValueError:
        pass

    # Do not route non-AI hosts like GitHub/npm through SmartDNS (they fail on SmartDNS)
    host_lower = clean_host.lower()
    bypass_domains = ("github.com", "githubusercontent.com", "github.io", "npmjs.org", "npmjs.com")
    if any(host_lower == d or host_lower.endswith("." + d) for d in bypass_domains):
        return host

    now = time.time()
    with _cache_lock:
        if host in _dns_cache:
            ip, exp = _dns_cache[host]
            if now < exp:
                return ip

    settings = get_config_dns_settings()
    mode = settings.get("dns_mode", "standard")
    resolved_ip = None

    if mode == "system":
        return host

    try:
        if mode == "doh":
            res = dns_tester.test_doh_endpoint(settings.get("doh_url", "https://dns.bezmezhau.com/dns-query"), domain=host)
            if res.get("ok") and res.get("resolved_ip") and res["resolved_ip"] != "OK":
                resolved_ip = res["resolved_ip"]
        elif mode == "dot":
            res = dns_tester.test_dot_endpoint(settings.get("dot_host", "dns.bezmezhau.com"), domain=host)
            if res.get("ok") and res.get("resolved_ip") and res["resolved_ip"] != "OK":
                resolved_ip = res["resolved_ip"]
        elif mode == "standard":
            custom_dns = settings.get("custom_dns", [])
            primary = custom_dns[0] if custom_dns else "143.20.64.55"
            res = dns_tester.test_standard_dns(primary, domain=host)
            if res.get("ok") and res.get("resolved_ip") and res["resolved_ip"] != "OK":
                resolved_ip = res["resolved_ip"]
    except Exception:
        pass

    final_ip = resolved_ip if resolved_ip else host
    with _cache_lock:
        _dns_cache[host] = (final_ip, now + 120)  # cache 2 minutes

    return final_ip


def _is_loopback_host(host: str) -> bool:
    clean = (host or "").strip().strip("[]").lower()
    if clean in ("localhost", "0.0.0.0", "::", "::1"):
        return True
    try:
        addr = ipaddress.ip_address(clean)
        return addr.is_loopback or addr.is_unspecified
    except ValueError:
        return False


class TunnelHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        # Silent logging
        pass

    def do_CONNECT(self):
        # Extract target host and port
        if self.path.startswith("[") and "]" in self.path:
            end = self.path.index("]")
            host = self.path[1:end]
            rest = self.path[end + 1:]
            port_str = rest[1:] if rest.startswith(":") else ""
            try:
                port = int(port_str) if port_str else 443
            except ValueError:
                port = 443
        elif ":" in self.path:
            host, port_str = self.path.split(":", 1)
            try:
                port = int(port_str)
            except ValueError:
                port = 443
        else:
            host = self.path
            port = 443

        # Self-loop protection
        if _is_loopback_host(host) and port in (PROXY_PORT, 10880):
            self.send_error(400, "Proxy Loop Detected")
            return

        resolved_target = resolve_target(host)

        upstream = None
        try:
            upstream = socket.create_connection((resolved_target, port), timeout=10)
            upstream.settimeout(300)

            self.send_response(200, "Connection Established")
            self.end_headers()

            # Bidirectional streaming using threads with half-close support
            client_sock = self.connection
            try:
                client_sock.settimeout(300)
            except OSError:
                pass

            def forward(src, dst):
                try:
                    while True:
                        buf = src.recv(32768)
                        if not buf:
                            try:
                                dst.shutdown(socket.SHUT_WR)
                            except Exception:
                                pass
                            break
                        dst.sendall(buf)
                except TimeoutError:
                    for s in (client_sock, upstream):
                        try:
                            s.close()
                        except Exception:
                            pass
                except Exception:
                    pass

            t1 = threading.Thread(target=forward, args=(client_sock, upstream), daemon=True)
            t2 = threading.Thread(target=forward, args=(upstream, client_sock), daemon=True)
            t1.start()
            t2.start()
            t1.join()
            t2.join()
        except Exception:
            try:
                self.send_error(502, f"Bad Gateway: Unable to connect to {host}")
            except Exception:
                pass
        finally:
            if upstream is not None:
                try:
                    upstream.close()
                except Exception:
                    pass

    def do_GET(self):
        self._proxy_plain_http("GET")

    def do_POST(self):
        self._proxy_plain_http("POST")

    def _proxy_plain_http(self, method):
        url = self.path
        if not url.startswith("http"):
            url = f"http://{self.headers.get('Host', '')}{self.path}"
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            self.send_error(400, "Invalid Proxy URL")
            return
        target_port = parsed.port or (443 if parsed.scheme == "https" else 80)
        if _is_loopback_host(parsed.hostname) and target_port in (PROXY_PORT, 10880):
            self.send_error(400, "Proxy Loop Detected")
            return
        try:
            content_length = int(self.headers.get("Content-Length", 0) or 0)
        except (TypeError, ValueError):
            self.send_error(400, "Invalid Content-Length")
            return
        if content_length < 0 or content_length > 32 * 1024 * 1024:
            self.send_error(413, "Payload Too Large")
            return
        try:
            body = self.rfile.read(content_length) if content_length > 0 else None
            req = urllib.request.Request(url, data=body, method=method)
            hop_by_hop = {
                "host", "content-length", "proxy-authorization", "proxy-connection",
                "connection", "keep-alive", "te", "trailers", "transfer-encoding", "upgrade",
            }
            for k, v in self.headers.items():
                if k.lower() not in hop_by_hop:
                    req.add_header(k, v)
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with opener.open(req, timeout=12) as resp:
                self.send_response(resp.status)
                for k, v in resp.headers.items():
                    if k.lower() not in hop_by_hop:
                        self.send_header(k, v)
                self.end_headers()
                self.wfile.write(resp.read())
        except Exception as e:
            try: self.send_error(502, f"Proxy Error: {e}")
            except Exception: pass


class ThreadedTunnelServer(HTTPServer):
    allow_reuse_address = True
    daemon_threads = True

    def process_request(self, request, client_address):
        t = threading.Thread(target=self.process_request_thread, args=(request, client_address), daemon=True)
        t.start()

    def process_request_thread(self, request, client_address):
        try:
            self.finish_request(request, client_address)
        except Exception:
            pass
        finally:
            self.shutdown_request(request)


_server_instance: ThreadedTunnelServer | None = None
_server_thread: threading.Thread | None = None
_server_lock = threading.Lock()

def start_local_proxy(port: int = PROXY_PORT) -> bool:
    global _server_instance, _server_thread
    with _server_lock:
        if _server_instance is not None:
            return True
        try:
            server = ThreadedTunnelServer((PROXY_HOST, port), TunnelHandler)
            _server_instance = server
            t = threading.Thread(target=server.serve_forever, daemon=True)
            _server_thread = t
            t.start()
            return True
        except Exception as e:
            print(f"Failed to start local proxy on {PROXY_HOST}:{port}: {e}")
            return False

def stop_local_proxy():
    global _server_instance, _server_thread
    with _server_lock:
        server = _server_instance
        thread = _server_thread
        _server_instance = None
        _server_thread = None
    if server:
        try:
            server.shutdown()
            server.server_close()
        except Exception:
            pass
    if thread and thread.is_alive():
        thread.join(timeout=2)
