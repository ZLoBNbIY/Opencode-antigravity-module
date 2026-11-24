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
        manager.terminate_opencode_desktop = Mock(return_value={
            "ok": True, "closed": 0, "failed": 0, "message": ""})
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
            api_origin=Mock(return_value="https://api.deepseek.com"),
            fetch_models=Mock(return_value=[{"id": "deepseek-chat", "name": "DeepSeek Chat", "context": 65536, "output": 8192}]),
            configure_opencode_models=Mock(return_value=["deepseek-chat"]),
            sync_opencode_credential=Mock(),
            disconnect_opencode=Mock(return_value=True),
            clear_api_key=Mock(return_value=True),
            selected_models=Mock(return_value=[]),
            FALLBACK_MODELS=[{"id": "deepseek-chat", "name": "DeepSeek Chat", "context": 65536, "output": 8192}],
            provider_state=Mock(return_value={
                "hasKey": False, "connected": False, "keyLabel": None,
                "baseUrl": "https://api.deepseek.com", "balance": {"status": "no_key"},
                "models": [], "selectedModels": [],
            }),
            DEFAULT_BASE_URL="https://api.deepseek.com",
        )
        modules = {
            "antigravity_manager": manager,
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
        startup_migration = patch.object(self.backend.hub_paths, "migrate_legacy_locations")
        startup_migration.start()
        self.addCleanup(startup_migration.stop)

    @patch("cloudcode_route_patch.get_expected_plugin_version", return_value="3.0.0")
    def test_google_proactive_refresh_accepts_node_from_path(self, expected):
        cli = Path(self.temp.name) / "cli.js"
        cli.touch()
        self.manager.get_cli_js = Mock(return_value=str(cli))
        self.manager.get_node_executable = Mock(return_value="node")
        self.manager.run_google_route_cmd = Mock()
        api = self.backend.HubApi()
        self.assertIs(api._run_google_refresh_cli(["refresh-due", "--list"], 45),
                      self.manager.run_google_route_cmd.return_value)
        self.manager.run_google_route_cmd.assert_called_once_with(
            ["node", str(cli), "refresh-due", "--list"], timeout=45)

    @patch("cloudcode_route_patch.get_expected_plugin_version", return_value="3.0.0")
    def test_google_proactive_refresh_respects_opt_out_and_supported_profiles(self, expected):
        api = self.backend.HubApi()
        api.load_config = Mock(return_value={})
        self.manager.get_cli_js = Mock()
        self.manager.get_node_executable = Mock(return_value="node")
        self.manager.run_google_route_cmd = Mock()
        cli = Path(self.temp.name) / "cached-cli.js"
        cli.touch()
        finder = self.enterContext(patch.object(
            self.backend.google_proactive_refresh, "find_cli_3113", return_value=cli))
        with patch.dict("os.environ", {"AI_HUB_GOOGLE_PROACTIVE_REFRESH": ""}):
            self.assertTrue(api._google_refresh_enabled())
            api.load_config.return_value = {"google_proactive_refresh": False}
            api._google_refresh.check()
            self.manager.run_google_route_cmd.assert_not_called()
            api.load_config.return_value = {"plugin_pin_version": "3.1.13"}
            self.assertEqual(api._google_refresh_profile(), "3.1.13")
            api.load_config.return_value = {}
            source = b'{"plugins":["@cortexkit/opencode-antigravity-auth@3.1.13"]}'
            self.backend.OPENCODE_CONFIG_FILE.write_bytes(source)
            api._google_refresh.check()
            self.assertEqual(self.backend.OPENCODE_CONFIG_FILE.read_bytes(), source)
            args = self.manager.run_google_route_cmd.call_args.args[0]
            self.assertEqual(args, ["node", str(self.backend.CURRENT_DIR.parent / "plugin" / "dist" /
                                                "google-cli-3113.mjs"), str(cli), "--list"])
            self.manager.run_google_route_cmd.reset_mock()
            self.backend.OPENCODE_CONFIG_FILE.write_text(
                '{"plugins":[{"package":"@cortexkit/opencode-antigravity-auth@3.1.13","options":{}}]}',
                encoding="utf-8")
            self.assertEqual(api._google_refresh_profile(), "3.1.13")
            api.load_config.return_value = {"plugin_pin_version": "3.0.0"}
            api._google_refresh.check()  # Conflicting pins fail closed.
            api.load_config.return_value = {}
            self.backend.OPENCODE_CONFIG_FILE.unlink()
            expected.return_value = "3.1.13"
            finder.return_value = None
            api._google_refresh.check()  # Missing 3.1 profile never uses 3.0 CLI.
            expected.return_value = "3.1.14"
            api._google_refresh.check()
        with patch.dict("os.environ", {"AI_HUB_GOOGLE_PROACTIVE_REFRESH": "0"}):
            expected.return_value = "3.0.0"
            api._google_refresh.check()
        self.manager.run_google_route_cmd.assert_not_called()
        self.manager.get_cli_js.assert_not_called()

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
        self.assertEqual([c.args[0] for c in self.manager.run_google_route_cmd.call_args_list],
                         [["node", "cli.js", "login"],
                          ["node", "cli.js", "quota", "--refresh", "--json"]])
        self.assertEqual([c.args[0] for c in self.manager.run_silent_cmd.call_args_list],
                         [["node", "cli.js", "migrate", "--offline", "--yes"],
                           ["cli.exe", "service", "restart"]])
        self.assertEqual(self.manager.run_silent_cmd.call_args.kwargs["env"],
                         self.backend.opencode_launch_environment())

    def test_google_login_reports_when_state_refresh_or_service_restart_fails(self):
        self.manager.get_node_executable = Mock(return_value="node")
        self.manager.get_cli_js = Mock(return_value="cli.js")
        self.manager.get_opencode_cli = Mock(return_value=None)
        self.manager.repair_legacy_google_account_file = Mock(return_value=None)
        self.manager.run_silent_cmd = Mock(return_value=SimpleNamespace(returncode=0, stdout="", stderr=""))
        self.manager.run_google_route_cmd = Mock(side_effect=[
            SimpleNamespace(returncode=0, stdout="", stderr=""),
            SimpleNamespace(returncode=1, stdout="", stderr="quota failed"),
        ])
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
        self.manager.run_silent_cmd = Mock()
        self.manager.run_google_route_cmd = Mock(
            return_value=SimpleNamespace(returncode=1, stdout="", stderr="login failed"))
        with patch.object(self.backend.os.path, "exists", return_value=True):
            result = self.backend.HubApi().add_google_account()
        self.assertEqual(result, {'status':'error', 'message':'Не удалось завершить вход в Google.'})
        self.manager.run_silent_cmd.assert_not_called()

    def test_google_connection_runs_in_a_daemon_thread_after_login(self):
        self.manager.get_node_executable = Mock(return_value="node")
        self.manager.get_cli_js = Mock(return_value="cli.js")
        self.manager.repair_legacy_google_account_file = Mock(return_value=None)
        self.manager.run_silent_cmd = Mock(return_value=SimpleNamespace(returncode=0, stdout="", stderr=""))
        self.manager.run_google_route_cmd = Mock(return_value=SimpleNamespace(returncode=0, stdout="", stderr=""))
        threads = []

        class RecordingThread:
            def __init__(self, target=None, daemon=None, name=None):
                self.target, self.daemon, self.name = target, daemon, name
                threads.append(self)

            def start(self):
                pass

        api = self.backend.HubApi()
        with patch.object(self.backend.threading, "Thread", RecordingThread), \
             patch.object(self.backend.os.path, "exists", return_value=True):
            result = api.add_google_account()
        self.assertEqual(result["status"], "ok")
        connect_threads = [t for t in threads if t.name == "hub-google-connect"]
        self.assertEqual(len(connect_threads), 1)
        self.assertTrue(connect_threads[0].daemon)
        self.assertEqual(connect_threads[0].target.__func__,
                         api.ensure_google_connection.__func__)
        self.assertIs(connect_threads[0].target.__self__, api)

    def test_google_connection_respects_lock_and_closing_state(self):
        api = self.backend.HubApi()
        api._google_connect_lock.acquire()
        try:
            self.assertEqual(api.ensure_google_connection(),
                             self.backend.google_connection.IN_PROGRESS)
        finally:
            api._google_connect_lock.release()
        api._closing.set()
        self.manager.get_opencode_cli = Mock(side_effect=AssertionError("worker must not run"))
        self.assertEqual(api.ensure_google_connection(), self.backend.google_connection.SKIP)
        self.manager.get_opencode_cli.assert_not_called()
        with patch.object(self.backend.threading, "Thread") as thread:
            api._schedule_google_connection()
            thread.assert_not_called()

    def test_openai_failure_and_exception_reach_frontend_and_unlock_retry(self):
        self.openai.login_openai_browser = Mock(side_effect=[(False, 'token exchange failed', None),
                                                           RuntimeError('network unavailable'),
                                                           (True, 'saved', {'id':'test'})])
        api = self.backend.HubApi()
        self.assertEqual(api.add_openai_account(), {'status':'error', 'message':'token exchange failed'})
        self.assertEqual(api.add_openai_account(), {'status':'error', 'message':'network unavailable'})
        self.assertEqual(api.add_openai_account(), {'status':'ok', 'message':'saved'})

    def test_openai_quota_refresh_uses_rotation_path_and_exposes_notice(self):
        self.openai.refresh_all_openai_accounts = Mock(
            return_value=([{'id': 'openai-1', 'is_active': True}], 'switched to backup')
        )

        class ImmediateThread:
            def __init__(self, target=None, **_kwargs):
                self.target = target

            def start(self):
                self.target()

        api = self.backend.HubApi()
        with patch.object(self.backend.threading, 'Thread', ImmediateThread):
            result = api.refresh_openai_quotas()

        self.assertTrue(result['ok'])
        self.assertFalse(api._quota_refreshing)
        self.openai.refresh_all_openai_accounts.assert_called_once_with()
        with patch.object(api, 'is_opencode_running', return_value=False):
            state = api.get_state()
        self.assertEqual(state['openaiNotice'], 'switched to backup')

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
        self.manager.run_silent_cmd.assert_called_once_with(
            ['cli.exe', 'service', 'restart'], timeout=45, env=self.backend.opencode_launch_environment())

    def test_stop_opencode_also_closes_desktop_opened_outside_hub(self):
        api = self.backend.HubApi()
        terminate = Mock(return_value={"ok": True, "closed": 1, "failed": 0, "message": "ok"})
        with patch.object(self.backend.antigravity_manager,
                          "terminate_opencode_desktop", terminate):
            self.assertTrue(api.stop_opencode())
        terminate.assert_called_once_with()

    def test_stop_opencode_reports_failed_external_close(self):
        api = self.backend.HubApi()
        terminate = Mock(return_value={"ok": False, "closed": 0, "failed": 1,
                                       "message": "access denied"})
        with patch.object(self.backend.antigravity_manager,
                          "terminate_opencode_desktop", terminate):
            self.assertFalse(api.stop_opencode())

    def test_desktop_launch_does_not_inherit_hub_proxy(self):
        self.manager.get_opencode_exe = Mock(return_value="OpenCode.exe")
        api = self.backend.HubApi()
        with patch.dict("os.environ", {"HTTPS_PROXY": "http://127.0.0.1:10880",
                                       "NO_PROXY": "localhost"}, clear=True), \
             patch.object(self.backend.os.path, "exists", return_value=True), \
             patch.object(self.backend.subprocess, "Popen") as launch:
            self.assertTrue(api.start_opencode())
        self.assertEqual(launch.call_args.kwargs["env"], {"NO_PROXY": "localhost"})

    def test_restart_service_failure_is_reported_and_retry_is_possible(self):
        self.manager.get_opencode_cli = Mock(return_value='cli.exe')
        self.manager.get_opencode_exe = Mock(return_value='OpenCode.exe')
        self.manager.run_silent_cmd = Mock(return_value=SimpleNamespace(returncode=1, stdout='', stderr='service failed'))
        api = self.backend.HubApi()
        with patch.object(self.backend.os.path, 'exists', return_value=True), \
             patch.object(api, 'stop_opencode', return_value=True), \
             patch.object(api, 'start_opencode', return_value=True) as start:
            with self.assertRaisesRegex(RuntimeError, 'CLI не смог'):
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
        added_first = api.add_vless_config(first)
        added_second = api.add_vless_config(second)
        self.assertTrue(added_first["ok"])
        self.assertTrue(added_second["ok"])
        state = api.get_vless_pool()
        self.assertEqual(len(state["pool"]), 2)
        self.assertEqual(state["active"], added_first["id"])
        self.assertNotIn("vless://", json.dumps(state))
        # First config becomes active automatically when it is the only one.
        activated = api.activate_vless_config(added_second["id"])
        self.assertTrue(activated["ok"])
        self.assertEqual(api.load_config()["vless_url"], second)
        self.assertEqual(api.get_vless_pool()["activeEntry"]["id"], added_second["id"])
        # Tunnel is stopped in this fixture, so activation probes the new config.
        self.vless.start_tunnel.assert_called()
        removed = api.delete_vless_config(added_second["id"])
        self.assertTrue(removed["ok"])
        self.assertEqual(api.load_config()["vless_url"], first)
        self.assertEqual(len(api.get_vless_pool()["pool"]), 1)

    def test_vless_pool_normalizes_legacy_strings_and_caches_probe(self):
        api = self.backend.HubApi()
        url = "vless://aaa@1.1.1.1:443?security=reality#DE"
        api.save_config({"vless_pool": [url, url, "not-a-vless-url"]})
        pool = api.get_vless_pool()["pool"]
        self.assertEqual(len(pool), 1)
        self.assertNotIn("url", pool[0])
        self.assertEqual(pool[0]["status"], "untested")
        checked = api.test_vless_config(pool[0]["id"])
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
            patch_antigravity_identity=Mock(return_value={
                "ok": True, "changed": ["server.js"], "already": [], "missing": [],
                "message": "Патч Antigravity применён."}),
            patch_auth_plugin_transport=Mock(return_value=True),
            get_prompt_sanitizer_status=Mock(return_value={"state": "patched"}),
            patch_gemini4_models=Mock(return_value={
                "ok": True, "changed": [], "already": [], "missing": [], "message": "ok"}),
            verify_plugin_health=Mock(return_value={"ok": True, "state": "ok", "reasons": []}),
            get_verified_version=Mock(return_value="3.0.0"),
            get_verified_versions=Mock(return_value=["3.0.0"]),
            get_installed_fingerprint=Mock(return_value={
                "found": 1, "copies": [{"path": "server.js", "version": "3.0.0", "sha256": "abc"}]}),
            save_patch_state=Mock(),
        )
        with patch.dict("sys.modules", {"cloudcode_route_patch": patcher}):
            result = self.backend.HubApi().fix_opencode_plugin()
        self.assertTrue(result["ok"])
        self.assertTrue(result["route_patched"])
        self.assertEqual(result["synced"], ["server.js"])
        self.assertEqual(result["identity"]["ok"], True)
        self.assertIn("Маршрут Hub и синтаксис бандла проверены", result["message"])
        patcher.sync_local_plugin_bundles.assert_called_once()
        patcher.patch_prompt_sanitizer.assert_called_once()
        patcher.patch_antigravity_identity.assert_called_once()
        patcher.patch_auth_plugin_transport.assert_called_once()
        patcher.patch_gemini4_models.assert_called_once()

    def test_get_opencode_plugin_status_delegates_to_patcher(self):
        patcher = SimpleNamespace(
            get_prompt_sanitizer_status=Mock(return_value={
                "state": "patched", "found": 2, "patched": 2, "pending": 0, "message": "ok"}),
            check_patch_state=Mock(return_value={"state": "ok", "copies": [
                {"version": "3.0.0"}]}),
            load_patch_state=Mock(return_value={
                "verified_version": "3.0.0", "degraded": False, "degraded_reason": ""}),
            verify_plugin_health=Mock(return_value={"ok": True, "state": "ok", "reasons": []}),
        )
        with patch.dict("sys.modules", {"cloudcode_route_patch": patcher}):
            status = self.backend.HubApi().get_opencode_plugin_status()
        self.assertEqual(status["state"], "patched")
        patcher.get_prompt_sanitizer_status.assert_called_once_with(full=True)

    def test_plugin_status_ignores_stale_reason_when_live_bundles_healthy(self):
        patcher = SimpleNamespace(
            get_prompt_sanitizer_status=Mock(return_value={
                "state": "patched", "found": 2, "patched": 2, "pending": 0, "message": "ok"}),
            check_patch_state=Mock(return_value={"state": "version_changed", "copies": [
                {"version": "3.1.13"}]}),
            load_patch_state=Mock(return_value={
                "verified_version": "3.1.13", "degraded": True,
                "degraded_reason": "stale test fixture reason"}),
            verify_plugin_health=Mock(return_value={"ok": True, "state": "ok", "reasons": []}),
        )
        with patch.dict("sys.modules", {"cloudcode_route_patch": patcher}):
            status = self.backend.HubApi().get_opencode_plugin_status()
        self.assertEqual(status["state"], "patched")
        self.assertFalse(status["degraded"])
        self.assertEqual(status["reason"], "")
        self.assertEqual(status["state_detail"], "version_changed")

    def test_apply_antigravity_patch_delegates_to_patcher(self):
        patcher = SimpleNamespace(
            patch_antigravity_identity=Mock(return_value={
                "ok": True, "changed": ["server.js"], "already": [], "missing": [],
                "message": "Патч Antigravity применён."}),
            get_identity_fix_status=Mock(return_value={
                "state": "patched", "found": 2, "patched": 2, "pending": 0, "message": "ok"}),
        )
        with patch.dict("sys.modules", {"cloudcode_route_patch": patcher}):
            result = self.backend.HubApi().apply_antigravity_patch()
        self.assertTrue(result["ok"])
        self.assertEqual(result["status"]["state"], "patched")
        patcher.patch_antigravity_identity.assert_called_once()
        patcher.get_identity_fix_status.assert_called_once()

    def test_get_antigravity_patch_status_delegates_to_patcher(self):
        patcher = SimpleNamespace(get_identity_fix_status=Mock(return_value={
            "state": "patched", "found": 2, "patched": 2, "pending": 0, "message": "ok"}))
        with patch.dict("sys.modules", {"cloudcode_route_patch": patcher}):
            status = self.backend.HubApi().get_antigravity_patch_status()
        self.assertEqual(status["state"], "patched")
        patcher.get_identity_fix_status.assert_called_once()

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
            self.assertTrue(window.events.loaded.wait(10), "Bridge initialization did not finish")
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

    def test_save_general_settings_persists_autostart(self):
        api = self.backend.HubApi()
        with patch.object(self.backend, "_apply_autostart") as apply_autostart:
            self.assertTrue(api.save_general_settings({"autostart_on_login": True}))
        apply_autostart.assert_called_once_with(True)
        self.assertTrue(api.load_config()["autostart_on_login"])

    def test_save_visibility_preserves_invalid_config_and_hub_settings(self):
        api = self.backend.HubApi()
        self.assertTrue(api.save_config({"close_to_tray": True}))
        oc = self.backend.OPENCODE_CONFIG_FILE
        original = b'{"model":"example/model",'
        oc.write_bytes(original)
        with self.assertRaisesRegex(ValueError, "OpenCode"):
            api.save_general_settings({"close_to_tray": False, "providers_visibility": {"openai": False}})
        self.assertEqual(oc.read_bytes(), original)
        self.assertTrue(api.load_config()["close_to_tray"])

    def test_autostart_error_rolls_back_all_settings_files(self):
        api = self.backend.HubApi()
        self.assertTrue(api.save_config({"close_to_tray": True}))
        paths = (self.backend.HUB_CONFIG_FILE, self.backend.ANTIGRAVITY_CONFIG_FILE,
                 self.backend.OPENCODE_CONFIG_FILE)
        paths[-1].write_bytes(b'\xef\xbb\xbf{\r\n  "model":"example/model"\r\n}\r\n')
        previous = [path.read_bytes() for path in paths]
        with patch.object(self.backend, "_apply_autostart", side_effect=OSError("registry")):
            with self.assertRaisesRegex(OSError, "registry"):
                api.save_general_settings({"close_to_tray": False, "autostart_on_login": True,
                                           "providers_visibility": {"openai": False}})
        self.assertEqual([path.read_bytes() for path in paths], previous)

    def test_corrupt_hub_config_is_not_replaced(self):
        api = self.backend.HubApi()
        central = self.backend.HUB_CONFIG_FILE
        central.write_bytes(b"{")
        self.assertFalse(api.save_config({"close_to_tray": True}))
        self.assertEqual(central.read_bytes(), b"{")
        self.assertFalse(self.backend.ANTIGRAVITY_CONFIG_FILE.exists())

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
        res = api._export_backup(str(backup_file), password="strong-password")
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
        imp = self._import_fixture(api, malicious)
        self.assertFalse(imp["ok"])
        saved = api.load_config()
        self.assertEqual(saved["vless_core_path"], "C:/safe/xray.exe")
        self.assertNotIn("doh_url", saved)
        self.assertNotIn("proxy", saved)
        malicious.write_text('{"config":{"vless_core_path":"C:/evil/payload.exe"}}', encoding="utf-8")
        self.assertTrue(self._import_fixture(api, malicious)["ok"])
        self.assertEqual(api.load_config()["vless_core_path"], "C:/safe/xray.exe")

    def test_full_backup_export_import_roundtrip_all_providers_and_missing_cli(self):
        self.manager.export_google_accounts.return_value = [{"email": "g@example.com", "refreshToken": "g-ref"}]
        self.manager.import_google_accounts = Mock(return_value=1)
        self.openai.load_openai_accounts.return_value = [{"id": "oa-1", "email": "o@example.com", "refresh": "o-ref"}]
        self.openai.import_openai_accounts = Mock(return_value=1)
        self.claude.load_accounts.return_value = [{"email": "c@example.com", "session_key": "sk-ant-1"}]
        self.claude.import_backup_accounts = Mock(return_value=1)
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

        target = Path(self.temp.name) / "full_backup.agb"
        exp = api._export_backup(str(target), password="pw")
        self.assertTrue(exp["ok"])
        self.assertTrue(exp["path"].endswith(".agb"))
        self.assertEqual(exp["counts"], {"google": 1, "openai": 1, "claude": 1})

        # First import without password asks for password
        prompt_res = self._import_fixture(api, target)
        self.assertFalse(prompt_res["ok"])
        self.assertTrue(prompt_res["requires_password"])

        # Reset local state before importing
        self.claude.load_accounts.return_value = []
        self.backend.ANTIGRAVITY_CONFIG_FILE.unlink(missing_ok=True)
        self.backend.HUB_CONFIG_FILE.unlink(missing_ok=True)

        imp = api.import_backup(prompt_res["import_token"], password="pw")
        self.assertFalse(imp["ok"], imp.get("message"))
        self.assertTrue(imp["partial"], imp.get("message"))
        self.assertEqual(imp["counts"], {"google": 1, "openai": 1, "claude": 1})
        self.claude.configure_opencode_provider.assert_called_once()
        self.openrouter.configure_models.assert_called_once_with([{"id": "free/m1", "name": "free/m1"}])
        self.tokenlavka.configure_models.assert_called_once_with(["gpt-6-luna"], "sk-tl-1")
        self.deepseek.save_api_key.assert_called_once_with("sk-ds-1")
        self.deepseek.save_config.assert_called_once()
        oc_after = json.loads(self.backend.OPENCODE_CONFIG_FILE.read_text(encoding="utf-8"))
        self.assertIn("openai", oc_after.get("disabled_providers", []))
        self.assertFalse(api.import_backup(prompt_res["import_token"], password="pw")["ok"])

    def _import_fixture(self, api, path):
        api._window_holder = SimpleNamespace(create_file_dialog=Mock(return_value=[str(path)]))
        with patch.dict("sys.modules", {"webview": SimpleNamespace(FileDialog=SimpleNamespace(OPEN=1))}):
            return api.import_backup()

    def test_backup_bridge_cannot_use_a_path_from_javascript(self):
        api = self.backend.HubApi(SimpleNamespace(create_file_dialog=Mock()))
        file = Path(self.temp.name) / "backup.json"
        file.write_text('{"config":{"close_to_tray":true}}', encoding="utf-8")
        response = self.backend._WebviewBridge(api).import_backup(str(file))
        self.assertFalse(response["ok"])
        api._window_holder.create_file_dialog.assert_not_called()
        self.assertFalse(self.backend.HUB_CONFIG_FILE.exists())

    def test_update_accepts_only_the_unconsumed_checked_commit(self):
        api = self.backend.HubApi()
        offered = "a" * 40
        check = Mock(return_value={"has_update": True, "remote_sha": offered, "remote_commit": offered})
        apply = Mock(return_value=(True, "updated"))
        with patch.object(self.backend.auto_updater, "check_for_updates", check, create=True), \
             patch.object(self.backend.auto_updater, "apply_update_git", apply, create=True):
            self.assertFalse(api.apply_update(offered)["ok"])
            self.assertEqual(api.check_updates()["remote_commit"], offered)
            self.assertFalse(api.apply_update("b" * 40)["ok"])
            self.assertTrue(api.apply_update(offered)["ok"])
            self.assertFalse(api.apply_update(offered)["ok"])
            apply.assert_called_once_with(self.backend.CURRENT_DIR.parent, expected_commit=offered)

    def test_export_bridge_requires_password_and_native_save_dialog(self):
        api = self.backend.HubApi(SimpleNamespace(create_file_dialog=Mock(return_value=None)))
        bridge = self.backend._WebviewBridge(api)
        self.assertFalse(hasattr(bridge, "_export_backup"))
        self.assertFalse(hasattr(bridge, "load_config"))
        self.assertFalse(hasattr(bridge, "save_config"))
        self.assertFalse(bridge.export_backup()["ok"])
        api._window_holder.create_file_dialog.assert_not_called()
        with patch.dict("sys.modules", {"webview": SimpleNamespace(FileDialog=SimpleNamespace(SAVE=1))}):
            self.assertTrue(bridge.export_backup("password")["cancelled"])
        api._window_holder.create_file_dialog.assert_called_once()

    def test_invalid_later_section_and_oversized_backup_do_not_mutate(self):
        import crypto_backup
        api = self.backend.HubApi()
        self.manager.import_google_accounts = Mock()
        target = Path(self.temp.name) / "invalid.json"
        target.write_text('{"accounts":[{"refreshToken":"test"}],"config":{"proxy_pool":[{}]}}')
        self.assertFalse(self._import_fixture(api, target)["ok"])
        self.manager.import_google_accounts.assert_not_called()
        target.write_bytes(b" " * 65)
        with patch.object(crypto_backup, "MAX_BACKUP_BYTES", 64):
            res = self._import_fixture(api, target)
        self.assertFalse(res["ok"])
        self.assertIn("16", res["message"])

    def test_proxy_public_state_and_operations_use_ids(self):
        api = self.backend.HubApi()
        url = "https://example-user:example-secret@proxy.example:8443"
        added = api.add_proxy_pool(url)
        self.assertTrue(added["ok"])
        proxy_id = added["proxy"]
        self.assertEqual(added["proxy_labels"][proxy_id], "proxy.example:8443")
        self.assertNotIn("example-secret", json.dumps(api.get_state()))
        self.assertTrue(api.test_proxy(proxy_id)["ok"])
        self.router._connect_upstream.assert_called_once_with(url, "cloudcode-pa.googleapis.com", 443, timeout=6)
        self.assertTrue(api.delete_proxy_pool(proxy_id)["ok"])

    def test_uninstall_preserves_custom_root_and_edits_only_owned_fields(self):
        api = self.backend.HubApi(SimpleNamespace(create_confirmation_dialog=Mock(return_value=True)))
        custom = Path(self.temp.name) / "custom"
        custom.mkdir()
        sentinel = custom / "sentinel.txt"
        sentinel.write_text("keep")
        with patch.dict("os.environ", {"ANTIGRAVITY_HUB_DATA_DIR": str(custom)}):
            self.assertFalse(api.uninstall_hub_completely()["ok"])
            self.assertTrue(api.uninstall_hub_completely("DELETE")["ok"])
        self.assertEqual(sentinel.read_text(), "keep")
        original = '''{
          // Keep this
          "plugin": ["@cortexkit/opencode-antigravity-auth@latest",
                     "@cortexkit/opencode-antigravity-auth-extra"],
          "plugins": [{"package":"@cortexkit/opencode-antigravity-auth@3.0.0"}, {"package":"./keep"}],
          "provider": {"google":{"options":{"apiKey":"antigravity","custom":true},"models":{"g":{}}}},
          "agent":{"title":{"model":"opencode/big-pickle"}}
        }'''
        updated = self.backend._remove_hub_opencode_settings(original)
        self.assertIn("// Keep this", updated)
        parsed = self.backend.jsonc_config.parse_config(updated)
        self.assertEqual(parsed["plugin"], ["@cortexkit/opencode-antigravity-auth-extra"])
        self.assertEqual(parsed["plugins"], [{"package":"./keep"}])
        self.assertEqual(parsed["provider"]["google"], {"options":{"custom": True}, "models":{"g": {}}})
        self.assertEqual(parsed["agent"]["title"]["model"], "opencode/big-pickle")

    def test_uninstall_allowlist_and_failures_in_disposable_root(self):
        api = self.backend.HubApi(SimpleNamespace(create_confirmation_dialog=Mock(return_value=True)))
        temp = Path(self.temp.name)
        root = temp / "AppData" / "Roaming" / "AntigravityHub"
        config_dir = temp / ".config" / "opencode"
        accounts = root / "accounts"
        accounts.mkdir(parents=True)
        config_dir.mkdir(parents=True)
        owned = accounts / "openai-accounts.json"
        unrelated = accounts / "unrelated.json"
        wrong_type = accounts / "claude-accounts.json"
        owned.write_text("{}")
        unrelated.write_text("keep")
        wrong_type.mkdir()
        pointer = config_dir / "antigravity-accounts.json.store.pointer.json"
        pointer.write_text(json.dumps({"relocatedTo": {"legacyPath": str(unrelated)}}))
        with patch.object(Path, "home", return_value=temp), \
             patch.object(self.backend.sys, "platform", "win32"), \
             patch.dict("os.environ", {"APPDATA": str(root.parent),
                        "ANTIGRAVITY_HUB_DATA_DIR": "", "OPENCODE_CONFIG_DIR": ""}), \
             patch.object(self.backend.hub_paths, "HUB_ROOT", root), \
             patch.object(self.backend, "CONFIG_DIR", config_dir):
            result = api.uninstall_hub_completely("DELETE")
        self.assertFalse(result["ok"])
        self.assertIn("claude-accounts.json", result["message"])
        self.assertFalse(owned.exists())
        self.assertTrue(wrong_type.is_dir())
        self.assertTrue(pointer.is_file())
        self.assertEqual(unrelated.read_text(), "keep")

    def test_set_strategy_validates_and_stop_vless_syncs_routes(self):
        api = self.backend.HubApi()
        with self.assertRaises(ValueError):
            api.set_strategy("invalid-strategy")
        self.assertTrue(api.set_strategy("sticky"))
        self.assertEqual(api.load_config()["account_selection_strategy"], "sticky")

        api.save_config({"vless_enabled": True})
        res = api.stop_vless()
        self.assertTrue(res["ok"])
        self.assertFalse(api.load_config()["vless_enabled"])
        self.router.start.assert_called()

    def test_jsonc_opencode_config_is_supported_across_backend(self):
        jsonc_file = Path(self.temp.name) / "opencode.jsonc"
        jsonc_file.write_text(
            '{\n  // user comment\n  "disabled_providers": ["openai"],\n  "provider": {"openrouter-free": {"models": {"free/m1": {"name": "M1"}}}}\n}\n',
            encoding="utf-8",
        )
        api = self.backend.HubApi()
        with patch.object(api, "is_opencode_running", return_value=False):
            state = api.get_state()
        self.assertFalse(state["config"]["providers_visibility"]["openai"])
        self.assertEqual(state["providers"]["openrouter"]["selectedModels"], ["free/m1"])
        self.assertTrue(api.save_general_settings({"providers_visibility": {"openai": True}}))
        self.assertIn("// user comment", jsonc_file.read_text(encoding="utf-8"))

    def test_restart_hub_schedules_restart_and_stops_services(self):
        api = self.backend.HubApi()
        api._tray_holder = SimpleNamespace(remove=Mock())
        api._window_holder = SimpleNamespace(destroy=Mock())
        fake_srv = SimpleNamespace(shutdown=Mock(), server_close=Mock())
        self.router._server = fake_srv
        spawned = []

        class FakeThread:
            def __init__(self, target=None, daemon=None, name=None):
                self.target = target

            def start(self):
                spawned.append(self.target)

        with patch("hub_restart.schedule_restart") as sched, \
             patch.object(self.backend.threading, "Thread", FakeThread), \
             patch.object(self.backend.time, "sleep"):
            res = api.restart_hub()
            self.assertTrue(res["ok"])
            sched.assert_called_once()
            self.assertEqual(len(spawned), 1)
            spawned[0]()
            self.assertTrue(api._closing.is_set())
            api._window_holder.destroy.assert_called_once()
            api._shutdown_runtime()
            self.vless.stop_tunnel.assert_called_once()
            fake_srv.shutdown.assert_called_once()
            fake_srv.server_close.assert_called_once()
            api._tray_holder.remove.assert_called_once()


    def test_configure_deepseek_api_registers_provider_in_opencode(self):
        self.deepseek.load_api_key.return_value = "sk-test-key-1234567890"
        self.deepseek.fetch_models.return_value = [
            {"id": "deepseek-chat", "name": "DeepSeek Chat", "context": 65536, "output": 8192},
            {"id": "deepseek-reasoner", "name": "DeepSeek Reasoner", "context": 65536, "output": 8192},
        ]
        self.deepseek.fetch_balance = Mock(return_value={"status": "ok", "total_balance": 5.0})
        api = self.backend.HubApi()
        res = api.configure_deepseek_api("sk-test-key-1234567890", "https://api.deepseek.com")
        self.assertTrue(res["ok"])
        self.assertIn("DeepSeek добавлен в OpenCode", res["message"])
        self.deepseek.configure_opencode_models.assert_called_once()
        self.deepseek.sync_opencode_credential.assert_called_once()
        self.assertEqual(res["selectedModels"], ["deepseek-chat"])

        api.disconnect_deepseek_api()
        self.deepseek.disconnect_opencode.assert_called_once()


if __name__ == "__main__":
    unittest.main()
