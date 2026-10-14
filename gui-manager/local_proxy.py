"""
Lightweight embedded local HTTP/HTTPS CONNECT proxy for Antigravity Hub.
Resolves upstream destinations using the configured DoH / DoT / SmartDNS
and tunnels OpenCode traffic (OpenAI, Google, etc.) cleanly without
touching Windows-wide network settings.
"""

import sys
import socket
import select
import threading
import json
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler
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
    if host.replace(".", "").isdigit() or ":" in host:
        return host
    
    import time
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

    dns_tester.DOMAIN_TO_TEST = host

    if mode == "doh":
        res = dns_tester.test_doh_endpoint(settings.get("doh_url", "https://dns.bezmezhau.com/dns-query"))
        if res.get("ok") and res.get("resolved_ip") and res["resolved_ip"] != "OK":
            resolved_ip = res["resolved_ip"]
    elif mode == "dot":
        res = dns_tester.test_dot_endpoint(settings.get("dot_host", "dns.bezmezhau.com"))
        if res.get("ok") and res.get("resolved_ip") and res["resolved_ip"] != "OK":
            resolved_ip = res["resolved_ip"]
    elif mode == "standard":
        custom_dns = settings.get("custom_dns", [])
        primary = custom_dns[0] if custom_dns else "143.20.64.55"
        res = dns_tester.test_standard_dns(primary)
        if res.get("ok") and res.get("resolved_ip") and res["resolved_ip"] != "OK":
            resolved_ip = res["resolved_ip"]

    final_ip = resolved_ip if resolved_ip else host
    with _cache_lock:
        _dns_cache[host] = (final_ip, now + 120)  # cache 2 minutes

    return final_ip


def is_openai_domain(host: str) -> bool:
    h = host.lower().strip()
    if ":" in h:
        h = h.split(":", 1)[0]
    openai_domains = (
        "openai.com",
        "chatgpt.com",
        "oaistatic.com",
        "oaiusercontent.com",
    )
    return any(h == d or h.endswith("." + d) for d in openai_domains)

class TunnelHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        # Silent logging for embedded proxy
        pass

    def do_CONNECT(self):
        # Extract target host and port
        if ":" in self.path:
            host, port_str = self.path.split(":", 1)
            port = int(port_str)
        else:
            host = self.path
            port = 443

        # Strict isolation: Only OpenAI / ChatGPT traffic goes through this tunnel
        if not is_openai_domain(host):
            self.send_error(403, f"Forbidden: Local tunnel is reserved for OpenAI/ChatGPT traffic only. Host {host} rejected.")
            return

        resolved_target = resolve_target(host)

        try:
            upstream = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            upstream.settimeout(12)
            upstream.connect((resolved_target, port))
            upstream.settimeout(None)

            self.send_response(200, "Connection Established")
            self.end_headers()

            # Bidirectional pipe
            self._pipe_sockets(self.connection, upstream)
        except Exception:
            try:
                self.send_error(502, f"Bad Gateway: Unable to connect to {host}")
            except Exception:
                pass
        finally:
            try: upstream.close()
            except Exception: pass

    def do_GET(self):
        self._proxy_plain_http("GET")

    def do_POST(self):
        self._proxy_plain_http("POST")

    def do_PUT(self):
        self._proxy_plain_http("PUT")

    def do_DELETE(self):
        self._proxy_plain_http("DELETE")

    def do_HEAD(self):
        self._proxy_plain_http("HEAD")

    def _proxy_plain_http(self, method):
        # Fallback for plain HTTP requests
        url = self.path
        if not url.startswith("http"):
            url = f"http://{self.headers.get('Host', '')}{self.path}"
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length) if content_length > 0 else None
            req = urllib.request.Request(url, data=body, method=method)
            for k, v in self.headers.items():
                if k.lower() not in ("host", "content-length"):
                    req.add_header(k, v)
            with urllib.request.urlopen(req, timeout=15) as resp:
                self.send_response(resp.status)
                for k, v in resp.headers.items():
                    self.send_header(k, v)
                self.end_headers()
                self.wfile.write(resp.read())
        except Exception as e:
            try: self.send_error(502, f"Proxy Error: {e}")
            except Exception: pass

    def _pipe_sockets(self, client_sock, server_sock):
        sockets = [client_sock, server_sock]
        client_sock.setblocking(False)
        server_sock.setblocking(False)

        while True:
            readable, _, exceptional = select.select(sockets, [], sockets, 60)
            if exceptional or not readable:
                break
            for s in readable:
                other = server_sock if s is client_sock else client_sock
                try:
                    data = s.recv(32768)
                    if not data:
                        return
                    other.sendall(data)
                except Exception:
                    return


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

def start_local_proxy(port: int = PROXY_PORT) -> bool:
    global _server_instance, _server_thread
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
    global _server_instance
    if _server_instance:
        try:
            _server_instance.shutdown()
            _server_instance.server_close()
        except Exception:
            pass
        _server_instance = None

if __name__ == "__main__":
    print(f"Starting standalone test of local proxy on {PROXY_HOST}:{PROXY_PORT}...")
    if start_local_proxy():
        print(f"Proxy is running on http://{PROXY_HOST}:{PROXY_PORT}")
        import time
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            stop_local_proxy()
            print("Stopped.")
