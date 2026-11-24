"""Offline tests for the idempotent Antigravity pool credential worker.

All CLI/DB access is mocked: these tests never contact a running OpenCode
server and never read or write the real credential store.
"""

import json
import sys
import tempfile
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "gui-manager"))
import google_connection as gc  # noqa: E402
import antigravity_manager  # noqa: E402
import proxy_config  # noqa: E402


def response(payload=None, returncode=0, stdout=None):
    if stdout is None:
        stdout = json.dumps(payload) if payload is not None else ""
    return SimpleNamespace(returncode=returncode, stdout=stdout, stderr="")


def envelope(*integrations):
    return {"location": "cli", "data": list(integrations)}


def integration(with_pool=False, foreign=False, methods=True):
    # methods=True -> pool method advertised; a list is used verbatim.
    connections = [{"type": "env", "name": "GOOGLE_GENERATIVE_AI_API_KEY"}]
    if foreign:
        connections.append({"type": "credential", "id": "cred-other",
                            "label": "Somebody else", "method": "oauth"})
    if with_pool:
        connections.append({"type": "credential", "id": "cred-pool",
                            "label": gc.POOL_LABEL, "method": "oauth"})
    row = {"id": "google", "connections": connections}
    if methods is True:
        row["methods"] = [{"id": gc.POOL_METHOD_ID}, {"id": "antigravity-vault"}]
    elif methods:
        row["methods"] = methods
    return row


def options(run, **overrides):
    params = dict(cli="opencode-cli.exe", version="3.1.13", resolve=False,
                  is_file=lambda _path: True, run_cli=run,
                  active_check=lambda _integration: [])
    params.update(overrides)
    return params


START_DATA = json.dumps({"methodID": gc.POOL_METHOD_ID, "label": gc.POOL_LABEL},
                        ensure_ascii=False, separators=(",", ":"))


