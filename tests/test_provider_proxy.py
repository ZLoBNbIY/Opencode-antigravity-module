import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "gui-manager"))
from provider_proxy import provider_for_host, select_upstream


class ProviderRouteProxyTests(unittest.TestCase):
    def setUp(self):
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


if __name__ == "__main__":
    unittest.main()
