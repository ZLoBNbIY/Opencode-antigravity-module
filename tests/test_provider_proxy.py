import os
import sys
import unittest
from io import BytesIO
from http.client import HTTPMessage
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "gui-manager"))
from provider_proxy import provider_for_host, select_upstream
from google_routes import describe_route


class ProviderRouteProxyTests(unittest.TestCase):
    @patch("provider_proxy._read_json", return_value={"dns_mode": "standard", "custom_dns": ["192.0.2.1", "192.0.2.2"]})
    @patch("dns_tester.test_standard_dns", side_effect=[{"ok": False}, {"ok": True, "resolved_ip": "203.0.113.8"}])
    def test_standard_dns_uses_saved_secondary_when_primary_fails(self, query, read):
        import provider_proxy
        import dns_tester
        previous = dns_tester.DOMAIN_TO_TEST
        self.assertEqual(provider_proxy._resolve_with_hub_dns("chatgpt.com"), "203.0.113.8")
        self.assertEqual([call.args[0] for call in query.call_args_list], ["192.0.2.1", "192.0.2.2"])
        self.assertEqual(dns_tester.DOMAIN_TO_TEST, previous)

    def setUp(self):
        self.auto_refresh = patch("auto_router.router.refresh").start()
        self.auto_selected = patch("auto_router.router.selected_upstream", return_value="http://127.0.0.1:10879").start()
        self.addCleanup(patch.stopall)
        self.opencode = {"provider": {
            "google": {"options": {}},
            "openai": {"options": {}},
            "xpiki": {"options": {"baseURL": "https://api.xpiki.com/v1"}},
        }}

    def test_builtin_hosts_resolve_to_expected_provider(self):
        self.assertEqual(provider_for_host("daily-cloudcode-pa.googleapis.com", self.opencode), "google")
        self.assertEqual(provider_for_host("api.openai.com", self.opencode), "openai")
        self.assertEqual(provider_for_host("api.xpiki.com", self.opencode), "xpiki")

    def test_updated_gemini_domain_is_routed_as_google(self):
        with patch("gemini_routes.matches", return_value=True):
            self.assertEqual(provider_for_host("antigravity-unleash.goog", self.opencode), "google")
            self.assertEqual(select_upstream("antigravity-unleash.goog",
                {"provider_routes": {"google": "vless"}, "vless_http_port": 10879}, self.opencode),
                "http://127.0.0.1:10879")

    def test_gemini_match_does_not_override_configured_provider(self):
        config = {"provider": {"custom": {"options": {"baseURL": "https://antigravity-unleash.goog"}}}}
        with patch("gemini_routes.matches", return_value=True):
            self.assertEqual(provider_for_host("antigravity-unleash.goog", config), "custom")

    def test_builtin_openai_direct_route_without_provider_config(self):
        hub = {"provider_routes": {"openai": "direct"}, "dns_mode": "standard",
               "vless_enabled": True, "vless_url": "vless://example"}
        import provider_proxy
        for host in ('chatgpt.com', 'auth.openai.com', 'api.openai.com'):
            self.assertEqual(provider_for_host(host, {}), 'openai')
            self.assertIsNone(select_upstream(host, hub, {}))
            with patch('provider_proxy._connect_upstream') as connect:
                provider_proxy.connect_routed(host, 443, hub, {})
            self.assertIsNone(connect.call_args.args[0])
        self.assertIsNone(provider_for_host('chatgpt.com.evil.test', {}))
        self.auto_refresh.assert_not_called()

    def test_configured_custom_endpoint_keeps_priority_over_builtin_fallback(self):
        config = {'provider': {'custom': {'options': {'baseURL': 'https://chatgpt.com/api'}}}}
        self.assertEqual(provider_for_host('chatgpt.com', config), 'custom')

    def test_routes_can_select_different_upstreams(self):
        hub = {"provider_routes": {"google": "dns", "openai": "vless"},
               "vless_http_port": 10879, "vless_enabled": True,
               "vless_url": "vless://example"}
        self.assertEqual(select_upstream("generativelanguage.googleapis.com", hub, self.opencode),
                         "dns://hub")
        self.assertEqual(select_upstream("api.openai.com", hub, self.opencode),
                         "http://127.0.0.1:10879")

    def test_google_follows_hub_route_setting_for_every_mode(self):
        """Google must never be pinned to VLESS: the Hub's per-provider route wins."""
        hosts = ("daily-cloudcode-pa.googleapis.com", "cloudcode-pa.googleapis.com",
                 "generativelanguage.googleapis.com")
        base = {"vless_http_port": 10879, "vless_enabled": True,
                "vless_url": "vless://example", "dns_mode": "standard",
                "custom_dns": ["192.0.2.1"], "proxy": "http://proxy.example:3128"}
        expectations = {
            "vless": "http://127.0.0.1:10879",
            "dns": "dns://hub",
            "proxy": "http://proxy.example:3128",
            "direct": None,
            "default": "http://127.0.0.1:10879",  # AutoRouter's current selection
            "auto": "http://127.0.0.1:10879",
        }
        for mode, expected in expectations.items():
            hub = {**base, "provider_routes": {"google": mode}}
            for host in hosts:
                self.assertEqual(select_upstream(host, hub, self.opencode), expected,
                                 f"google route {mode} for {host}")
        self.auto_refresh.assert_called()

    def test_direct_override_bypasses_global_vless(self):
        hub = {"provider_routes": {"google": "direct"}, "vless_enabled": True,
               "vless_url": "vless://example", "vless_http_port": 10879}
        self.assertIsNone(select_upstream("cloudcode-pa.googleapis.com", hub, self.opencode))
        self.assertEqual(select_upstream("api.openai.com", hub, self.opencode),
                          "http://127.0.0.1:10879")

    def test_legacy_smart_dns_route_falls_back_to_normal_google_route(self):
        hub = {"provider_routes": {"google": "google-smart"},
               "vless_enabled": True, "vless_url": "vless://example"}
        self.assertEqual(select_upstream("cloudcode-pa.googleapis.com", hub, self.opencode),
                         "http://127.0.0.1:10879")

    def test_plugin_dispatcher_proxy_never_loops_back_to_dispatcher(self):
        # The OpenCode plugin reads hub.proxy from antigravity.json; when it
        # points at the route dispatcher itself, the dispatcher must not
        # connect back to itself for non-gate hosts.
        hub = {"proxy": "http://127.0.0.1:10880", "vless_enabled": False,
               "dns_mode": "system"}
        from auto_router import AutoRouteUnavailable
        self.auto_selected.side_effect = AutoRouteUnavailable("no configured routes")
        with self.assertRaises(AutoRouteUnavailable):
            select_upstream("accounts.google.com", hub, self.opencode)
        with self.assertRaises(AutoRouteUnavailable):
            select_upstream("api.openai.com", hub, self.opencode)

    def test_external_proxy_still_used_when_it_is_not_the_dispatcher(self):
        self.auto_selected.return_value = "http://proxy.example:3128"
        hub = {"proxy": "http://proxy.example:3128", "vless_enabled": False,
               "dns_mode": "system"}
        self.assertEqual(select_upstream("accounts.google.com", hub, self.opencode),
                         "http://proxy.example:3128")

    def test_proxy_pool_top_entry_is_the_primary_route(self):
        import provider_proxy
        hub = {"proxy_pool": ["http://first.example:8000", "http://backup.example:8000"],
               "proxy_failover": True}
        self.assertEqual(provider_proxy._hub_upstream_proxy(hub), "http://first.example:8000")
        self.assertEqual(provider_proxy._get_candidate_proxies(hub), hub["proxy_pool"])

    @patch("provider_proxy.select_upstream", return_value="http://secret:password@proxy.example:3128")
    def test_route_description_never_exposes_credentials(self, select):
        self.assertEqual(describe_route("cloudcode-pa.googleapis.com"), "http://proxy.example:3128")

    @patch("provider_proxy.select_upstream")
    def test_route_description_survives_pending_auto_probe(self, select):
        from auto_router import AutoRouteUnavailable
        select.side_effect = AutoRouteUnavailable("Auto: маршрут ещё не выбран")
        self.assertEqual(describe_route("cloudcode-pa.googleapis.com", {}),
                         "Auto: маршрут ещё не выбран")

    def test_dispatcher_accepts_parallel_retries_without_losing_tunnel_bytes(self):
        import provider_proxy
        self.assertGreaterEqual(provider_proxy._ThreadingServer.request_queue_size, 64)
        self.assertEqual(provider_proxy._Handler.rbufsize, 0)

    def test_dispatcher_start_does_not_install_global_proxy(self):
        import provider_proxy as proxy
        with patch("gemini_routes.refresh_async"), \
             patch.object(proxy, "_server", None), patch.object(proxy, "_thread", None), \
             patch.object(proxy, "_ThreadingServer"), patch("provider_proxy.threading.Thread"), \
             patch.dict(os.environ, {"NO_PROXY": "example.test"}, clear=True):
            self.assertTrue(proxy.start())
            self.assertTrue(proxy.start())
            self.assertEqual(dict(os.environ), {"NO_PROXY": "example.test"})
            routed = proxy.proxy_environment()
            self.assertEqual(routed["HTTPS_PROXY"], "http://127.0.0.1:10880")
            self.assertNotIn("HTTPS_PROXY", os.environ)

    @patch("provider_proxy._read_json", return_value={"provider": {"tokenlavka": {
        "options": {"hubBaseURL": "https://tokenlavka.example/v1"}}}})
    def test_reverse_target_reads_saved_provider_endpoint(self, read):
        import provider_proxy
        handler = provider_proxy._Handler.__new__(provider_proxy._Handler)
        self.assertEqual(handler._reverse_target("tokenlavka"),
                         "https://tokenlavka.example/v1")

    def test_reverse_endpoint_is_used_for_model_requests(self):
        import provider_proxy
        self.assertEqual(provider_proxy.PROVIDER_ENDPOINTS["tokenlavka"],
                         "https://tokenlavka.com/v1")
        self.assertEqual(provider_proxy._Handler.do_POST,
                         provider_proxy._Handler._dispatch)

    @patch("gemini_routes.matches", return_value=False)
    def test_jsonc_origins_match_exact_scheme_host_and_port(self, gemini):
        import provider_proxy as proxy
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "opencode.jsonc").write_text(
                '{"provider": {/* comment */ "custom":{"settings":'
                '{"baseURL":"https://gateway.example:8443/v1",},},},}', encoding="utf-8")
            config = proxy._read_json(root / "opencode.json")
        self.assertTrue(proxy._destination_allowed("gateway.example", 8443, "https", config))
        self.assertTrue(proxy._destination_allowed("gateway.example", 8443, None, config))
        self.assertFalse(proxy._destination_allowed("gateway.example", 8443, "http", config))
        self.assertFalse(proxy._destination_allowed("gateway.example", 443, None, config))
        self.assertFalse(proxy._destination_allowed("a.gateway.example", 8443, None, config))
        self.assertTrue(proxy._destination_allowed("integrate.api.nvidia.com", 443, None, {}))
        self.assertTrue(proxy._destination_allowed("registry.npmjs.org", 443, None, {}))
        self.assertFalse(proxy._destination_allowed("unconfigured.example", 443, None, {}))

    @patch("gemini_routes.matches", return_value=False)
    def test_protected_xpiki_custom_origin_is_allowed(self, gemini):
        import provider_proxy as proxy
        import xpiki_manager
        with TemporaryDirectory() as directory, patch.multiple(
            xpiki_manager, CONFIG_DIR=Path(directory),
            XPIKI_CONFIG_FILE=Path(directory) / "xpiki.json",
        ):
            self.assertTrue(xpiki_manager.save_xpiki_config({
                "base_url": "https://xpiki-gateway.example:8443/v1", "api_key": "fixture"}))
            self.assertTrue(proxy._destination_allowed("xpiki-gateway.example", 8443, None, {}))
            self.assertFalse(proxy._destination_allowed("xpiki-gateway.example", 443, None, {}))

    @patch("provider_proxy.socket.getaddrinfo", return_value=[
        (2, 1, 6, "", ("93.184.216.34", 443)),
        (2, 1, 6, "", ("10.0.0.1", 443)),
    ])
    def test_mixed_dns_answers_are_not_connected(self, resolve):
        import provider_proxy as proxy
        with self.assertRaises(OSError):
            proxy._resolve_public("gateway.example", 443)

    @patch("gemini_routes.matches", return_value=False)
    def test_app_host_subdomains_share_the_builtin_allowlist(self, gemini):
        import provider_proxy as proxy
        self.assertTrue(proxy._builtin_host("models.opencode.ai"))
        self.assertTrue(proxy._destination_allowed("models.opencode.ai", 443, "https", {}))
        self.assertFalse(proxy._destination_allowed("models.opencode.ai.evil.test", 443, "https", {}))

    @patch("provider_proxy.socket.getaddrinfo", return_value=[
        (2, 1, 6, "", ("198.18.0.85", 443)),
    ])
    def test_direct_tunnel_accepts_all_fake_ip_answers(self, resolve):
        import provider_proxy as proxy
        self.assertEqual(proxy._resolve_public("chatgpt.com", 443, allow_fake_ip=True),
                         ["198.18.0.85"])
        with self.assertRaises(OSError):
            proxy._resolve_public("chatgpt.com", 443)

    @patch("provider_proxy.socket.getaddrinfo", return_value=[
        (2, 1, 6, "", ("198.18.0.85", 443)),
        (2, 1, 6, "", ("10.0.0.1", 443)),
    ])
    def test_mixed_fake_ip_and_private_answers_are_rejected(self, resolve):
        import provider_proxy as proxy
        with self.assertRaises(OSError):
            proxy._resolve_public("chatgpt.com", 443, allow_fake_ip=True)

    @patch("provider_proxy._read_json", return_value={})
    @patch("provider_proxy._relay")
    @patch("provider_proxy.ssl.create_default_context")
    @patch("provider_proxy.connect_public_routed")
    def test_tokenlavka_reverse_sends_one_framed_post(self, connect, ssl, relay, read):
        import provider_proxy as proxy
        upstream = MagicMock()
        wire = ssl.return_value.wrap_socket.return_value = MagicMock()
        connect.return_value = upstream, None
        handler = proxy._Handler.__new__(proxy._Handler)
        handler.path = "/r/tokenlavka/v1/chat/completions"
        handler.command = "POST"
        handler.headers = HTTPMessage()
        handler.headers["Content-Length"] = "2"
        handler.headers["Authorization"] = "Bearer fixture"
        handler.rfile = BytesIO(b"{}")
        handler.connection = MagicMock()
        handler._dispatch()
        connect.assert_called_once_with("tokenlavka.com", 443, {})
        header, body = [call.args[0] for call in wire.sendall.call_args_list]
        self.assertIn(b"POST /v1/chat/completions HTTP/1.1\r\n", header)
        self.assertIn(b"Host: tokenlavka.com\r\n", header)
        self.assertIn(b"Content-Length: 2\r\n", header)
        self.assertEqual(body, b"{}")
        relay.assert_called_once_with(handler.connection, wire, response_only=True)

    def test_native_chatgpt_route_keeps_path_and_uses_openai_route(self):
        import provider_proxy as proxy
        from proxy_config import NATIVE_ROUTES, native_route_revision
        endpoint = NATIVE_ROUTES["openai-chatgpt"][1]
        handler = proxy._Handler.__new__(proxy._Handler)
        handler.headers = HTTPMessage()
        handler._forward_http = MagicMock()
        handler.send_error = MagicMock()
        handler.path = (f"/r/openai-chatgpt/{native_route_revision(endpoint)}"
                        "/backend-api/codex/responses?fixture=1")
        with patch("provider_proxy._read_json", return_value={}):
            handler._reverse_proxy()
        _, host, port, path, config = handler._forward_http.call_args.args
        self.assertEqual((host, port, path, config),
                         ("chatgpt.com", 443, "/backend-api/codex/responses?fixture=1", {}))
        self.assertEqual(handler._forward_http.call_args.kwargs, {"provider_id": "openai"})
        handler.send_error.assert_not_called()

    def test_outdated_native_endpoint_does_not_forward_authorization(self):
        import provider_proxy as proxy
        handler = proxy._Handler.__new__(proxy._Handler)
        handler.headers = HTTPMessage()
        handler.headers["Authorization"] = "Bearer fixture"
        handler._forward_http = MagicMock()
        handler.send_error = MagicMock()
        handler.path = "/r/xpiki-api/outdated/v1/chat/completions"
        with patch("provider_proxy._read_json", return_value={}):
            handler._reverse_proxy()
        handler.send_error.assert_called_once_with(409, "Provider routing configuration changed")
        handler._forward_http.assert_not_called()

    def test_ipv6_host_parsing_and_half_close_relay(self):
        import socket
        import threading
        import provider_proxy

        self.assertEqual(provider_proxy._strip_host_port("[::1]:443"), "::1")
        self.assertEqual(provider_proxy._split_host_port("[::1]:8443", 443), ("::1", 8443))
        self.assertEqual(provider_proxy._split_host_port("example.com", 443), ("example.com", 443))

        c1, s1 = socket.socketpair()
        c2, s2 = socket.socketpair()
        t = threading.Thread(target=provider_proxy._relay, args=(s1, s2), daemon=True)
        t.start()
        c1.sendall(b"ping")
        c1.shutdown(socket.SHUT_WR)
        self.assertEqual(c2.recv(16), b"ping")
        self.assertEqual(c2.recv(16), b"")
        c2.sendall(b"pong")
        c2.shutdown(socket.SHUT_WR)
        self.assertEqual(c1.recv(16), b"pong")
        c1.close()
        c2.close()
        t.join(timeout=2)
        self.assertFalse(t.is_alive())


if __name__ == "__main__":
    unittest.main()
