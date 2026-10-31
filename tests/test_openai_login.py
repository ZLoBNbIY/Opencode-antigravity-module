import json
from pathlib import Path
import sys
import unittest
import urllib.error
import urllib.parse
import urllib.request
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'gui-manager'))
import openai_manager as manager


class OpenAiLoginTests(unittest.TestCase):
    def login(self, save_ok=True, token_error=False):
        original_server = manager._OAuthServer
        def server(address, state):
            self.server = original_server(('127.0.0.1', 0), state)
            return self.server
        def browser(url):
            state = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)['state'][0]
            base = f'http://127.0.0.1:{self.server.server_port}'
            direct = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            # A favicon or unrelated request must not consume the callback listener.
            with self.assertRaises(urllib.error.HTTPError):
                direct.open(base + '/favicon.ico', timeout=2)
            with direct.open(base + '/auth/callback?code=test&state=' + state, timeout=2) as response:
                self.assertEqual(response.status, 200)
            return True
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.read.return_value = json.dumps({'access_token':'fake', 'expires_in':3600}).encode()
        opener = Mock()
        opener.open.return_value = response
        if token_error:
            opener.open.side_effect = OSError('exchange unavailable')
        with patch.object(manager, '_OAuthServer', side_effect=server), \
             patch.object(manager.webbrowser, 'open', side_effect=browser), \
             patch.object(manager, '_get_http_opener', return_value=opener), \
             patch.object(manager, 'fetch_openai_usage', return_value={}), \
             patch.object(manager, 'load_openai_accounts', return_value=[]), \
             patch.object(manager, 'save_openai_accounts', return_value=save_ok) as save, \
             patch.object(manager, 'write_active_auth_openai', return_value=True) as activate:
            result = manager.login_openai_browser(timeout=2)
        return result, save, activate

    def test_unrelated_request_does_not_break_callback_and_account_is_saved(self):
        result, save, activate = self.login()
        self.assertTrue(result[0], result[1])
        save.assert_called_once()
        activate.assert_called_once()
        self.assertEqual(self.server.fileno(), -1)

    def test_save_failure_is_not_reported_as_success(self):
        result, save, activate = self.login(save_ok=False)
        self.assertFalse(result[0])
        activate.assert_not_called()

    def test_token_exchange_failure_is_reported(self):
        result, save, activate = self.login(token_error=True)
        self.assertFalse(result[0])
        self.assertIn('exchange unavailable', result[1])
        save.assert_not_called()


if __name__ == '__main__':
    unittest.main()
