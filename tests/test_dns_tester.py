from pathlib import Path
import socket
import struct
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'gui-manager'))
import dns_tester


class DnsAvailabilityTests(unittest.TestCase):
    @patch('dns_tester.urllib.request.urlopen')
    @patch('dns_tester._parse_a_record_ip', return_value='203.0.113.2')
    @patch('dns_tester.urllib.request.build_opener')
    def test_doh_check_bypasses_provider_proxy_and_uses_explicit_domain(self, build, parse, urlopen):
        response = Mock()
        response.read.return_value = b'dns-answer'
        build.return_value.open.return_value.__enter__ = Mock(return_value=response)
        build.return_value.open.return_value.__exit__ = Mock(return_value=False)
        result = dns_tester.test_doh_endpoint('https://resolver.test/dns-query', domain='chatgpt.com')
        self.assertTrue(result['ok'])
        self.assertEqual(result['resolved_ip'], '203.0.113.2')
        self.assertEqual(build.call_args.args[0].proxies, {})
        request = build.return_value.open.call_args.args[0]
        self.assertIn(b'chatgpt', request.data)
        parse.assert_called_once_with(b'dns-answer', expected_txid=int.from_bytes(request.data[:2], 'big'))
        urlopen.assert_not_called()

    @patch('dns_tester.urllib.request.build_opener')
    @patch('dns_tester.secrets.randbits', return_value=0x1234)
    def test_doh_accepts_only_the_matching_transaction(self, randbits, build):
        response = Mock()
        opener = build.return_value.open.return_value
        opener.__enter__ = Mock(return_value=response)
        opener.__exit__ = Mock(return_value=False)
        for txid, expected_ok in ((0x1234, True), (0x1235, False)):
            with self.subTest(txid=txid):
                question = dns_tester._build_dns_query('chatgpt.com', txid=txid)[12:]
                response.read.return_value = (struct.pack('!HHHHHH', txid, 0x8180, 1, 1, 0, 0)
                                              + question
                                              + struct.pack('!HHHIH4B', 0xc00c, 1, 1, 60, 4, 203, 0, 113, 2))
                result = dns_tester.test_doh_endpoint('https://resolver.test/dns-query', domain='chatgpt.com')
                self.assertEqual(result['ok'], expected_ok)

    @patch('dns_tester.socket.socket')
    def test_standard_dns_receives_only_on_socket_connected_to_configured_resolver(self, socket_factory):
        sock = socket_factory.return_value
        def reply(_size):
            query = sock.send.call_args.args[0]
            txid = int.from_bytes(query[:2], 'big')
            return (struct.pack('!HHHHHH', txid, 0x8180, 1, 1, 0, 0) + query[12:]
                    + struct.pack('!HHHIH4B', 0xc00c, 1, 1, 60, 4, 203, 0, 113, 2))
        sock.recv.side_effect = reply
        for resolver, family in (('192.0.2.1', socket.AF_INET), ('2001:db8::1', socket.AF_INET6)):
            with self.subTest(resolver=resolver):
                socket_factory.reset_mock()
                result = dns_tester.test_standard_dns(resolver, domain='chatgpt.com')
                self.assertEqual(result['resolved_ip'], '203.0.113.2')
                socket_factory.assert_called_once_with(family, socket.SOCK_DGRAM)
                sock.connect.assert_called_once_with((resolver, 53))
                self.assertEqual([call[0] for call in sock.mock_calls],
                                 ['settimeout', 'connect', 'send', 'recv', 'close'])

    def test_rejects_nxdomain_txid_mismatch_and_plaintext_doh(self):
        # NXDOMAIN (rcode=3) with an A record in additional section must be rejected
        nxdomain = struct.pack('!HHHHHH', 0x1234, 0x8183, 0, 0, 0, 1) + b'\x00\x00\x01\x00\x01\x00\x00\x00\x01\x00\x04\x01\x02\x03\x04'
        self.assertIsNone(dns_tester._parse_a_record_ip(nxdomain, expected_txid=0x1234))

        # Valid answer with wrong txid must be rejected
        valid_other_txid = struct.pack('!HHHHHH', 0x9999, 0x8180, 0, 1, 0, 0) + b'\x00\x00\x01\x00\x01\x00\x00\x00\x3c\x00\x04\x01\x02\x03\x04'
        self.assertIsNone(dns_tester._parse_a_record_ip(valid_other_txid, expected_txid=0x1234))
        self.assertEqual(dns_tester._parse_a_record_ip(valid_other_txid, expected_txid=0x9999), '1.2.3.4')

        # Plaintext http:// DoH must be rejected
        res = dns_tester.test_doh_endpoint('http://resolver.test/dns-query')
        self.assertFalse(res['ok'])


if __name__ == '__main__':
    unittest.main()
