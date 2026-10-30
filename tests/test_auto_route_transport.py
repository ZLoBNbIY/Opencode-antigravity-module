"""Loopback integration: Auto failover must carry real traffic through the dispatcher."""
import socket
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'gui-manager'))
import provider_proxy
import auto_router


class TestServer(ThreadingHTTPServer):
    daemon_threads = True


class AutoTransportTests(unittest.TestCase):
    def setUp(self):
        self.received = []
        received = self.received

        class Target(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                received.append(self.path)
                body = b'fixture-ok'
                self.send_response(200)
                self.send_header('Content-Length', str(len(body)))
                self.send_header('Connection', 'close')
                self.end_headers()
                self.wfile.write(body)

        self.target = self.server(Target)
        target_port = self.target.server_port

        class Proxy(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_CONNECT(self):
                with socket.create_connection(('127.0.0.1', target_port), timeout=2) as conn:
                    self.send_response(200)
                    self.end_headers()
                    provider_proxy._relay(self.connection, conn)

        self.external = self.server(Proxy)
        # Reserve a port without listening, making the measured VLESS fail on
        # the real connection after its successful synthetic probe.
        self.closed = socket.socket()
        self.closed.bind(('127.0.0.1', 0))
        self.addCleanup(self.closed.close)
        self.hub = {'vless_enabled': True, 'vless_url': 'vless://fixture',
                    'vless_http_port': self.closed.getsockname()[1],
                    'proxy': f'http://127.0.0.1:{self.external.server_port}',
                    'provider_routes': {'openai': 'default'}}
        self.oc = {'provider': {'openai': {'options': {'baseURL': f'http://api.fixture.test:{target_port}'}}}}
        probe = lambda upstream, host, hub: {'host': host, 'ok': True,
                    'latency_ms': 1 if str(self.closed.getsockname()[1]) in upstream else 30}
        self.router = auto_router.AutoRouter(provider_proxy._connect_upstream, probe=probe)
        self.assertTrue(self.router.refresh('openai', self.hub, self.oc).wait(2))
        self.patches = [patch('auto_router.router', self.router),
                        patch('provider_proxy._read_json', side_effect=lambda path: self.hub if path.name == 'antigravity.json' else self.oc)]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)
        self.dispatcher = self.server(provider_proxy._Handler)

    def server(self, handler):
        server = TestServer(('127.0.0.1', 0), handler)
        threading.Thread(target=server.serve_forever, kwargs={'poll_interval': 0.02}, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return server

    def read_response(self, conn):
        response = bytearray()
        while True:
            part = conn.recv(4096)
            if not part:
                return bytes(response)
            response.extend(part)

    def test_plain_http_reaches_target_once_after_vless_failure(self):
        with socket.create_connection(('127.0.0.1', self.dispatcher.server_port), timeout=4) as conn:
            conn.sendall(f'GET http://api.fixture.test:{self.target.server_port}/check?q=1 HTTP/1.1\r\nHost: api.fixture.test\r\nConnection: close\r\n\r\n'.encode())
            response = self.read_response(conn)
        self.assertIn(b'fixture-ok', response)
        self.assertEqual(self.received, ['/check?q=1'])
        self.assertEqual(self.router.state('openai', self.hub, self.oc)['selected'], 'proxy')

    def test_connect_tunnel_fails_over_before_forwarding_client_request(self):
        with socket.create_connection(('127.0.0.1', self.dispatcher.server_port), timeout=4) as conn:
            conn.sendall(f'CONNECT api.fixture.test:{self.target.server_port} HTTP/1.1\r\nHost: api.fixture.test\r\n\r\n'.encode())
            headers = b''
            while b'\r\n\r\n' not in headers:
                headers += conn.recv(4096)
            self.assertIn(b'200 Connection Established', headers)
            conn.sendall(b'GET /through-tunnel HTTP/1.1\r\nHost: api.fixture.test\r\nConnection: close\r\n\r\n')
            response = self.read_response(conn)
        self.assertIn(b'fixture-ok', response)
        self.assertEqual(self.received, ['/through-tunnel'])
        self.assertEqual(self.router.state('openai', self.hub, self.oc)['selected'], 'proxy')

    def test_manual_vless_failure_does_not_switch_to_another_route(self):
        self.hub['provider_routes']['openai'] = 'vless'
        with socket.create_connection(('127.0.0.1', self.dispatcher.server_port), timeout=4) as conn:
            conn.sendall(f'GET http://api.fixture.test:{self.target.server_port}/manual HTTP/1.1\r\nHost: api.fixture.test\r\nConnection: close\r\n\r\n'.encode())
            response = self.read_response(conn)
        self.assertIn(b'502', response)
        self.assertEqual(self.received, [])


if __name__ == '__main__':
    unittest.main()
