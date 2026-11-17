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
        self.vless = SimpleNamespace(find_core_executable=Mock(return_value=None), is_running=Mock(return_value=False),
                                     start_tunnel=Mock(return_value=(True, "ok")),
                                     stop_tunnel=Mock(return_value=(True, "stopped")),
                                     test_connection=Mock(return_value={
                                         "ok": True, "message": "Туннель активен! IP: 1.2.3.4 (DE)",
                                         "ip": "1.2.3.4", "country": "DE", "latency_ms": 120}))
        self.openai = SimpleNamespace(load_openai_accounts=Mock(return_value=[]))
        self.router = SimpleNamespace(PORT=10880, start=Mock(return_value=True), _dns_lock=threading.Lock(),
                                      select_upstream=Mock(return_value=None), _connect_upstream=Mock())
        self.router.connect_routed = Mock(side_effect=lambda host, port, **kwargs: (self.router._connect_upstream(None, host, port), None))
        self.auto = SimpleNamespace(refresh=Mock(), state=Mock(return_value={"selected":None, "running":False, "rows":[], "status":"pending"}))
        self.xpiki = SimpleNamespace(load_xpiki_config=Mock(return_value={}), DEFAULT_BASE_URL='https://api.xpiki.com/v1',
                                     XPIKI_MODELS={'claude-test': {'name': 'Claude Test'}})
        self.openrouter = SimpleNamespace(load_api_key=Mock(return_value=''), configure_models=Mock(),
                                          sync_opencode_credential=Mock())
        self.tokenlavka = SimpleNamespace(
            load_api_key=Mock(return_value=''), provider_state=Mock(return_value={
                'hasKey': False, 'connected': False, 'selectedModels': [], 'models': [],
                'keyLabel': None, 'baseUrl': 'https://tokenlavka.com/v1', 'balance': {}}),
            fetch_balance=Mock(return_value={}), refresh_balance_silent=Mock(return_value={}),
            cached_balance=Mock(return_value={}), load_config=Mock(return_value={}), save_config=Mock(),
            test_connection=Mock(return_value=(True, 'ok')), save_api_key=Mock(),
            sync_opencode_credential=Mock(), configure_models=Mock(return_value=['gpt-6-luna']),
            selected_models=Mock(return_value=[]), disconnect=Mock(),
            DEFAULT_MODEL='gpt-6-luna', TOKENLAVKA_MODELS={'gpt-6-luna': {}})
        self.claude = SimpleNamespace(load_accounts=Mock(return_value=[{"email": "test@example.com"}]))
        self.deepseek = SimpleNamespace(
            load_api_key=Mock(return_value=""),
            save_api_key=Mock(),
            load_config=Mock(return_value={"base_url": "https://api.deepseek.com", "connected": False}),
            save_config=Mock(),
            provider_state=Mock(return_value={
                "hasKey": False, "connected": False, "keyLabel": None,
                "baseUrl": "https://api.deepseek.com", "balance": {"status": "no_key"},
            }),
            DEFAULT_BASE_URL="https://api.deepseek.com",
        )
        modules = {
            "antigravity_manager": manager,
            "proxy_config": SimpleNamespace(sync_provider_routes=Mock()),
            "opencode_config": ModuleType("opencode_config"),
            "auto_updater": ModuleType("auto_updater"),
            "openai_manager": self.openai,
            "claude_manager": SimpleNamespace(claude_service=self.claude),
            "vless_manager": SimpleNamespace(get_http_port=Mock(return_value=20809), get_socks_port=Mock(return_value=20808),
                                             vless_service=self.vless, VlessParser=SimpleNamespace(parse_url=Mock(
                                                 side_effect=lambda url: (_ for _ in ()).throw(ValueError("bad url"))
                                                 if not str(url).strip().startswith("vless://") else
                                                 {"tag": str(url).split("#")[-1], "server": "1.1.1.1", "port": 443}))),
            "provider_proxy": self.router,
            "auto_router": SimpleNamespace(router=self.auto),
            "dns_tester": ModuleType("dns_tester"),
            "xpiki_manager": self.xpiki,
            "openrouter_manager": self.openrouter,
            "tokenlavka_manager": self.tokenlavka,
            "deepseek_api": self.deepseek,
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
        self.backend.HUB_CONFIG_FILE = Path(self.temp.name) / 'hub_antigravity.json'

    def test_tokenlavka_configure_validates_saves_and_registers_models(self):
        self.tokenlavka.test_connection.return_value = (True, 'ok')
        api = self.backend.HubApi()
        result = api.configure_tokenlavka_api('sk-new-key', ['gpt-6-luna'])
        self.assertTrue(result['ok'])
        self.tokenlavka.test_connection.assert_called_once_with('sk-new-key')
        self.tokenlavka.save_api_key.assert_called_once_with('sk-new-key')
        self.tokenlavka.sync_opencode_credential.assert_called_once_with('sk-new-key')
        self.tokenlavka.configure_models.assert_called_once_with(['gpt-6-luna'], 'sk-new-key')

    def test_tokenlavka_invalid_key_is_reported_without_saving(self):
        self.tokenlavka.test_connection.return_value = (False, 'ключ отклонён')
        api = self.backend.HubApi()
        result = api.configure_tokenlavka_api('sk-bad', ['gpt-6-luna'])
        self.assertFalse(result['ok'])
        self.assertEqual(result['message'], 'ключ отклонён')
        self.tokenlavka.save_api_key.assert_not_called()
        self.tokenlavka.sync_opencode_credential.assert_not_called()

    def test_google_login_waits_migrates_refreshes_and_restarts_before_reporting_success(self):
        self.manager.get_node_executable = Mock(return_value="node")
        self.manager.get_cli_js = Mock(return_value="cli.js")
        self.manager.get_opencode_cli = Mock(return_value="cli.exe")
        self.manager.repair_legacy_google_account_file = Mock(return_value=None)
        self.manager.run_silent_cmd = Mock(return_value=SimpleNamespace(returncode=0, stdout="", stderr=""))
        self.manager.run_google_route_cmd = Mock(return_value=SimpleNamespace(returncode=0, stdout="", stderr=""))
        with patch.object(self.backend.os.path, "exists", return_value=True):
            result = self.backend.HubApi().add_google_account()
        self.assertEqual(result['status'], 'ok')
        self.assertIn('квоты обновлены', result['message'])
        self.assertIn('перезапущен', result['message'])
        self.manager.run_google_route_cmd.assert_called_once_with(
            ["node", "cli.js", "quota", "--refresh", "--json"], timeout=60)
        self.assertEqual([c.args[0] for c in self.manager.run_silent_cmd.call_args_list],
                         [["node", "cli.js", "login"],
                          ["node", "cli.js", "migrate", "--offline", "--yes"],
                          ["cli.exe", "service", "restart"]])

    def test_google_login_reports_when_state_refresh_or_service_restart_fails(self):
        self.manager.get_node_executable = Mock(return_value="node")
        self.manager.get_cli_js = Mock(return_value="cli.js")
        self.manager.get_opencode_cli = Mock(return_value=None)
        self.manager.repair_legacy_google_account_file = Mock(return_value=None)
        self.manager.run_silent_cmd = Mock(return_value=SimpleNamespace(returncode=0, stdout="", stderr=""))
        self.manager.run_google_route_cmd = Mock(return_value=SimpleNamespace(returncode=1, stdout="", stderr="quota failed"))
        with patch.object(self.backend.os.path, "exists", return_value=True):
            result = self.backend.HubApi().add_google_account()
        self.assertEqual(result['status'], 'ok')
        self.assertIn('квоты обновить не удалось', result['message'])
        self.assertIn('CLI OpenCode не найден', result['message'])
        self.assertIn('перезапустите OpenCode вручную', result['message'])

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

    def test_restart_restarts_background_service_before_reopening_desktop(self):
        self.manager.get_opencode_cli = Mock(return_value='cli.exe')
        self.manager.get_opencode_exe = Mock(return_value='OpenCode.exe')
        result = SimpleNamespace(returncode=0, stdout='', stderr='')
        self.manager.run_silent_cmd = Mock(return_value=result)
        api = self.backend.HubApi()
        calls = Mock()
        calls.attach_mock(self.manager.run_silent_cmd, 'service')
        with patch.object(self.backend.os.path, 'exists', return_value=True), \
             patch.object(api, 'stop_opencode', return_value=True) as stop, \
             patch.object(api, 'start_opencode', return_value=True) as start:
            calls.attach_mock(stop, 'stop')
            calls.attach_mock(start, 'start')
            self.assertTrue(api.restart_opencode())
        self.assertEqual([c[0] for c in calls.mock_calls], ['stop', 'service', 'start'])
        self.manager.run_silent_cmd.assert_called_once_with(['cli.exe', 'service', 'restart'], timeout=45)

    def test_restart_service_failure_is_reported_and_retry_is_possible(self):
        self.manager.get_opencode_cli = Mock(return_value='cli.exe')
        self.manager.get_opencode_exe = Mock(return_value='OpenCode.exe')
        self.manager.run_silent_cmd = Mock(return_value=SimpleNamespace(returncode=1, stdout='', stderr='service failed'))
        api = self.backend.HubApi()
        with patch.object(self.backend.os.path, 'exists', return_value=True), \
             patch.object(api, 'stop_opencode', return_value=True), \
             patch.object(api, 'start_opencode', return_value=True) as start:
            with self.assertRaisesRegex(RuntimeError, 'service failed'):
                api.restart_opencode()
            start.assert_not_called()
            self.manager.run_silent_cmd.return_value.returncode = 0
            self.assertTrue(api.restart_opencode())

    def test_restart_without_cli_preserves_running_desktop(self):
        self.manager.get_opencode_cli = Mock(return_value=None)
        api = self.backend.HubApi()
        with patch.object(api, 'stop_opencode') as stop:
            with self.assertRaisesRegex(RuntimeError, 'CLI OpenCode'):
                api.restart_opencode()
        stop.assert_not_called()

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
            api.set_provider_route('google', 'google-smart')

    def test_auto_and_default_are_both_accepted_route_modes(self):
        api = self.backend.HubApi()
        api.set_provider_route('google', 'auto')
        self.assertEqual(api.load_config()['provider_routes']['google'], 'auto')
        api.set_provider_route('google', 'default')
        self.assertEqual(api.load_config()['provider_routes']['google'], 'default')

    def test_reordering_proxy_pool_sets_top_item_as_primary(self):
        api = self.backend.HubApi()
        api.save_config({'proxy_pool': ['http://one.example:8000', 'http://two.example:8000'],
                         'proxy': 'http://one.example:8000'})
        result = api.move_proxy_pool_item(1, 0)
        self.assertTrue(result['ok'])
        saved = api.load_config()
        self.assertEqual(saved['proxy_pool'][0], 'http://two.example:8000')
        self.assertEqual(saved['proxy'], 'http://two.example:8000')

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

    def test_run_provider_deep_probe_invokes_health_checker(self):
        api = self.backend.HubApi()
        with patch("health_checker.test_provider_deep_probe") as mocked:
            mocked.return_value = {"ok": True, "status": "active", "message": "OK"}
            result = api.run_provider_deep_probe("google")
            mocked.assert_called_once_with("google", timeout=20)
            self.assertTrue(result["ok"])

    def test_set_vless_core_selects_installed_core(self):
        api = self.backend.HubApi()
        core_path = Path("/tmp/xray.exe")
        self.vless.find_core_executable.return_value = core_path
        result = api.set_vless_core("xray")
        self.assertTrue(result["ok"])
        self.assertEqual(api.load_config()["vless_core_path"], str(core_path))
        self.assertIn("xray", result["path"].lower())

    def test_set_vless_core_rejects_missing_or_unknown(self):
        api = self.backend.HubApi()
        self.vless.find_core_executable.return_value = None
        self.assertFalse(api.set_vless_core("sing-box")["ok"])
        with self.assertRaises(ValueError):
            api.set_vless_core("curl")

    def test_vless_pool_add_activate_and_delete(self):
        api = self.backend.HubApi()
        first = "vless://aaa@1.1.1.1:443?security=reality#DE"
        second = "vless://bbb@2.2.2.2:443?security=tls#US"
        self.assertTrue(api.add_vless_config(first)["ok"])
        self.assertTrue(api.add_vless_config(second)["ok"])
        state = api.get_vless_pool()
        self.assertEqual(len(state["pool"]), 2)
        self.assertEqual(state["active"], first)
        # First config becomes active automatically when it is the only one.
        activated = api.activate_vless_config(second)
        self.assertTrue(activated["ok"])
        self.assertEqual(api.load_config()["vless_url"], second)
        self.assertEqual(api.get_vless_pool()["activeEntry"]["url"], second)
        # Tunnel is stopped in this fixture, so activation probes the new config.
        self.vless.start_tunnel.assert_called()
        removed = api.delete_vless_config(second)
        self.assertTrue(removed["ok"])
        self.assertEqual(api.load_config()["vless_url"], first)
        self.assertEqual(len(api.get_vless_pool()["pool"]), 1)

    def test_vless_pool_normalizes_legacy_strings_and_caches_probe(self):
        api = self.backend.HubApi()
        url = "vless://aaa@1.1.1.1:443?security=reality#DE"
        api.save_config({"vless_pool": [url, url, "not-a-vless-url"]})
        pool = api.get_vless_pool()["pool"]
        self.assertEqual(len(pool), 1)
        self.assertEqual(pool[0]["url"], url)
        self.assertEqual(pool[0]["status"], "untested")
        checked = api.test_vless_config(url)
        self.assertTrue(checked["ok"])
        self.assertEqual(checked["ip"], "1.2.3.4")
        entry = api.get_vless_pool()["pool"][0]
        self.assertEqual(entry["status"], "ok")
        self.assertEqual(entry["ip"], "1.2.3.4")
        self.assertEqual(entry["country"], "DE")
        self.assertIsNotNone(entry["checked_at"])

    def test_fix_opencode_plugin_applies_prompt_and_route_patches(self):
        patcher = SimpleNamespace(
            sync_local_plugin_bundles=Mock(return_value={
                "ok": True, "copied": ["server.js"], "message": "synced"}),
            patch_prompt_sanitizer=Mock(return_value={
                "ok": True, "changed": ["server.js"], "already": [], "missing": [],
                "message": "Фикс применён."}),
            patch_auth_plugin_transport=Mock(return_value=True),
        )
        with patch.dict("sys.modules", {"cloudcode_route_patch": patcher}):
            result = self.backend.HubApi().fix_opencode_plugin()
        self.assertTrue(result["ok"])
        self.assertTrue(result["route_patched"])
        self.assertEqual(result["synced"], ["server.js"])
        self.assertIn("Маршрут Hub проверен", result["message"])
        patcher.sync_local_plugin_bundles.assert_called_once()
        patcher.patch_prompt_sanitizer.assert_called_once()
        patcher.patch_auth_plugin_transport.assert_called_once()

    def test_get_opencode_plugin_status_delegates_to_patcher(self):
        patcher = SimpleNamespace(get_prompt_sanitizer_status=Mock(return_value={
            "state": "patched", "found": 2, "patched": 2, "pending": 0, "message": "ok"}))
        with patch.dict("sys.modules", {"cloudcode_route_patch": patcher}):
            status = self.backend.HubApi().get_opencode_plugin_status()
        self.assertEqual(status["state"], "patched")
        patcher.get_prompt_sanitizer_status.assert_called_once()

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

    def test_save_general_settings_persists_close_to_tray(self):
        api = self.backend.HubApi()
        self.assertTrue(api.save_general_settings({"close_to_tray": False, "switch_on_first_rate_limit": False}))
        saved = api.load_config()
        self.assertFalse(saved["close_to_tray"])
        self.assertFalse(saved["switch_on_first_rate_limit"])

    def test_save_network_settings_persists_proxy_pool_failover_and_typed_proxy(self):
        api = self.backend.HubApi()
        api.save_network_settings({
            "proxy": "http://new.example:8080",
            "proxy_pool": ["http://old.example:8080"],
            "proxy_failover": False,
        })
        saved = api.load_config()
        self.assertFalse(saved["proxy_failover"])
        self.assertEqual(saved["proxy"], "http://new.example:8080")
        self.assertEqual(saved["proxy_pool"], ["http://new.example:8080", "http://old.example:8080"])

    def test_activate_vless_config_sets_vless_enabled_and_test_restarts_active(self):
        api = self.backend.HubApi()
        url = "vless://aaa@1.1.1.1:443?security=reality#DE"
        api.add_vless_config(url)
        res = api.activate_vless_config(url)
        self.assertTrue(res["ok"])
        self.assertTrue(api.load_config()["vless_enabled"])

        self.vless.is_running.return_value = True
        self.vless.start_tunnel.reset_mock()
        api.test_vless_config(url)
        # Once for _vless_probe, once to restore the active tunnel afterward.
        self.assertEqual(self.vless.start_tunnel.call_count, 2)

    def test_test_openai_account_imports_health_checker(self):
        self.openai.load_openai_accounts.return_value = [{"id": "oa-1", "email": "oa@example.com"}]
        api = self.backend.HubApi()
        with patch("health_checker.test_openai_model_generation", return_value={"message": "OK"}) as mocked:
            msg = api.test_openai_account("oa-1")
        self.assertEqual(msg, "OK")
        mocked.assert_called_once()

    def test_save_network_settings_ignores_vless_core_path(self):
        api = self.backend.HubApi()
        api.save_network_settings({"vless_core_path": "C:/evil/calc.exe", "dns_mode": "system"})
        self.assertNotIn("vless_core_path", api.load_config())

    def test_encrypted_backup_roundtrip_and_import_sanitizes_dangerous_fields(self):
        import crypto_backup
        api = self.backend.HubApi()
        api.save_config({"dns_mode": "system", "vless_core_path": "C:/safe/xray.exe"})
        backup_file = Path(self.temp.name) / "backup.agb"
        res = api.export_backup(str(backup_file), password="strong-password")
        self.assertTrue(res["ok"])
        self.assertTrue(res["encrypted"])
        raw = backup_file.read_bytes()
        self.assertTrue(crypto_backup.is_encrypted_backup(raw))
        self.assertNotIn(b"google_accounts", raw)

        # Tamper a plaintext backup with dangerous fields and verify import filters them.
        malicious = Path(self.temp.name) / "malicious.json"
        malicious.write_text(json.dumps({
            "config": {
                "vless_core_path": "C:/evil/payload.exe",
                "doh_url": "http://insecure.example/dns-query",
                "proxy": "ftp://bad.example:21",
                "dns_mode": "doh",
            }
        }), encoding="utf-8")
        imp = api.import_backup(str(malicious))
        self.assertTrue(imp["ok"])
        saved = api.load_config()
        self.assertEqual(saved["vless_core_path"], "C:/safe/xray.exe")
        self.assertEqual(saved["doh_url"], "")
        self.assertEqual(saved["proxy"], "")

    def test_full_backup_export_import_roundtrip_all_providers_and_missing_cli(self):
        self.manager.export_google_accounts.return_value = [{"email": "g@example.com", "refreshToken": "g-ref"}]
        self.manager.import_google_accounts = Mock(return_value=1)
        self.openai.load_openai_accounts.return_value = [{"id": "oa-1", "email": "o@example.com", "refresh": "o-ref"}]
        self.openai.import_openai_accounts = Mock(return_value=1)
        self.claude.load_accounts.return_value = [{"email": "c@example.com", "session_key": "sk-ant-1"}]
        self.claude.save_accounts = Mock()
        self.claude.configure_opencode_provider = Mock()
        self.xpiki.load_xpiki_config.return_value = {
            "api_key": "sk-xpiki", "base_url": "https://api.xpiki.com/v1",
            "enabled_models": ["claude-test"], "connected": True,
        }
        self.xpiki.save_xpiki_config = Mock()
        self.xpiki.configure_opencode = Mock()
        self.openrouter.load_api_key.return_value = "sk-or-1"
        self.openrouter.save_api_key = Mock()
        self.openrouter.sync_opencode_credential.side_effect = ValueError("CLI missing")
        self.tokenlavka.load_api_key.return_value = "sk-tl-1"
        self.tokenlavka.selected_models.return_value = ["gpt-6-luna"]
        self.tokenlavka.cached_balance.return_value = {"balance": 100}
        self.tokenlavka.sync_opencode_credential.side_effect = ValueError("CLI missing")
        self.deepseek.load_api_key.return_value = "sk-ds-1"
        self.deepseek.load_config.return_value = {"base_url": "https://api.deepseek.com", "connected": True}

        self.backend.OPENCODE_CONFIG_FILE.write_text(json.dumps({
            "provider": {"openrouter-free": {"models": {"free/m1": {"name": "M1"}}}}
        }), encoding="utf-8")

        api = self.backend.HubApi()
        api.save_config({
            "dns_mode": "doh",
            "doh_url": "https://dns.example/dns-query",
            "vless_url": "vless://aaa@1.1.1.1:443#DE",
            "providers_visibility": {"openai": False},
        })

        backup_no_ext = Path(self.temp.name) / "full_backup"
        exp = api.export_backup(str(backup_no_ext), password="pw")
        self.assertTrue(exp["ok"])
        self.assertTrue(exp["path"].endswith(".agb"))
        self.assertEqual(exp["counts"], {"google": 1, "openai": 1, "claude": 1})

        # First import without password asks for password
        prompt_res = api.import_backup(exp["path"])
        self.assertFalse(prompt_res["ok"])
        self.assertTrue(prompt_res["requires_password"])

        # Reset local state before importing
        self.claude.load_accounts.return_value = []
        self.backend.ANTIGRAVITY_CONFIG_FILE.unlink(missing_ok=True)
        self.backend.HUB_CONFIG_FILE.unlink(missing_ok=True)

        imp = api.import_backup(exp["path"], password="pw")
        self.assertTrue(imp["ok"], imp.get("message"))
        self.assertEqual(imp["counts"], {"google": 1, "openai": 1, "claude": 1})
        self.claude.configure_opencode_provider.assert_called_once()
        self.openrouter.configure_models.assert_called_once_with([{"id": "free/m1", "name": "free/m1"}])
        self.tokenlavka.configure_models.assert_called_once_with(["gpt-6-luna"], "sk-tl-1")
        self.deepseek.save_api_key.assert_called_once_with("sk-ds-1")
        self.deepseek.save_config.assert_called_once()
        oc_after = json.loads(self.backend.OPENCODE_CONFIG_FILE.read_text(encoding="utf-8"))
        self.assertIn("openai", oc_after.get("disabled_providers", []))


if __name__ == "__main__":
    unittest.main()
