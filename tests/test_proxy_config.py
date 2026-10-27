import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "gui-manager"))
from proxy_config import DNS_PROXY, select_effective_proxy, sync_provider_proxies


class ProxyConfigTests(unittest.TestCase):
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

    def test_external_providers_are_updated_and_local_hub_is_not(self):
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


if __name__ == "__main__":
    unittest.main()
