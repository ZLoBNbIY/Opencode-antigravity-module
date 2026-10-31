import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
from contextlib import contextmanager
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'gui-manager'))
import openai_manager


class FakeResponse:
    def __init__(self, payload):
        self._payload = json.dumps(payload).encode()

    def read(self):
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, * exc):
        return False


class OpenAiTokenSharingTests(unittest.TestCase):
    def test_generate_pkce_pair_matches_sha256_s256(self):
        verifier, challenge = openai_manager.generate_pkce()
        import base64, hashlib
        digest = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode('ascii')).digest()).decode('ascii').rstrip('=')
        self.assertEqual(challenge, digest)
        self.assertNotEqual(verifier, challenge)

    @patch('openai_manager._get_http_opener')
    def test_refresh_uses_token_sharing_endpoint_when_client_id_present(self, opener):
        opener.return_value.open.return_value = FakeResponse({'access_token': 'new-access', 'refresh_token': 'new-refresh'})
        account = {'refresh': 'r', 'clientID': 'client_abc', 'expires': int(time.time() * 1000) + 3600000}
        with tempfile.TemporaryDirectory() as temp_dir:
            openai_manager.refresh_openai_token(account)
            request = opener.return_value.open.call_args[0][0]
            self.assertEqual(request.full_url, openai_manager.OPENAI_TOKEN_URL)
            self.assertIn('client_abc', request.data.decode())
            self.assertIn('resource', request.data.decode())
        self.assertEqual(account['access'], 'new-access')

    @patch('openai_manager._get_http_opener')
    def test_refresh_uses_legacy_endpoint_without_client_id(self, opener):
        opener.return_value.open.return_value = FakeResponse({'access_token': 'legacy-access', 'refresh_token': 'legacy-refresh'})
        account = {'refresh': 'r', 'expires': int(time.time() * 1000) + 3600000}
        openai_manager.refresh_openai_token(account)
        request = opener.return_value.open.call_args[0][0]
        self.assertEqual(request.full_url, openai_manager.OPENAI_LEGACY_TOKEN_URL)
        self.assertEqual(account['access'], 'legacy-access')

    @patch('openai_manager._get_http_opener')
    def test_models_parse_token_sharing_shape_and_filters(self, opener):
        opener.return_value.open.return_value = FakeResponse({
            'models': [
                {'slug': 'gpt-6-sol', 'display_name': 'GPT-6 Sol', 'visibility': 'list',
                 'supported_in_api': True, 'context_window': 400000},
                {'slug': 'hidden-model', 'visibility': 'hidden', 'supported_in_api': True},
                {'slug': 'tool-only', 'visibility': 'list', 'supported_in_api': False},
                {'display_name': 'broken'},
            ]
        })
        account = {'access': 'token', 'expires': int(time.time() * 1000) + 3600000}
        models = openai_manager.fetch_openai_models(account)
        request = opener.return_value.open.call_args[0][0]
        self.assertEqual(request.full_url, openai_manager.OPENAI_MODELS_URL)
        self.assertEqual([m['id'] for m in models], ['gpt-6-sol'])
        self.assertEqual(models[0]['name'], 'GPT-6 Sol')
        self.assertEqual(account['models'], models)

    @patch('openai_manager._get_http_opener')
    def test_models_accept_platform_data_shape(self, opener):
        opener.return_value.open.return_value = FakeResponse({
            'object': 'list',
            'data': [{'id': 'gpt-5.5', 'display_name': 'GPT-5.5'}]
        })
        account = {'access': 'token', 'expires': int(time.time() * 1000) + 3600000}
        models = openai_manager.fetch_openai_models(account)
        self.assertEqual([m['id'] for m in models], ['gpt-5.5'])

    @patch('openai_manager._get_http_opener')
    def test_models_failure_returns_cached_list(self, opener):
        opener.return_value.open.side_effect = TimeoutError('network down')
        cached = [{'id': 'gpt-6-sol', 'name': 'GPT-6 Sol', 'context': 1}]
        account = {'access': 'token', 'expires': int(time.time() * 1000) + 3600000, 'models': list(cached)}
        models = openai_manager.fetch_openai_models(account)
        self.assertEqual(models, cached)

    def test_sync_methods_and_metadata_follow_account_shape(self):
        sharing = {"accountId": "acc1", "email": "a@b.c", "clientID": "client_x", "scopes": ["chatgpt.tokens.use.direct"]}
        self.assertEqual(openai_manager._openai_method_for(sharing), openai_manager.TOKEN_SHARING_METHOD)
        metadata = openai_manager._openai_credential_metadata(sharing)
        self.assertEqual(metadata['clientID'], 'client_x')
        self.assertIn('chatgpt.tokens.use.direct', metadata['scopes'])
        legacy = {'accountId': 'acc2', 'email': 'a@b.c'}
        self.assertEqual(openai_manager._openai_method_for(legacy), openai_manager.LEGACY_BROWSER_METHOD)
        self.assertNotIn('clientID', openai_manager._openai_credential_metadata(legacy))

    def _removed_context(self, temp_dir, accounts, active_id):
        accounts_file = Path(temp_dir) / 'openai-accounts.json'
        auth_files = [Path(temp_dir) / 'auth.json']
        # auth.json points at the current active account, mirroring real Hub state
        active = next((a for a in accounts if a['accountId'] == active_id), None)
        auth_files[0].write_text(json.dumps({
            'openai': {'type': 'oauth', 'access': 'old-access', 'refresh': 'old-refresh',
                       'expires': 0, 'accountId': active['accountId'] if active else None},
        }), encoding='utf-8')
        accounts_file.write_text(json.dumps(accounts), encoding='utf-8')
        return accounts_file, auth_files

    def test_remove_openai_account_of_active_rotates_to_next(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            accounts = [
                {'accountId': 'pool-1', 'email': 'one@test', 'is_active': False},
                {'accountId': 'active-1', 'email': 'two@test', 'is_active': True},
            ]
            accounts_file, auth_files = self._removed_context(temp_dir, accounts, 'active-1')
            with patch.object(openai_manager, 'OPENAI_ACCOUNTS_FILE', accounts_file), \
                    patch.object(openai_manager, 'AUTH_FILES', auth_files), \
                    patch.object(openai_manager, 'OPENCODE_DB_FILE', Path(temp_dir) / 'missing.db'), \
                    patch.object(openai_manager, 'find_opencode_cli', return_value=None):
                self.assertTrue(openai_manager.remove_openai_account('active-1'))
                saved = json.loads(accounts_file.read_text(encoding='utf-8'))
                self.assertEqual([acc['accountId'] for acc in saved], ['pool-1'])
                self.assertTrue(saved[0]['is_active'])
                auth = json.loads(auth_files[0].read_text(encoding='utf-8'))
                self.assertEqual(auth.get('openai', {}).get('accountId'), 'pool-1')

    def test_remove_openai_account_of_last_clears_auth(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            accounts = [{'accountId': 'active-1', 'email': 'two@test', 'is_active': True}]
            accounts_file, auth_files = self._removed_context(temp_dir, accounts, 'active-1')
            with patch.object(openai_manager, 'OPENAI_ACCOUNTS_FILE', accounts_file), \
                    patch.object(openai_manager, 'AUTH_FILES', auth_files), \
                    patch.object(openai_manager, 'OPENCODE_DB_FILE', Path(temp_dir) / 'missing.db'), \
                    patch.object(openai_manager, 'find_opencode_cli', return_value=None):
                self.assertTrue(openai_manager.remove_openai_account('active-1'))
                self.assertEqual(json.loads(accounts_file.read_text(encoding='utf-8')), [])
                auth = json.loads(auth_files[0].read_text(encoding='utf-8'))
                self.assertNotIn('openai', auth)

    def test_remove_openai_account_pool_entry_keeps_active(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            accounts = [
                {'accountId': 'active-1', 'email': 'one@test', 'is_active': True},
                {'accountId': 'pool-2', 'email': 'two@test', 'is_active': False},
            ]
            accounts_file, auth_files = self._removed_context(temp_dir, accounts, 'active-1')
            with patch.object(openai_manager, 'OPENAI_ACCOUNTS_FILE', accounts_file), \
                    patch.object(openai_manager, 'AUTH_FILES', auth_files), \
                    patch.object(openai_manager, 'OPENCODE_DB_FILE', Path(temp_dir) / 'missing.db'), \
                    patch.object(openai_manager, 'find_opencode_cli', return_value=None):
                self.assertTrue(openai_manager.remove_openai_account('pool-2'))
                saved = json.loads(accounts_file.read_text(encoding='utf-8'))
                self.assertEqual([acc['accountId'] for acc in saved], ['active-1'])
                auth = json.loads(auth_files[0].read_text(encoding='utf-8'))
                self.assertEqual(auth.get('openai', {}).get('accountId'), 'active-1')

    def test_set_active_openai_account_updates_store(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            accounts_file = Path(temp_dir) / 'openai-accounts.json'
            auth_files = [Path(temp_dir) / 'auth.json']
            accounts = [
                {'accountId': 'a1', 'email': 'one@test', 'is_active': True},
                {'accountId': 'a2', 'email': 'two@test', 'is_active': False},
            ]
            accounts_file.write_text(json.dumps(accounts), encoding='utf-8')
            with patch.object(openai_manager, 'OPENAI_ACCOUNTS_FILE', accounts_file), \
                    patch.object(openai_manager, 'AUTH_FILES', auth_files), \
                    patch.object(openai_manager, 'OPENCODE_DB_FILE', Path(temp_dir) / 'missing.db'), \
                    patch.object(openai_manager, 'find_opencode_cli', return_value=None):
                self.assertTrue(openai_manager.set_active_openai_account('a2'))
                saved = json.loads(accounts_file.read_text(encoding='utf-8'))
                self.assertEqual(saved[0]['is_active'], False)
                self.assertEqual(saved[1]['is_active'], True)


if __name__ == '__main__':
    unittest.main()
