import sys
import unittest
from unittest.mock import patch
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
            "mwapi": {"options": {"baseURL": "https://api.mwapi.dev/v1"}},
        }}

    def test_builtin_hosts_resolve_to_expected_provider(self):
        self.assertEqual(provider_for_host("daily-cloudcode-pa.googleapis.com", self.opencode), "google")
        self.assertEqual(provider_for_host("api.openai.com", self.opencode), "openai")
        self.assertEqual(provider_for_host("api.mwapi.dev", self.opencode), "mwapi")

    def test_routes_can_select_different_upstreams(self):
        hub = {"provider_routes": {"google": "dns", "openai": "vless"},
               "vless_http_port": 10879, "vless_enabled": True,
               "vless_url": "vless://example"}
        self.assertEqual(select_upstream("generativelanguage.googleapis.com", hub, self.opencode),
                         "dns://hub")
        self.assertEqual(select_upstream("api.openai.com", hub, self.opencode),
                         "http://127.0.0.1:10879")

    def test_direct_override_bypasses_global_vless(self):
        hub = {"provider_routes": {"google": "direct"}, "vless_enabled": True,
               "vless_url": "vless://example", "vless_http_port": 10879}
        self.assertIsNone(select_upstream("cloudcode-pa.googleapis.com", hub, self.opencode))
        self.assertEqual(select_upstream("api.openai.com", hub, self.opencode),
                          "http://127.0.0.1:10879")

    def test_smart_dns_is_only_used_for_cloudcode_not_oauth(self):
        hub = {"provider_routes": {"google": "google-smart"},
               "vless_enabled": True, "vless_url": "vless://example"}
        for host in ("cloudcode-pa.googleapis.com", "daily-cloudcode-pa.googleapis.com"):
            self.assertEqual(select_upstream(host, hub, self.opencode), "smartdns://google")
        for host in ("oauth2.googleapis.com", "accounts.google.com", "cloudcode-pa.googleapis.com.evil.test"):
            self.assertEqual(select_upstream(host, hub, self.opencode), "http://127.0.0.1:10879")

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

    @patch("provider_proxy.select_upstream", return_value="http://secret:password@proxy.example:3128")
    def test_route_description_never_exposes_credentials(self, select):
        self.assertEqual(describe_route("cloudcode-pa.googleapis.com"), "http://proxy.example:3128")


if __name__ == "__main__":
    unittest.main()
