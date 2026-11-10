import io
from pathlib import Path
import sys
import time
import unittest
import urllib.error
from unittest.mock import Mock, MagicMock, patch

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

    def test_auto_rotate_skips_disabled_and_non_candidate_accounts(self):
        active = {
            'id': 'acc_1',
            'accountId': 'acc_1',
            'email': 'a1@test.com',
            'is_active': True,
            'enabled': True,
            'candidate': True,
            'quota': {'limit_reached': True, 'primary': {'remaining_percent': 0}, 'secondary': {'remaining_percent': 0}},
        }
        # Disabled account should be skipped
        disabled_acc = {
            'id': 'acc_2',
            'accountId': 'acc_2',
            'email': 'a2@test.com',
            'is_active': False,
            'enabled': False,
            'candidate': True,
            'quota': {'limit_reached': False, 'primary': {'remaining_percent': 100}, 'secondary': {'remaining_percent': 100}},
        }
        # Non-candidate (standalone) account should be skipped
        standalone_acc = {
            'id': 'acc_3',
            'accountId': 'acc_3',
            'email': 'a3@test.com',
            'is_active': False,
            'enabled': True,
            'candidate': False,
            'quota': {'limit_reached': False, 'primary': {'remaining_percent': 100}, 'secondary': {'remaining_percent': 100}},
        }
        # Eligible candidate
        eligible_acc = {
            'id': 'acc_4',
            'accountId': 'acc_4',
            'email': 'a4@test.com',
            'is_active': False,
            'enabled': True,
            'candidate': True,
            'quota': {'limit_reached': False, 'primary': {'remaining_percent': 100}, 'secondary': {'remaining_percent': 100}},
        }

        accounts = [active, disabled_acc, standalone_acc, eligible_acc]
        with patch('openai_manager.set_active_openai_account', return_value=True):
            rotated, msg = openai_manager.check_and_auto_rotate_openai(accounts)
            self.assertTrue(rotated)
            self.assertTrue(eligible_acc['is_active'])
            self.assertFalse(standalone_acc['is_active'])
            self.assertFalse(disabled_acc['is_active'])

    @patch('openai_manager._get_http_opener')
    def test_openai_model_generation_success(self, mock_opener):
        import health_checker

        sse_stream = (
            b'event: response.output_text.delta\r\n'
            b'data: {"type":"response.output_text.delta","delta":"Hello from ChatGPT"}\r\n\r\n'
            b'event: response.completed\r\n'
            b'data: {"type":"response.completed"}\r\n\r\n'
        )
        fake_resp = MagicMock()
        fake_resp.readline.side_effect = sse_stream.splitlines(keepends=True) + [b'']
        fake_resp.__enter__.return_value = fake_resp
        mock_opener.return_value.open.return_value = fake_resp

        account = {'access': 'test-token', 'accountId': 'acc-123', 'email': 'test@test.com', 'expires': int(time.time() * 1000) + 3600000}
        res = health_checker.test_openai_model_generation(account, model='gpt-5.6-sol', timeout=5)
        self.assertTrue(res['ok'])
        self.assertEqual(res['status'], 'active')
        self.assertIn('Hello from ChatGPT', res['response_text'])
        self.assertIn('gpt-5.6-sol', res['message'])


if __name__ == '__main__':
    unittest.main()
