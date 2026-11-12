import unittest
from pathlib import Path
import sys
import tempfile
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "gui-manager"))
import vless_subscription
from vless_subscription import (
    detect_country,
    parse_vless_subscription,
    filter_nodes_by_country,
    benchmark_and_pick_best,
    VlessNode,
    AI_BLOCKED_COUNTRIES,
)


class VlessSubscriptionTests(unittest.TestCase):
    def test_detect_country_by_flag_emoji(self):
        # US flag
        code, name, flag, ai_ok = detect_country("%F0%9F%87%BA%F0%9F%87%B8 United States, Chicago")
        self.assertEqual(code, "US")
        self.assertTrue(ai_ok)
        self.assertEqual(flag, "🇺🇸")

        # Germany flag
        code, name, flag, ai_ok = detect_country("%F0%9F%87%A9%F0%9F%87%AA Germany, Frankfurt")
        self.assertEqual(code, "DE")
        self.assertTrue(ai_ok)
        self.assertEqual(flag, "🇩🇪")

        # Iran flag (blocked for AI)
        code, name, flag, ai_ok = detect_country("%F0%9F%87%AE%F0%9F%87%B7 Iran, Tehran")
        self.assertEqual(code, "IR")
        self.assertFalse(ai_ok)

        # Russia flag (blocked for AI)
        code, name, flag, ai_ok = detect_country("%F0%9F%87%B7%F0%9F%87%BA Russia | [CIDR]")
        self.assertEqual(code, "RU")
        self.assertFalse(ai_ok)

        # Hong Kong (blocked for AI)
        code, name, flag, ai_ok = detect_country("%F0%9F%87%AD%F0%9F%87%B0 Hong Kong")
        self.assertEqual(code, "HK")
        self.assertFalse(ai_ok)

    def test_detect_country_by_keyword(self):
        code, name, flag, ai_ok = detect_country("My Server in Netherlands, Amsterdam")
        self.assertEqual(code, "NL")
        self.assertTrue(ai_ok)

        code, name, flag, ai_ok = detect_country("Fast node France Paris")
        self.assertEqual(code, "FR")
        self.assertTrue(ai_ok)

        code, name, flag, ai_ok = detect_country("China Shenzhen Node")
        self.assertEqual(code, "CN")
        self.assertFalse(ai_ok)

    def test_parse_vless_subscription(self):
        raw_text = (
            "# Some comment\n"
            "vless://uuid-1@104.21.58.37:443?security=reality&sni=example.com#%F0%9F%87%BA%F0%9F%87%B8%20United%20States\n"
            "vless://uuid-2@185.86.147.175:443?security=tls&sni=other.com#%F0%9F%87%AE%F0%9F%87%B7%20Iran\n"
            "vless://uuid-3@151.101.36.111:443?security=tls&sni=fastly.com#%F0%9F%87%AB%F0%9F%87%B7%20France\n"
            "invalid line\n"
        )
        nodes = parse_vless_subscription(raw_text)
        self.assertEqual(len(nodes), 3)

        self.assertEqual(nodes[0].country_code, "US")
        self.assertTrue(nodes[0].is_ai_allowed)

        self.assertEqual(nodes[1].country_code, "IR")
        self.assertFalse(nodes[1].is_ai_allowed)

        self.assertEqual(nodes[2].country_code, "FR")
        self.assertTrue(nodes[2].is_ai_allowed)

    def test_filter_nodes_by_country(self):
        nodes = [
            VlessNode("vless://1", "1.1.1.1", 443, "US Node", "US", "USA", "🇺🇸", True),
            VlessNode("vless://2", "2.2.2.2", 443, "DE Node", "DE", "Germany", "🇩🇪", True),
            VlessNode("vless://3", "3.3.3.3", 443, "RU Node", "RU", "Russia", "🇷🇺", False),
            VlessNode("vless://4", "4.4.4.4", 443, "IR Node", "IR", "Iran", "🇮🇷", False),
        ]

        ai_filtered = filter_nodes_by_country(nodes, "ai_allowed")
        self.assertEqual(len(ai_filtered), 2)
        self.assertEqual({n.country_code for n in ai_filtered}, {"US", "DE"})

        us_filtered = filter_nodes_by_country(nodes, "US")
        self.assertEqual(len(us_filtered), 1)
        self.assertEqual(us_filtered[0].country_code, "US")

        all_nodes = filter_nodes_by_country(nodes, "all")
        self.assertEqual(len(all_nodes), 4)

    def test_benchmark_and_pick_best(self):
        nodes = [
            VlessNode("vless://1", "1.1.1.1", 443, "US-1", "US", "USA", "🇺🇸", True),
            VlessNode("vless://2", "2.2.2.2", 443, "US-2", "US", "USA", "🇺🇸", True),
            VlessNode("vless://3", "3.3.3.3", 443, "IR-1", "IR", "Iran", "🇮🇷", False),
        ]

        def fake_tcp_ping(node, timeout=2.0):
            if node.server == "1.1.1.1":
                return 120
            if node.server == "2.2.2.2":
                return 45
            return 10

        with mock.patch("vless_subscription.tcp_ping_node", side_effect=fake_tcp_ping):
            best = benchmark_and_pick_best(nodes, country_filter="ai_allowed")
            self.assertIsNotNone(best)
            self.assertEqual(best.server, "2.2.2.2")
            self.assertEqual(best.country_code, "US")

    def test_fetch_subscription_cache_fallback(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_cache = Path(temp_dir) / "sub_cache.txt"
            temp_cache.write_text(
                "vless://uuid-cached@1.2.3.4:443?security=reality#%F0%9F%87%A9%F0%9F%87%AA%20Germany\n",
                encoding="utf-8",
            )
            with mock.patch("vless_subscription.CACHE_FILE", temp_cache), \
                 mock.patch("vless_subscription.urllib.request.build_opener", side_effect=OSError("Network error")):
                nodes, msg = vless_subscription.fetch_subscription()
                self.assertEqual(len(nodes), 1)
                self.assertEqual(nodes[0].country_code, "DE")
                self.assertIn("кэш", msg.lower())


if __name__ == "__main__":
    unittest.main()
