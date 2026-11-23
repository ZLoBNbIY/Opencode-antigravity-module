import io
import json
from pathlib import Path
import sys
import threading
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "gui-manager"))
from auto_router import AutoRouter, AutoRouteUnavailable, configured_routes, probe_hosts


class AutoRouterTests(unittest.TestCase):
    def setUp(self):
        self.hub = {"vless_enabled": True, "vless_url": "vless://test", "vless_http_port": 10879,
                    "dns_mode": "standard", "custom_dns": ["192.0.2.1"],
                    "proxy": "http://user:secret-value@proxy.example:8080"}
        self.oc = {"provider": {"google": {"options": {}}, "openai": {"options": {"baseURL": "https://chatgpt.com"}}}}

    def ready(self, router, provider="openai", hub=None):
        self.assertTrue(router.refresh(provider, hub or self.hub, self.oc).wait(2))
        return router.state(provider, hub or self.hub, self.oc)

    def test_deepseek_has_probe_host_and_auto_can_select_a_route(self):
        self.assertEqual(probe_hosts("deepseek-account", {}), ("api.deepseek.com",))
        configured = {"provider": {"deepseek": {"options": {"baseURL": "https://ds.example.com/v1"}}}}
        self.assertEqual(probe_hosts("deepseek-account", configured), ("ds.example.com",))
        with patch("deepseek_api.api_origin", return_value="https://custom.deepseek.test"):
            self.assertEqual(probe_hosts("deepseek-account", {}), ("custom.deepseek.test",))

        probe = lambda upstream, host, hub: {"host": host, "ok": True,
                                             "latency_ms": 1 if upstream == "dns://hub" else 20}
        router = AutoRouter(Mock(), probe=probe)
        state = self.ready(router, "deepseek-account")
        self.assertEqual(state["status"], "ready")
        self.assertEqual(state["selected"], "dns")
        self.assertTrue(all(row["total"] == 1 for row in state["rows"]))

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
        self.assertEqual(configured_routes({}), [])

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

    def test_proxy_only_pool_obeys_order_and_retries_per_candidate(self):
        primary, backup = "http://proxy-one.example:8080", "http://user:fixture@proxy-two.example:8080"
        hub = {"proxy_pool": [{"url": primary}, backup], "proxy": primary}
        probe = Mock(side_effect=lambda upstream, host, hub: {
            "host": host, "ok": True, "latency_ms": 30 if upstream == primary else 1,
        })
        connection = Mock()
        connector = Mock(side_effect=[OSError("primary temporarily down"), connection, connection, connection])
        now = [0]
        router = AutoRouter(connector, probe=probe, clock=lambda: now[0])
        state = self.ready(router, hub=hub)
        self.assertEqual(state["selected"], "proxy")
        self.assertEqual(len(state["rows"]), 1)
        self.assertNotIn("fixture@", json.dumps(state))
        self.assertEqual(router.selected_upstream("openai", hub, self.oc), primary)
        self.assertEqual(router.connect("openai", "chatgpt.com", 443, hub, self.oc), (connection, backup))
        self.assertEqual([call.args[0] for call in connector.call_args_list], [primary, backup])
        self.assertEqual(router.selected_upstream("openai", hub, self.oc), backup)
        self.assertEqual(router.connect("openai", "auth.openai.com", 443, hub, self.oc)[1], primary)
        self.assertEqual(router.connect("openai", "chatgpt.com", 443, hub, self.oc)[1], backup)
        now[0] = 10
        self.ready(router, hub=hub)
        self.assertEqual(router.selected_upstream("openai", hub, self.oc), primary)

    def test_unavailable_proxy_is_skipped_and_pool_changes_invalidate_cached_order(self):
        primary, backup = "http://proxy-one.example:8080", "http://proxy-two.example:8080"
        hub = {"proxy_pool": [primary, backup]}
        probe = Mock(side_effect=lambda upstream, host, hub: {
            "host": host, "ok": upstream == backup, "latency_ms": 25,
        })
        connector = Mock()
        router = AutoRouter(connector, probe=probe)
        self.assertEqual(self.ready(router, hub=hub)["selected"], "proxy")
        self.assertEqual(router.connect("openai", "chatgpt.com", 443, hub, self.oc)[1], backup)
        connector.assert_called_once_with(backup, "chatgpt.com", 443, hub_config=hub, timeout=20)
        for changed in ({**hub, "proxy_pool": [backup, primary]}, {**hub, "proxy_failover": False}):
            self.assertEqual(router.state("openai", changed, self.oc)["status"], "pending")
        disabled = {**hub, "proxy_failover": False}
        probe.reset_mock()
        self.assertEqual(self.ready(router, hub=disabled)["status"], "unavailable")
        probe.assert_called_once_with(primary, "chatgpt.com", disabled)
        with self.assertRaises(AutoRouteUnavailable):
            router.connect("openai", "chatgpt.com", 443, disabled, self.oc)

    def test_claude_auto_kill_switch_never_probes_or_connects_non_vless_routes(self):
        vless = "http://127.0.0.1:10879"
        probe = Mock(side_effect=lambda upstream, host, hub: {
            "host": host, "ok": True, "latency_ms": 30 if upstream == vless else 1,
        })
        connector = Mock(side_effect=OSError("VLESS disconnected"))
        router = AutoRouter(connector, probe=probe)
        for mode in ("default", "auto"):
            with self.subTest(mode=mode):
                hub = dict(self.hub, provider_routes={"claude-pro": mode})
                state = self.ready(router, "claude-pro", hub=hub)
                self.assertEqual([row["mode"] for row in state["rows"]], ["vless"])
                self.assertEqual(state["selected"], "vless")
        probe.assert_called_once()
        self.assertEqual(probe.call_args.args[:2], (vless, "claude.ai"))
        with self.assertRaises(AutoRouteUnavailable):
            router.connect("claude-pro", "claude.ai", 443, self.hub, self.oc)
        connector.assert_called_once_with(vless, "claude.ai", 443, hub_config=self.hub, timeout=20)
        self.assertEqual(router.state("claude-pro", self.hub, self.oc)["status"], "unavailable")
        with self.assertRaises(AutoRouteUnavailable):
            router.selected_upstream("claude-pro", self.hub, self.oc, host="claude.ai")

        disabled = {**self.hub, "vless_kill_switch": False}
        self.assertEqual(router.state("claude-pro", disabled, self.oc)["status"], "pending")
        self.assertEqual(self.ready(router, "claude-pro", hub=disabled)["selected"], "dns")
        self.assertEqual(self.ready(router, "openai")["selected"], "dns")
        no_active_tunnel = {**self.hub, "vless_url": ""}
        self.assertEqual(self.ready(router, "claude-pro", hub=no_active_tunnel)["selected"], "dns")

    def test_claude_auto_rejects_cached_vless_selection_when_managed_listener_is_not_ready(self):
        connector = Mock()
        ready = Mock(return_value=True)
        revision = Mock(return_value=1)
        probe = Mock(side_effect=lambda upstream, host, hub: {"host": host, "ok": True, "latency_ms": 1})
        router = AutoRouter(connector, probe=probe, vless_ready=ready, vless_revision=revision)
        self.assertEqual(self.ready(router, "claude-pro")["selected"], "vless")
        ready.return_value = False
        self.assertEqual(router.state("claude-pro", self.hub, self.oc)["status"], "unavailable")
        with self.assertRaises(AutoRouteUnavailable):
            router.connect("claude-pro", "claude.ai", 443, self.hub, self.oc)
        connector.assert_not_called()
        ready.return_value = True
        revision.return_value = 2
        self.assertEqual(router.state("claude-pro", self.hub, self.oc)["status"], "pending")
        self.assertEqual(self.ready(router, "claude-pro")["selected"], "vless")
        self.assertEqual(probe.call_count, 2)

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
        _, upstream = router.connect('google', 'clients6.google.com', 443, self.hub, self.oc)
        self.assertNotEqual(upstream, 'dns://hub')
        self.assertEqual(router.state('google', self.hub, self.oc)['selected'], 'dns')

    def test_probe_hosts_handles_none_sections_and_refresh_sets_expiry_on_error(self):
        self.assertEqual(probe_hosts("openai", {"provider": None}), ("api.openai.com", "chatgpt.com"))
        now = [100]
        router = AutoRouter(Mock(), clock=lambda: now[0])
        with patch.object(router, "_measure", side_effect=RuntimeError("boom")):
            ev = router.refresh("openai", self.hub, self.oc)
            self.assertTrue(ev.wait(2))
        entry = next(iter(router._entries.values()))
        self.assertFalse(entry["running"])
        self.assertEqual(entry["expires"], 110)


if __name__ == "__main__":
    unittest.main()
