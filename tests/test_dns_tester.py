from pathlib import Path
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
        urlopen.assert_not_called()


if __name__ == '__main__':
    unittest.main()
