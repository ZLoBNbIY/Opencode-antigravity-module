import json
import io
import subprocess
from contextlib import redirect_stdout
from pathlib import Path
import sqlite3
import sys
from tempfile import TemporaryDirectory
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
            with self.assertRaises(urllib.error.HTTPError):
                direct.open(base + '/auth/callback?error=cancelled&state=unrelated', timeout=2)
            with direct.open(base + '/auth/callback?code=test&state=' + state, timeout=2) as response:
                self.assertEqual(response.status, 200)
                self.assertIn('Ответ браузера получен', response.read().decode('utf-8'))
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

    def test_empty_hub_pool_imports_active_opencode_database_account(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / 'opencode.db'
            pool = root / 'openai-accounts.json'
            credential = {
                'type': 'oauth', 'methodID': 'chatgpt-browser',
                'access': 'fake', 'refresh': 'fake-refresh', 'expires': 123,
                'metadata': {'accountID': 'account-1', 'email': 'chatgpt@example.com'},
            }
            conn = sqlite3.connect(database)
            with conn:
                conn.execute('CREATE TABLE credential (integration_id, active, time_updated, value)')
                conn.executemany('INSERT INTO credential VALUES (?, ?, ?, ?)', [
                    ('openai', 1, 1, json.dumps(credential)),
                    ('openai', 0, 2, json.dumps({**credential, 'metadata': {'accountID': 'inactive'}})),
                ])
            conn.close()
            with patch.multiple(manager, CONFIG_DIR=root, OPENAI_ACCOUNTS_FILE=pool,
                                AUTH_FILES=[root / 'auth.json'], OPENCODE_DB_FILE=database):
                accounts = manager.load_openai_accounts()
                self.assertEqual(manager.load_openai_accounts(), accounts)
            self.assertEqual(len(accounts), 1)
            self.assertEqual(accounts[0]['id'], 'account-1')
            self.assertEqual(accounts[0]['email'], 'chatgpt@example.com')
            self.assertTrue(accounts[0]['is_active'])


    def test_cli_import_failure_does_not_expose_tokens(self):
        for error in (subprocess.CalledProcessError(1, ["cli"], stderr="secret-token"),
                      subprocess.TimeoutExpired(["cli"], 10)):
            with self.subTest(error=type(error).__name__):
                output = io.StringIO()
                with patch.object(manager, "find_opencode_cli", return_value="cli"), \
                     patch.object(manager, "get_openai_cred_id", return_value="fixture"), \
                     patch.object(manager.subprocess, "run", side_effect=error) as run, redirect_stdout(output):
                    self.assertFalse(manager.sync_opencode_cli_openai({"access": "secret-token"}))
                self.assertNotIn("secret-token", output.getvalue())
                args, kwargs = run.call_args
                self.assertEqual(args[0], ["cli", "auth", "import"])
                self.assertTrue(kwargs["check"])
                self.assertIn("secret-token", kwargs["input"])

    def test_pool_migrates_legacy_and_does_not_overwrite_unreadable_record(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            pool = root / "openai-accounts.json"
            pool.write_text('[{"access":"legacy"}]', encoding="utf-8")
            with patch.multiple(manager, CONFIG_DIR=root, OPENAI_ACCOUNTS_FILE=pool), \
                 patch.object(manager, "get_active_auth_openai", return_value=None):
                self.assertEqual(manager.load_openai_accounts()[0]["access"], "legacy")
                self.assertIn("protection", json.loads(pool.read_text(encoding="utf-8")))
                invalid = '{"protection":"invalid","payload":"unreadable"}'
                pool.write_text(invalid, encoding="utf-8")
                self.assertFalse(manager.save_openai_accounts([]))
                self.assertEqual(pool.read_text(encoding="utf-8"), invalid)


if __name__ == '__main__':
    unittest.main()
