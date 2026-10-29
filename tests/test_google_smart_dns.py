import socket
import struct
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "gui-manager"))
import google_smart_dns as smart


def answer(query, ip="93.184.216.34", ttl=30):
    header = query[:2] + struct.pack("!5H", 0x8180, 1, 1, 0, 0)
    return header + query[12:] + b"\xc0\x0c" + struct.pack("!HHIH", 1, 1, ttl, 4) + socket.inet_aton(ip)


class SmartDnsTests(unittest.TestCase):
    def setUp(self):
        smart._cache.clear()
        self.host = smart.GATE_HOSTS[0]
        self.query = smart._query(self.host)

    def test_dns_validation_and_ttl(self):
        self.assertEqual(smart._answers(answer(self.query), self.query), (["93.184.216.34"], 30))
        self.assertEqual(smart._answers(answer(self.query, ttl=9999), self.query)[1], 120)
        self.assertEqual(smart._answers(answer(self.query, ttl=0), self.query)[1], 0)
        for packet in (b"", b"xx" + answer(self.query)[2:], answer(self.query)[:-1],
                       answer(self.query, "127.65.71.2"), answer(self.query, "10.0.0.1")):
            with self.assertRaises((ValueError, struct.error)):
                smart._answers(packet, self.query)

    def test_dns_compression_loop_rejected(self):
        with self.assertRaises(ValueError):
            smart._name(b"\xc0\x00", 0)

    def test_failed_dns_response_rejected(self):
        for flags in (0x0100, 0x8380, 0x8183):
            packet = bytearray(answer(self.query))
            packet[2:4] = struct.pack("!H", flags)
            with self.assertRaises(ValueError):
                smart._answers(bytes(packet), self.query)

    @patch("httpx.Client")
    def test_http2_resolver_does_not_use_proxy_environment_and_caches(self, client):
        transport = client.return_value.__enter__.return_value
        def respond(url, content, headers):
            return Mock(content=answer(content), headers={"content-type": "application/dns-message"})
        transport.post.side_effect = respond
        self.assertEqual(smart.resolve(self.host, {}), ["93.184.216.34"])
        self.assertEqual(smart.resolve(self.host, {}), ["93.184.216.34"])
        self.assertEqual(transport.post.call_count, 1)
        self.assertEqual(client.call_args.kwargs, {"http2": True, "trust_env": False, "timeout": 8})
        smart.resolve(self.host, {"google_smart_doh": "https://resolver.example/dns-query"})
        self.assertEqual(transport.post.call_count, 2)

    @patch("google_smart_dns.socket.create_connection")
    @patch("google_smart_dns.resolve", return_value=["93.184.216.34", "93.184.216.35"])
    def test_connection_uses_public_literal_addresses_not_system_dns(self, resolve, connect):
        connected = Mock()
        connect.side_effect = [OSError("first address offline"), connected]
        self.assertIs(smart.connect(self.host, 443, {}), connected)
        self.assertEqual([call.args[0] for call in connect.call_args_list],
                         [("93.184.216.34", 443), ("93.184.216.35", 443)])
        connected.settimeout.assert_called_once_with(None)

    def test_scope_and_url_validation(self):
        with self.assertRaises(ValueError):
            smart.resolve("accounts.google.com", {})
        with self.assertRaises(ValueError):
            smart.connect(self.host, 80, {})
        for url in ("http://example.com", "https://user:pass@example.com", "https://"):
            with self.assertRaises(ValueError):
                smart.resolver_url({"google_smart_doh": url})


if __name__ == "__main__":
    unittest.main()