class GoogleConnectionTests(unittest.TestCase):
    def test_already_connected_keeps_env_and_never_posts(self):
        run = Mock(return_value=response(envelope(integration(with_pool=True))))
        status = gc.ensure_google_connection(**options(run))
        self.assertEqual(status, gc.ALREADY_CONNECTED)
        run.assert_called_once()
        self.assertEqual(run.call_args.args[0],
                         ["opencode-cli.exe", "api", "GET", gc.INTEGRATION_PATH])
        self.assertEqual(run.call_args.kwargs["timeout"], gc.GET_TIMEOUT)

    def test_public_helpers_use_only_the_data_envelope_and_the_hub_label(self):
        connected = envelope(integration(with_pool=True))
        self.assertEqual(gc._google_connections(connected)[-1]["label"], gc.POOL_LABEL)
        self.assertTrue(gc.has_pool_connection(connected))
        self.assertFalse(gc.has_pool_connection(envelope(integration())))
        self.assertFalse(gc.has_pool_connection({"google": integration(with_pool=True)}))
        with_method_id = envelope({"id": "google", "connections": [
            {"type": "credential", "label": "Other", "method": gc.POOL_METHOD_ID}]})
        self.assertFalse(gc.has_pool_connection(with_method_id))

    def test_only_data_envelope_is_parsed(self):
        # Legacy shapes must not be mistaken for a successful listing.
        legacy = {"google": integration(with_pool=True)}
        run = Mock(return_value=response(legacy))
        self.assertEqual(gc.ensure_google_connection(**options(run, retry_delay=0)), gc.API_ERROR)
        self.assertEqual(run.call_count, 3)

    def test_method_id_on_a_connection_does_not_count_as_ours(self):
        fake = {"id": "google", "connections": [
            {"type": "credential", "id": "cred-other", "label": "Other",
             "method": gc.POOL_METHOD_ID}]}
        run = Mock(return_value=response(envelope(fake)))
        self.assertEqual(gc.ensure_google_connection(**options(run)), gc.FOREIGN_CREDENTIAL)
        run.assert_called_once()

    def test_full_flow_creates_completes_and_verifies_once(self):
        responses = [
            response(envelope(integration())),
            response(envelope(integration())),
            response({"attemptID": "attempt-123", "mode": "auto", "url": "", "status": "pending"}),
            response({"status": "complete"}),
            response(envelope(integration(with_pool=True))),
        ]
        run = Mock(side_effect=responses)
        status = gc.ensure_google_connection(**options(run))
        self.assertEqual(status, gc.CONNECTED)
        calls = [call.args[0] for call in run.call_args_list]
        self.assertEqual(calls, [
            ["opencode-cli.exe", "api", "GET", gc.INTEGRATION_PATH],
            ["opencode-cli.exe", "api", "GET", gc.INTEGRATION_PATH],
            ["opencode-cli.exe", "api", "POST", gc.CONNECT_PATH, "--data", START_DATA],
            ["opencode-cli.exe", "api", "POST", f"{gc.CONNECT_PATH}/attempt-123/complete",
             "--data", "{}"],
            ["opencode-cli.exe", "api", "GET", gc.INTEGRATION_PATH],
        ])
        all_args = json.dumps(calls)
        self.assertNotIn("GOOGLE_GENERATIVE_AI_API_KEY", all_args)
        self.assertNotIn("logout", all_args)
        self.assertNotIn("DELETE", all_args)

    def test_recheck_under_lock_catches_a_concurrent_success(self):
        run = Mock(side_effect=[response(envelope(integration())),
                                response(envelope(integration(with_pool=True)))])
        self.assertEqual(gc.ensure_google_connection(**options(run)), gc.ALREADY_CONNECTED)
        self.assertEqual(run.call_count, 2)
        self.assertTrue(all(call.args[0][2] == "GET" for call in run.call_args_list))

    def test_foreign_credential_is_never_duplicated(self):
        run = Mock(return_value=response(envelope(integration(foreign=True))))
        self.assertEqual(gc.ensure_google_connection(**options(run)), gc.FOREIGN_CREDENTIAL)
        run.assert_called_once()

    def test_stale_foreign_oauth_does_not_block_pool_login(self):
        # A dead legacy row (empty access, expires=0, no plugin method) is not a
        # live user credential: create the Hub credential alongside it.
        stale = [{"id": "cred-other", "active": 1, "label": "OAuth",
                  "value": {"methodID": "oauth", "access": "", "expires": 0}}]
        run = Mock(side_effect=[
            response(envelope(integration(foreign=True))),
            response(envelope(integration(foreign=True))),
            response({"attemptID": "attempt-stale", "mode": "auto", "status": "pending"}),
            response({"status": "complete"}),
            response(envelope(integration(with_pool=True, foreign=True))),
        ])
        status = gc.ensure_google_connection(
            **options(run, active_check=lambda _integration: stale))
        self.assertEqual(status, gc.CONNECTED)
        calls = json.dumps([call.args[0] for call in run.call_args_list])
        self.assertIn(gc.POOL_METHOD_ID, calls)
        self.assertNotIn("logout", calls)
        self.assertNotIn("DELETE", calls)

    def test_live_foreign_oauth_still_blocks_pool_login(self):
        live = [{"id": "cred-other", "active": 1, "label": "Somebody else",
                 "value": {"methodID": "oauth", "access": "token", "expires": 4102444800000}}]
        run = Mock(return_value=response(envelope(integration(foreign=True))))
        status = gc.ensure_google_connection(
            **options(run, active_check=lambda _integration: live))
        self.assertEqual(status, gc.FOREIGN_CREDENTIAL)
        run.assert_called_once()

    def test_inactive_hub_credential_is_diagnosed_without_writes(self):
        active_check = Mock(return_value=[{"id": "cred-pool", "active": 0,
                                           "label": gc.POOL_LABEL, "value": {}}])
        run = Mock(return_value=response(envelope(integration(with_pool=True))))
        status = gc.ensure_google_connection(**options(run, active_check=active_check))
        self.assertEqual(status, gc.INACTIVE)
        active_check.assert_called_once_with("google")
        run.assert_called_once()

    def test_vault_method_in_methods_does_not_change_behaviour(self):
        run = Mock(side_effect=[response(envelope(integration())),
                                response(envelope(integration())),
                                response({"attemptID": "a1", "mode": "auto", "status": "pending"}),
                                response({"status": "complete"}),
                                response(envelope(integration(with_pool=True)))])
        self.assertEqual(gc.ensure_google_connection(**options(run)), gc.CONNECTED)

    def test_profile_without_pool_method_is_skipped(self):
        run = Mock(return_value=response(envelope(integration(methods=["antigravity-vault"]))))
        self.assertEqual(gc.ensure_google_connection(**options(run)), gc.SKIP)
        run.assert_called_once()

    def test_absent_cli_is_skipped_without_subprocess(self):
        run = Mock()
        self.assertEqual(gc.ensure_google_connection(**options(run, cli=None)), gc.CLI_MISSING)
        self.assertEqual(gc.ensure_google_connection(**options(run, cli="missing.exe",
                                                              is_file=lambda _path: False)),
                         gc.CLI_MISSING)
        run.assert_not_called()

    def test_unsupported_version_is_skipped_without_subprocess(self):
        run = Mock()
        for version in ("3.0.0", "3.0.9", "3.1.13-beta", "4.0.0", 3.1):
            with self.subTest(version=version):
                self.assertEqual(gc.ensure_google_connection(**options(run, version=version)),
                                 gc.SKIP)
        run.assert_not_called()

    def test_version_is_taken_from_the_hub_helper(self):
        run = Mock()
        with patch("cloudcode_route_patch.get_expected_plugin_version", return_value="3.1.13"):
            self.assertEqual(gc.ensure_google_connection(**options(run, version=None, cli=None)),
                             gc.CLI_MISSING)
        with patch("cloudcode_route_patch.get_expected_plugin_version", return_value="3.0.0"):
            self.assertEqual(gc.ensure_google_connection(**options(run, version=None, cli=None)),
                             gc.SKIP)
        run.assert_not_called()

    def test_api_error_retries_only_reads_and_stays_quiet(self):
        run = Mock(return_value=response(returncode=1, stdout="secret-token-in-response"))
        sleep = Mock()
        with self.assertLogs("ai_hub.google_connection", level="INFO") as logs:
            status = gc.ensure_google_connection(**options(run, sleep=sleep))
        self.assertEqual(status, gc.API_ERROR)
        self.assertEqual(run.call_count, 3)
        self.assertEqual(sleep.call_count, 2)
        self.assertNotIn("secret-token-in-response", "\n".join(logs.output))

    def test_broken_json_is_an_api_error(self):
        run = Mock(side_effect=[response(stdout="not-json") for _ in range(3)])
        self.assertEqual(gc.ensure_google_connection(**options(run, retry_delay=0)), gc.API_ERROR)
        self.assertEqual(run.call_count, 3)

    def test_attempt_without_id_is_not_completed(self):
        run = Mock(side_effect=[response(envelope(integration())),
                                response(envelope(integration())),
                                response({"mode": "auto", "status": "pending"})])
        self.assertEqual(gc.ensure_google_connection(**options(run)), gc.API_ERROR)
        self.assertEqual(run.call_count, 3)

    def test_non_automatic_attempt_is_rejected(self):
        run = Mock(side_effect=[response(envelope(integration())),
                                response(envelope(integration())),
                                response({"attemptID": "a", "mode": "browser", "status": "pending"})])
        self.assertEqual(gc.ensure_google_connection(**options(run)), gc.API_ERROR)
        self.assertEqual(run.call_count, 3)

    def test_unfinished_attempt_is_reported_as_timeout(self):
        run = Mock(side_effect=[response(envelope(integration())),
                                response(envelope(integration())),
                                response({"attemptID": "a", "mode": "auto", "status": "pending"}),
                                response({"attemptID": "a", "status": "pending"})])
        self.assertEqual(gc.ensure_google_connection(**options(run)), gc.TIMEOUT)
        self.assertEqual(run.call_count, 4)

    def test_failed_attempt_is_not_completed(self):
        run = Mock(side_effect=[response(envelope(integration())),
                                response(envelope(integration())),
                                response({"attemptID": "a", "mode": "auto", "status": "failed"})])
        self.assertEqual(gc.ensure_google_connection(**options(run)), gc.TIMEOUT)
        self.assertEqual(run.call_count, 3)

    def test_untrusted_attempt_id_is_rejected(self):
        run = Mock(side_effect=[response(envelope(integration())),
                                response(envelope(integration())),
                                response({"attemptID": "../../danger", "mode": "auto",
                                          "status": "pending"})])
        self.assertEqual(gc.ensure_google_connection(**options(run)), gc.API_ERROR)
        self.assertEqual(run.call_count, 3)

    def test_verify_failure_is_reported(self):
        run = Mock(side_effect=[response(envelope(integration())),
                                response(envelope(integration())),
                                response({"attemptID": "a", "mode": "auto", "status": "pending"}),
                                response({"status": "complete"}),
                                response(envelope(integration()))])
        self.assertEqual(gc.ensure_google_connection(**options(run)), gc.VERIFY_FAILED)

    def test_stop_callback_prevents_work(self):
        run = Mock()
        self.assertEqual(gc.ensure_google_connection(**options(run, stop=lambda: True)), gc.SKIP)
        run.assert_not_called()

    def test_cli_calls_use_run_silent_cmd_with_proxy_stripped_environment(self):
        with patch.object(antigravity_manager, "run_silent_cmd",
                          return_value=response(envelope(integration(with_pool=True)))) as silent, \
             patch.object(proxy_config, "opencode_launch_environment",
                          return_value={"NO_PROXY": "localhost"}) as env:
            status = gc.ensure_google_connection(**options(None, run_cli=None))
        self.assertEqual(status, gc.ALREADY_CONNECTED)
        self.assertEqual(silent.call_args.args[0],
                         ["opencode-cli.exe", "api", "GET", gc.INTEGRATION_PATH])
        self.assertEqual(silent.call_args.kwargs["timeout"], gc.GET_TIMEOUT)
        self.assertEqual(silent.call_args.kwargs["env"], {"NO_PROXY": "localhost"})
        env.assert_called_once_with()

    def test_concurrent_callers_create_one_attempt(self):
        started = threading.Event()
        release = threading.Event()

        def blocking(_args, timeout):
            started.set()
            release.wait(10)
            return response(envelope(integration(with_pool=True)))

        first_run = Mock(side_effect=blocking)
        second_run = Mock()
        results = {}

        def first():
            results["status"] = gc.ensure_google_connection(**options(first_run))

        worker = threading.Thread(target=first, daemon=True)
        worker.start()
        try:
            self.assertTrue(started.wait(10))
            self.assertEqual(gc.ensure_google_connection(**options(second_run)), gc.IN_PROGRESS)
            second_run.assert_not_called()
        finally:
            release.set()
            worker.join(10)
        self.assertEqual(results["status"], gc.ALREADY_CONNECTED)
        first_run.assert_called_once()

    def test_resolve_cli_prefers_the_hub_helper(self):
        with tempfile.TemporaryDirectory() as tmp:
            cli = Path(tmp) / "opencode-cli.exe"
            cli.touch()
            manager = SimpleNamespace(get_opencode_cli=Mock(return_value=str(cli)),
                                      get_opencode_exe=Mock(return_value=None))
            self.assertEqual(gc.resolve_cli(manager=manager), str(cli))
            manager.get_opencode_cli.assert_called_once_with()

    def test_resolve_cli_falls_back_beside_any_installed_opencode(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            exe = root / "AppData" / "Local" / "Programs" / "SomePublisher" / "OpenCode.exe"
            cli = exe.parent / "resources" / "opencode-cli.exe"
            cli.parent.mkdir(parents=True)
            exe.touch()
            cli.touch()
            manager = SimpleNamespace(get_opencode_cli=Mock(return_value=None),
                                      get_opencode_exe=Mock(return_value=None))
            with patch("pathlib.Path.home", return_value=root), \
                 patch.dict("os.environ", {"LOCALAPPDATA": str(root / "AppData" / "Local")}):
                self.assertEqual(gc.resolve_cli(manager=manager, which=lambda _name: None), str(cli))


if __name__ == "__main__":
    unittest.main()
