import importlib.util
import json
from pathlib import Path
import threading
import tempfile
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import Mock, patch


class WebviewBackendTests(unittest.TestCase):
    def setUp(self):
        manager = ModuleType("antigravity_manager")
        manager.DEFAULT_CONFIG = {}
        manager.export_google_accounts = Mock(return_value=[])
        manager.enrich_google_accounts_with_generation_store = Mock(return_value=[])
        manager.get_active_google_account_index = Mock(return_value=0)
        manager.get_active_google_health_account = Mock(return_value=None)
        self.manager = manager
        self.vless = SimpleNamespace(find_core_executable=Mock(return_value=None), is_running=Mock(return_value=False))
        self.openai = SimpleNamespace(load_openai_accounts=Mock(return_value=[]))
        self.router = SimpleNamespace(PORT=10880, start=Mock(return_value=True), _dns_lock=threading.Lock(),
                                      select_upstream=Mock(return_value=None), _connect_upstream=Mock())
        self.router.connect_routed = Mock(side_effect=lambda host, port, **kwargs: (self.router._connect_upstream(None, host, port), None))
        self.auto = SimpleNamespace(refresh=Mock(), state=Mock(return_value={"selected":None, "running":False, "rows":[], "status":"pending"}))
        self.xpiki = SimpleNamespace(load_xpiki_config=Mock(return_value={}), DEFAULT_BASE_URL='https://api.xpiki.com/v1',
                                     XPIKI_MODELS={'claude-test': {'name': 'Claude Test'}})
        self.openrouter = SimpleNamespace(load_api_key=Mock(return_value=''), configure_models=Mock(),
                                          sync_opencode_credential=Mock())
        self.claude = SimpleNamespace(load_accounts=Mock(return_value=[{"email": "test@example.com"}]))
        modules = {
            "antigravity_manager": manager,
            "proxy_config": SimpleNamespace(sync_provider_routes=Mock()),
            "opencode_config": ModuleType("opencode_config"),
            "auto_updater": ModuleType("auto_updater"),
            "openai_manager": self.openai,
            "claude_manager": SimpleNamespace(claude_service=self.claude),
            "vless_manager": SimpleNamespace(get_http_port=Mock(return_value=20809), get_socks_port=Mock(return_value=20808),
                                             vless_service=self.vless, VlessParser=SimpleNamespace(parse_url=Mock())),
            "provider_proxy": self.router,
            "auto_router": SimpleNamespace(router=self.auto),
            "dns_tester": ModuleType("dns_tester"),
            "google_smart_dns": SimpleNamespace(resolver_url=lambda cfg: cfg.get('google_smart_doh') or 'https://dns.example/query'),
            "xpiki_manager": self.xpiki,
            "openrouter_manager": self.openrouter,
        }
        path = Path(__file__).resolve().parent.parent / "gui-manager" / "webview_backend.py"
        spec = importlib.util.spec_from_file_location("hub_backend_test", path)
        self.backend = importlib.util.module_from_spec(spec)
        with patch.dict("sys.modules", modules):
            spec.loader.exec_module(self.backend)
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent.parent)
        self.assertEqual(Path(self.temp.name).resolve().parent, Path(__file__).resolve().parent.parent)
        self.addCleanup(self.temp.cleanup)
        self.backend.CONFIG_DIR = Path(self.temp.name)
        self.backend.ANTIGRAVITY_CONFIG_FILE = Path(self.temp.name) / 'antigravity.json'
        self.backend.OPENCODE_CONFIG_FILE = Path(self.temp.name) / 'opencode.json'

    def test_google_login_waits_and_migrates_before_reporting_success(self):
        self.manager.get_node_executable = Mock(return_value="node")
        self.manager.get_cli_js = Mock(return_value="cli.js")
        self.manager.repair_legacy_google_account_file = Mock(return_value=None)
        self.manager.run_silent_cmd = Mock(return_value=SimpleNamespace(returncode=0, stdout="", stderr=""))
        with patch.object(self.backend.os.path, "exists", return_value=True):
            result = self.backend.HubApi().add_google_account()
        self.assertEqual(result['status'], 'ok')
        self.assertEqual([c.args[0] for c in self.manager.run_silent_cmd.call_args_list],
                         [["node", "cli.js", "login"], ["node", "cli.js", "migrate", "--offline", "--yes"]])

    def test_google_login_failure_is_reported_without_migration(self):
        self.manager.get_node_executable = Mock(return_value="node")
        self.manager.get_cli_js = Mock(return_value="cli.js")
        self.manager.repair_legacy_google_account_file = Mock(return_value=None)
        self.manager.run_silent_cmd = Mock(return_value=SimpleNamespace(returncode=1, stdout="", stderr="login failed"))
        with patch.object(self.backend.os.path, "exists", return_value=True):
            result = self.backend.HubApi().add_google_account()
        self.assertEqual(result, {'status':'error', 'message':'login failed'})
        self.manager.run_silent_cmd.assert_called_once()

    def test_openai_failure_and_exception_reach_frontend_and_unlock_retry(self):
        self.openai.login_openai_browser = Mock(side_effect=[(False, 'token exchange failed', None),
                                                           RuntimeError('network unavailable'),
                                                           (True, 'saved', {'id':'test'})])
        api = self.backend.HubApi()
        self.assertEqual(api.add_openai_account(), {'status':'error', 'message':'token exchange failed'})
        self.assertEqual(api.add_openai_account(), {'status':'error', 'message':'network unavailable'})
        self.assertEqual(api.add_openai_account(), {'status':'ok', 'message':'saved'})

    def test_windows_bom_configs_do_not_hide_saved_accounts(self):
        self.backend.OPENCODE_CONFIG_FILE.write_text('{"disabled_providers": ["openrouter-free"]}', encoding='utf-8-sig')
        self.backend.ANTIGRAVITY_CONFIG_FILE.write_text('{"provider_routes": {"google": "dns"}}', encoding='utf-8-sig')
        self.manager.export_google_accounts.return_value = [{'id':'google-saved', 'email':'google@test'}]
        self.manager.enrich_google_accounts_with_generation_store.side_effect = lambda rows: rows
        self.openai.load_openai_accounts.return_value = [{'id':'openai-saved', 'email':'openai@test'}]
        api = self.backend.HubApi()
        with patch.object(api, 'is_opencode_running', return_value=False):
            state = api.get_state()
        self.assertEqual(len(state['accounts']), 1)
        self.assertEqual(len(state['openaiAccounts']), 1)
        self.assertEqual(state['routes'], {'google':'dns'})
        self.assertFalse(state['config']['providers_visibility']['openrouter'])
        self.assertIn('network', state)

    def test_state_uses_existing_claude_account_service(self):
        api = self.backend.HubApi()
        with patch.object(api, "load_config", return_value={}), patch.object(api, "is_opencode_running", return_value=False):
            state = api.get_state()
        self.assertEqual(state["claudeAccounts"], [{"email": "test@example.com", "is_active": True}])
        self.claude.load_accounts.assert_called_once_with()

    def test_claude_active_identity_uses_active_flag_without_exposing_session_keys(self):
        self.claude.load_accounts.return_value = [{'email':'idle@test','active':False,'session_key':'secret-cookie'},
                                                 {'email':'active@test','active':True,'session_key':'another-cookie'}]
        api = self.backend.HubApi()
        with patch.object(api, 'is_opencode_running', return_value=False):
            state = api.get_state()
        self.assertEqual([a['is_active'] for a in state['claudeAccounts']], [False, True])
        self.assertNotIn('cookie', json.dumps(state))

    def test_provider_key_labels_expose_only_last_four_characters(self):
        self.xpiki.load_xpiki_config.return_value = {'api_key':'xpiki-secret-1234','connected':True}
        self.openrouter.load_api_key.return_value = 'openrouter-secret-5678'
        state = self.backend.HubApi().get_provider_state()
        self.assertEqual(state['xpiki']['keyLabel'], '••••1234')
        self.assertEqual(state['openrouter']['keyLabel'], '••••5678')
        self.assertNotIn('secret', json.dumps(state))

    def test_dns_check_uses_explicit_domain(self):
        self.backend.dns_tester.test_standard_dns = Mock(return_value={'ok':True})
        self.backend.HubApi().test_dns('standard','1.1.1.1')
        self.backend.dns_tester.test_standard_dns.assert_called_once_with('1.1.1.1', domain='cloudcode-pa.googleapis.com')

    def test_google_active_identity_survives_filtered_export_order(self):
        raw = [{"id": "second", "email": "second@example.com", "accessToken": "secret"},
               {"id": "first", "email": "first@example.com"}]
        disk = [{"id": "first", "index": 1}, {"id": "incomplete", "index": 2}, {"id": "second", "index": 3}]
        self.manager.export_google_accounts.return_value = raw
        self.manager.enrich_google_accounts_with_generation_store.side_effect = lambda rows: rows if rows else disk
        self.manager.get_active_google_health_account.return_value = {"id": "second"}
        api = self.backend.HubApi()
        with patch.object(api, 'is_opencode_running', return_value=False):
            state = api.get_state()
        self.assertEqual([(a['id'], a['index'], a['is_active']) for a in state['accounts']],
                         [('second', 3, True), ('first', 1, False)])
        self.assertNotIn('secret', json.dumps(state))

    def test_network_save_keeps_ports_and_unrelated_settings(self):
        cfg = {'vless_http_port': 20809, 'vless_socks_port': 20808, 'debug': True}
        self.backend.ANTIGRAVITY_CONFIG_FILE.write_text(json.dumps(cfg))
        api = self.backend.HubApi()
        api.save_network_settings({'dns_mode': 'doh', 'doh_url': 'https://dns.example/query',
                                   'vless_http_port': 12345, 'vless_socks_port': 12346})
        saved = json.loads(self.backend.ANTIGRAVITY_CONFIG_FILE.read_text())
        self.assertEqual(saved['vless_http_port'], 20809)
        self.assertEqual(saved['vless_socks_port'], 20808)
        self.assertTrue(saved['debug'])
        self.assertEqual(saved['doh_url'], 'https://dns.example/query')
        self.router.start.assert_called_once()

    def test_invalid_dns_is_not_saved(self):
        api = self.backend.HubApi()
        with self.assertRaises(ValueError):
            api.save_network_settings({'dns_mode': 'standard', 'custom_dns': ['not-an-ip']})
        self.assertFalse(self.backend.ANTIGRAVITY_CONFIG_FILE.exists())

    def test_provider_toggles_preserve_credentials_and_other_disabled_providers(self):
        oc = {'disabled_providers': ['external-provider', 'openrouter'],
              'provider': {'openai': {'options': {'apiKey': 'keep-secret'}}}}
        self.backend.OPENCODE_CONFIG_FILE.write_text(json.dumps(oc))
        api = self.backend.HubApi()
        self.assertTrue(api.save_general_settings({'providers_visibility': {'openai': False, 'openrouter': False}}))
        saved = json.loads(self.backend.OPENCODE_CONFIG_FILE.read_text())
        self.assertEqual(saved['disabled_providers'], ['external-provider', 'openrouter', 'openai', 'openrouter-free'])
        self.assertEqual(saved['provider'], oc['provider'])
        api.save_general_settings({'providers_visibility': {'openai': True}})
        saved = json.loads(self.backend.OPENCODE_CONFIG_FILE.read_text())
        self.assertNotIn('openai', saved['disabled_providers'])
        self.assertIn('openrouter', saved['disabled_providers'])
        self.assertIn('openrouter-free', saved['disabled_providers'])

    def test_invalid_provider_toggles_do_not_change_config(self):
        api = self.backend.HubApi()
        with self.assertRaises(ValueError):
            api.save_general_settings({'providers_visibility': {'openai': 'false'}})
        self.assertFalse(self.backend.OPENCODE_CONFIG_FILE.exists())
        self.assertFalse(self.backend.ANTIGRAVITY_CONFIG_FILE.exists())

    def test_route_alias_targets_actual_claude_provider(self):
        api = self.backend.HubApi()
        api.set_provider_route('claude', 'dns')
        saved = api.load_config()
        self.assertEqual(saved['provider_routes'], {'claude-pro': 'dns'})
        with self.assertRaises(ValueError):
            api.set_provider_route('openai', 'google-smart')

    def test_domain_failure_remains_red_without_fake_latency(self):
        self.router._connect_upstream.side_effect = OSError('unavailable')
        api = self.backend.HubApi()
        rows = api.run_provider_diagnostics('openai')
        self.assertEqual([r['domain'] for r in rows], ['chatgpt.com', 'auth.openai.com', 'api.openai.com'])
        self.assertTrue(all(r['status'] == 'error' and r['latency_ms'] is None for r in rows))
        self.assertEqual(api.get_cached_diagnostics()['openai']['rows'], rows)
        self.assertFalse(api.get_cached_diagnostics()['openai']['running'])
        oc = self.router.connect_routed.call_args.kwargs['opencode_config']
        self.assertIn('openai', oc['provider'])

    def test_domain_cache_is_invalidated_by_network_changes(self):
        self.router._connect_upstream.side_effect = OSError('unavailable')
        api = self.backend.HubApi()
        api.run_provider_diagnostics('openai')
        self.assertTrue(api.get_cached_diagnostics()['openai']['rows'])
        self.backend.ANTIGRAVITY_CONFIG_FILE.write_text(json.dumps({'dns_mode':'doh', 'doh_url':'https://dns.example/query'}))
        self.assertEqual(api.get_cached_diagnostics()['openai']['rows'], [])
        self.assertIsNone(api.get_cached_diagnostics()['openai']['checkedAt'])

    def test_openrouter_applies_only_catalog_models_selected_by_user(self):
        api = self.backend.HubApi()
        api._openrouter_models = [{'id': 'free/model', 'name': 'Free'}, {'id': 'free/other', 'name': 'Other'}]
        self.openrouter.load_api_key.return_value = 'secret'
        api.apply_openrouter_models(['free/model'])
        self.openrouter.configure_models.assert_called_once_with([{'id': 'free/model', 'name': 'Free'}])
        with self.assertRaises(ValueError):
            api.apply_openrouter_models(['paid/not-in-catalog'])

    @unittest.skipUnless(importlib.util.find_spec("webview"), "pywebview required")
    def test_bridge_finishes_without_inspecting_native_window(self):
        from webview.util import inject_pywebview

        touched = threading.Event()

        class NativeWindow:
            @property
            def native(self):
                touched.set()
                raise RuntimeError("Native window properties must stay outside the JS bridge")

        window = SimpleNamespace(
            _js_api=self.backend.HubApi(NativeWindow()),
            _functions={},
            _expose_lock=threading.Lock(),
            events=SimpleNamespace(before_load=threading.Event(),
                                   _pywebviewready=threading.Event(), loaded=threading.Event()),
            run_js=Mock(),
        )
        with patch("webview.util.load_js_files", return_value=("bootstrap", "%(functions)s")):
            inject_pywebview("edgechromium", window)
            self.assertTrue(window.events.loaded.wait(2), "Bridge initialization did not finish")
        self.assertTrue(window.events._pywebviewready.is_set())
        self.assertFalse(touched.is_set(), "Bridge traversed a native Window property")
        functions = json.loads(window.run_js.call_args.args[0])
        names = {entry["func"] for entry in functions}
        self.assertIn("get_state", names)
        self.assertTrue(all("window_holder" not in name for name in names))


if __name__ == "__main__":
    unittest.main()
