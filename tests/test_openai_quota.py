import io
from pathlib import Path
import sys
import time
import unittest
import urllib.error
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'gui-manager'))
import openai_manager


class OpenAiQuotaTests(unittest.TestCase):
    def test_missing_windows_are_unknown_and_exhausted_window_is_zero(self):
        result = openai_manager._parse_usage_payload({'rate_limit': {}}, {})
        self.assertEqual(result['primary'], {})
        self.assertEqual(result['secondary'], {})
        result = openai_manager._parse_usage_payload({'rate_limit': {
            'primary_window': {'used_percent': 100, 'limit_window_seconds': 18000},
            'secondary_window': {'used_percent': 20, 'limit_window_seconds': 604800},
        }}, {})
        self.assertEqual(result['window_5h']['remaining_percent'], 0)
        self.assertEqual(result['window_weekly']['remaining_percent'], 80)

    @patch('openai_manager._get_http_opener')
    @patch('openai_manager.refresh_openai_token')
    def test_repeated_unauthorized_response_retries_only_once(self, refresh, opener):
        account = {'access': 'test', 'expires': int(time.time() * 1000) + 3600000}
        refresh.return_value = (True, account)
        opener.return_value.open.side_effect = urllib.error.HTTPError('https://example.test', 401, 'Unauthorized', {}, io.BytesIO())
        result = openai_manager.fetch_openai_usage(account)
        self.assertEqual(opener.return_value.open.call_count, 2)
        refresh.assert_called_once()
        self.assertEqual(result, {'status': 'error', 'primary': {}, 'secondary': {}})

    @patch('openai_manager._get_http_opener')
    def test_failed_refresh_labels_cached_quota_as_stale(self, opener):
        opener.return_value.open.side_effect = TimeoutError()
        account = {'expires': int(time.time() * 1000) + 3600000,
                   'quota': {'status': 'ok', 'primary': {'remaining_percent': 0}, 'last_checked': 123}}
        result = openai_manager.fetch_openai_usage(account)
        self.assertEqual(result['status'], 'stale')
        self.assertEqual(result['primary']['remaining_percent'], 0)
        self.assertEqual(result['last_checked'], 123)


if __name__ == '__main__':
    unittest.main()
