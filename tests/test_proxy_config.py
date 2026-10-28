import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "gui-manager"))
from proxy_config import DNS_PROXY, ROUTE_PROXY, select_effective_proxy, sync_process_proxy_environment, sync_provider_proxies, sync_provider_routes


class ProxyConfigTests(unittest.TestCase):
    def test_process_proxy_environment_sets_route_and_keeps_loopback_bypass(self):
        from unittest.mock import patch
        with patch.dict(os.environ, {"NO_PROXY": "example.com,localhost", "no_proxy": "example.com,localhost"}, clear=True):
            sync_process_proxy_environment("http://127.0.0.1:20809")
            self.assertEqual(os.environ["HTTPS_PROXY"], "http://127.0.0.1:20809")
            self.assertEqual(os.environ["https_proxy"], "http://127.0.0.1:20809")
            self.assertIn("127.0.0.1", os.environ["NO_PROXY"])
            self.assertIn("localhost", os.environ["no_proxy"])
            self.assertIn("example.com", os.environ["NO_PROXY"])

    def test_vless_has_priority_over_custom_and_dns(self):
        config = {
            "vless_enabled": True,
            "vless_url": "vless://example",
            "proxy": "http://proxy.example:8080",
            "dns_mode": "doh",
        }
        self.assertEqual(select_effective_proxy(config, 20809), "http://127.0.0.1:20809")

    def test_dns_proxy_is_used_when_vless_is_disabled(self):
        config = {"vless_enabled": False, "proxy": DNS_PROXY, "dns_mode": "standard"}
        self.assertEqual(select_effective_proxy(config, 20809), DNS_PROXY)

    def test_dns_proxy_replaces_stale_vless_proxy_when_disabled(self):
        config = {
            "vless_enabled": False,
            "vless_url": "vless://example",
            "proxy": "http://127.0.0.1:20809",
            "dns_mode": "doh",
        }
        self.assertEqual(select_effective_proxy(config, 20809), DNS_PROXY)

        config = {
            "provider": {
                "google": {"options": {"apiKey": "antigravity"}},
                "openrouter": {"options": {"baseURL": "https://openrouter.ai/api/v1"}},
                "hub": {"options": {"baseURL": "http://127.0.0.1:51186/v1", "proxy": "http://127.0.0.1:51180"}},
            },
            "providers": {
                "deepseek": {"settings": {"baseURL": "https://api.deepseek.com/anthropic/v1"}},
                "deepseek-web": {"settings": {"baseURL": "http://127.0.0.1:1/v1"}},
            },
        }
        sync_provider_proxies(config, "http://127.0.0.1:20809")
        self.assertEqual(config["provider"]["google"]["options"]["proxy"], "http://127.0.0.1:20809")
        self.assertEqual(config["provider"]["openrouter"]["options"]["proxy"], "http://127.0.0.1:20809")
        self.assertNotIn("proxy", config["provider"]["hub"]["options"])
        self.assertEqual(config["providers"]["deepseek"]["settings"]["proxy"], "http://127.0.0.1:20809")
        self.assertNotIn("proxy", config["providers"]["deepseek-web"]["settings"])

    def test_proxy_is_removed_from_external_providers_when_disabled(self):
        config = {"provider": {"google": {"options": {"proxy": DNS_PROXY}}}}
        sync_provider_proxies(config, None)
        self.assertNotIn("proxy", config["provider"]["google"]["options"])

    def test_external_providers_use_local_route_dispatcher(self):
        config = {"provider": {
            "google": {"options": {}},
            "openrouter": {"options": {}},
            "deepseek": {"options": {"proxy": "old"}},
            "custom": {"options": {"baseURL": "https://api.example/v1", "proxy": "old"}},
            "hub": {"options": {"baseURL": "http://localhost:9000/v1", "proxy": "old"}},
        }}
        hub = {
            "vless_enabled": True, "vless_url": "vless://example",
            "dns_mode": "doh",
            "proxy": "http://proxy.example:8080",
        }
        sync_provider_routes(config, hub, 10879, {
            "google": "vless", "openrouter": "direct",
            "deepseek": "proxy", "custom": "dns", "hub": "vless",
        })
        opts = config["provider"]
        self.assertEqual(opts["google"]["options"]["proxy"], ROUTE_PROXY)
        self.assertEqual(opts["openrouter"]["options"]["proxy"], ROUTE_PROXY)
        self.assertEqual(opts["deepseek"]["options"]["proxy"], ROUTE_PROXY)
        self.assertEqual(opts["custom"]["options"]["proxy"], ROUTE_PROXY)
        self.assertNotIn("proxy", opts["hub"]["options"])

    def test_route_dispatcher_is_applied_to_all_external_providers(self):
        config = {"provider": {
            "openai": {"options": {}}, "google": {"options": {}},
            "openrouter": {"options": {}},
        }}
        hub = {"vless_enabled": True, "vless_url": "vless://example",
               "dns_mode": "system"}
        sync_provider_routes(config, hub, 10879, {"google": "direct"})
        providers = config["provider"]
        self.assertEqual(providers["openai"]["options"]["proxy"], ROUTE_PROXY)
        self.assertEqual(providers["google"]["options"]["proxy"], ROUTE_PROXY)
        self.assertEqual(providers["openrouter"]["options"]["proxy"], ROUTE_PROXY)


if __name__ == "__main__":
    unittest.main()
