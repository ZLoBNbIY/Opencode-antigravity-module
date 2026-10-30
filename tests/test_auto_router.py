import io
import json
from pathlib import Path
import sys
import threading
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "gui-manager"))
from auto_router import AutoRouter, AutoRouteUnavailable, configured_routes


class AutoRouterTests(unittest.TestCase):
    def setUp(self):
        self.hub = {"vless_enabled": True, "vless_url": "vless://test", "vless_http_port": 10879,
                    "dns_mode": "standard", "custom_dns": ["192.0.2.1"],
                    "proxy": "http://user:secret-value@proxy.example:8080"}
        self.oc = {"provider": {"google": {"options": {}}, "openai": {"options": {}}}}

    def ready(self, router, provider="openai", hub=None):
        self.assertTrue(router.refresh(provider, hub or self.hub, self.oc).wait(2))
        return router.state(provider, hub or self.hub, self.oc)

    def test_best_route_is_measured_per_provider_not_fixed_priority(self):
        def probe(upstream, host, hub):
            latency = (5 if host == "chatgpt.com" else 70) if upstream == "dns://hub" else 30
            return {"host": host, "ok": True, "latency_ms": latency}
        router = AutoRouter(Mock(), probe=probe)
        self.assertEqual(self.ready(router)["selected"], "dns")
        self.assertEqual(self.ready(router, "google")["selected"], "vless")
        self.assertNotIn("secret-value", json.dumps(router.state("openai", self.hub, self.oc)))

    def test_coverage_beats_lower_latency_on_a_partially_blocked_route(self):
        def probe(upstream, host, hub):
            return {"host": host, "ok": not (upstream == "dns://hub" and host.startswith("daily-")),
                    "latency_ms": 1 if upstream == "dns://hub" else 25}
        router = AutoRouter(Mock(), probe=probe)
        state = self.ready(router, "google")
        self.assertNotEqual(state["selected"], "dns")
        self.assertEqual(next(r for r in state["rows"] if r["mode"] == "dns")["passed"], 1)

    def test_connection_failure_switches_to_next_healthy_route_without_direct(self):
        def probe(upstream, host, hub):
            return {"host": host, "ok": True, "latency_ms": 1 if upstream == "dns://hub" else 10}
        connection = Mock()
        connector = Mock(side_effect=[OSError("down"), connection])
        router = AutoRouter(connector, probe=probe)
        self.ready(router)
        result, upstream = router.connect("openai", "chatgpt.com", 443, self.hub, self.oc)
        self.assertIs(result, connection)
        self.assertEqual([call.args[0] for call in connector.call_args_list],
                         ["dns://hub", "http://127.0.0.1:10879"])
        self.assertEqual(router.state("openai", self.hub, self.oc)["selected"], "vless")
        connection.sendall.assert_not_called()

    def test_no_successful_route_fails_closed_and_never_uses_direct(self):
        connector = Mock()
        router = AutoRouter(connector, probe=lambda upstream, host, hub: {"host": host, "ok": False, "latency_ms": None})
        self.ready(router)
        with self.assertRaises(AutoRouteUnavailable):
            router.connect("openai", "chatgpt.com", 443, self.hub, self.oc)
        connector.assert_not_called()
        with self.assertRaises(AutoRouteUnavailable):
            router.connect("openai", "chatgpt.com", 443, {}, self.oc)
        self.assertEqual(configured_routes({"google_smart_doh": "https://dns.example/query"}), [])

    def test_cache_refreshes_after_expiry_and_config_changes_invalidate_selection(self):
        now = [0]
        speeds = {"dns://hub": 1}
        probe = Mock(side_effect=lambda upstream, host, hub: {"host": host, "ok": True, "latency_ms": speeds.get(upstream, 20)})
        router = AutoRouter(Mock(), probe=probe, clock=lambda: now[0])
        self.assertEqual(self.ready(router)["selected"], "dns")
        count = probe.call_count
        now[0] = 30
        self.ready(router)
        self.assertEqual(probe.call_count, count)
        now[0] = 61
        speeds["dns://hub"] = 50
        self.assertEqual(self.ready(router)["selected"], "vless")
        changed = {**self.hub, "custom_dns": ["192.0.2.2"]}
        self.assertIsNone(router.state("openai", changed, self.oc)["selected"])

    def test_concurrent_refresh_requests_share_one_probe_batch(self):
        gate = threading.Event()
        entered = threading.Event()
        def probe(upstream, host, hub):
            entered.set()
            gate.wait(2)
            return {"host": host, "ok": True, "latency_ms": 10}
        mocked = Mock(side_effect=probe)
        router = AutoRouter(Mock(), probe=mocked)
        event = router.refresh("openai", self.hub, self.oc)
        self.assertTrue(entered.wait(1))
        for _ in range(10):
            self.assertIs(router.refresh("openai", self.hub, self.oc, force=True), event)
        gate.set()
        self.assertTrue(event.wait(2))
        self.assertEqual(mocked.call_count, 3)

    def test_https_probe_accepts_auth_required_but_rejects_blocks_and_gateway_errors(self):
        for status, ok in ((200, True), (401, True), (403, False), (502, False)):
            with self.subTest(status=status), patch("auto_router.ssl.create_default_context") as context:
                raw, tls = Mock(), Mock()
                tls.makefile.return_value = io.BytesIO(f"HTTP/1.1 {status} test\r\nContent-Length: 0\r\n\r\n".encode())
                context.return_value.wrap_socket.return_value = tls
                router = AutoRouter(Mock(return_value=raw))
                result = router._probe_https("dns://hub", "chatgpt.com", self.hub)
                self.assertEqual(result["ok"], ok)
                context.return_value.wrap_socket.assert_called_once_with(raw, server_hostname="chatgpt.com")
                request = tls.sendall.call_args.args[0]
                self.assertNotIn(b"Authorization:", request)
                self.assertIn(b"GET /backend-api/wham/usage ", request)
                tls.close.assert_called_once()

    def test_internal_dispatcher_and_dns_proxy_are_not_external_candidates(self):
        for url in ("http://localhost:10880", "http://127.0.0.1:51180", "http://[::1]:10880"):
            self.assertEqual(configured_routes({"proxy": url}), [])

    def test_partial_route_is_not_used_for_its_failed_host(self):
        def probe(upstream, host, hub):
            return {"host": host, "ok": host.startswith('daily-') if upstream == 'dns://hub' else not host.startswith('daily-'),
                    "latency_ms": 1 if upstream == 'dns://hub' else 30}
        connector = Mock(return_value=Mock())
        router = AutoRouter(connector, probe=probe)
        self.ready(router, 'google')
        router.connect('google', 'cloudcode-pa.googleapis.com', 443, self.hub, self.oc)
        self.assertNotEqual(connector.call_args.args[0], 'dns://hub')

    def test_auxiliary_domain_failure_does_not_replace_the_best_api_route(self):
        def probe(upstream, host, hub):
            return {"host": host, "ok": True, "latency_ms": 1 if upstream == 'dns://hub' else 30}
        connector = Mock(side_effect=[OSError('auxiliary host down'), Mock()])
        router = AutoRouter(connector, probe=probe)
        self.ready(router, 'google')
        _, upstream = router.connect('google', 'artifactregistry.googleapis.com', 443, self.hub, self.oc)
        self.assertNotEqual(upstream, 'dns://hub')
        self.assertEqual(router.state('google', self.hub, self.oc)['selected'], 'dns')


if __name__ == "__main__":
    unittest.main()
