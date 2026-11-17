import json
from pathlib import Path
import sys
import tempfile
import unittest
import urllib.error
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "gui-manager"))
import tokenlavka_manager


class TokenLavkaManagerTests(unittest.TestCase):
    def test_catalog_contains_documented_models(self):
        for model_id in ("gpt-6-luna", "claude-opus-5-5", "gemini-3.1-pro-preview",
                         "deepseek-v4.1-flash", "qwen-3.8-flash", "economy"):
            self.assertIn(model_id, tokenlavka_manager.TOKENLAVKA_MODELS)
        self.assertEqual(tokenlavka_manager.TOKENLAVKA_MODELS["gpt-6-luna"]["context"], 512000)
        self.assertEqual(tokenlavka_manager.BASE_URL, "https://tokenlavka.com/v1")

    def test_config_writes_openai_compatible_provider(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "opencode.json"
            config_path.write_text(json.dumps({"provider": {"google": {"models": {}}}}), encoding="utf-8")
            selected = tokenlavka_manager.configure_models(
                ["gpt-6-luna", "claude-opus-5-5", "not-a-model"], "sk-test-key", temp_dir)
            self.assertEqual(selected, ["gpt-6-luna", "claude-opus-5-5"])
            saved = json.loads(config_path.read_text(encoding="utf-8"))
            provider = saved["provider"]["tokenlavka"]
            self.assertEqual(provider["npm"], "@ai-sdk/openai-compatible")
            self.assertEqual(provider["options"]["baseURL"], "https://tokenlavka.com/v1")
            self.assertNotIn("apiKey", provider["options"])
            self.assertEqual(set(provider["models"]), {"gpt-6-luna", "claude-opus-5-5"})
            self.assertEqual(provider["models"]["gpt-6-luna"]["limit"]["output"], 65536)
            self.assertIn("google", saved["provider"])

    def test_api_key_is_protected_in_hub_storage(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "tokenlavka.json"
            with patch.object(tokenlavka_manager, "SECRET_FILE", path):
                tokenlavka_manager.save_api_key("sk-tokenlavka-secret")
                self.assertNotIn("sk-tokenlavka-secret", path.read_text(encoding="utf-8"))
                self.assertEqual(tokenlavka_manager.load_api_key(), "sk-tokenlavka-secret")

    def test_parse_balance_payload_computes_remaining_percent(self):
        result = tokenlavka_manager.parse_balance_payload({
            "key": {"total_added": 1000, "balance": 250, "spent": 750, "reserved": 20}
        })
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["issued"], 1000)
        self.assertEqual(result["balance"], 250)
        self.assertEqual(result["spent"], 750)
        self.assertEqual(result["remaining_percent"], 25.0)
        self.assertEqual(result["used_percent"], 75.0)

    def test_parse_balance_infers_spent_and_handles_zero_issued(self):
        result = tokenlavka_manager.parse_balance_payload({
            "key": {"total_added": 500, "balance": 500}
        })
        self.assertEqual(result["spent"], 0)
        self.assertEqual(result["remaining_percent"], 100.0)
        zero = tokenlavka_manager.parse_balance_payload({
            "key": {"total_added": 0, "balance": 0}
        })
        self.assertIsNone(zero["remaining_percent"])

    @patch("tokenlavka_manager._opener")
    def test_fetch_balance_caches_result_and_keeps_stale_on_error(self, get_opener):
        with tempfile.TemporaryDirectory() as temp_dir:
            cfg_path = Path(temp_dir) / "tokenlavka.json"
            opener = Mock()
            get_opener.return_value = opener
            response = Mock()
            response.__enter__ = Mock(return_value=response)
            response.__exit__ = Mock(return_value=False)
            response.read.return_value = json.dumps({
                "key": {"total_added": 1000, "balance": 400, "spent": 600}
            }).encode()
            opener.open.return_value = response
            with patch.object(tokenlavka_manager, "BALANCE_CONFIG_FILE", cfg_path):
                result = tokenlavka_manager.fetch_balance("sk-test-key")
                self.assertEqual(result["remaining_percent"], 40.0)
                self.assertEqual(tokenlavka_manager.cached_balance()["balance"], 400)
                opener.open.side_effect = urllib.error.HTTPError(
                    tokenlavka_manager.PORTAL_URL, 402, "Payment required", {}, None)
                stale = tokenlavka_manager.fetch_balance("sk-test-key")
                self.assertEqual(stale["status"], "stale")
                self.assertEqual(stale["balance"], 400)
                self.assertIn("402", stale["error"])

    @patch("tokenlavka_manager._opener")
    def test_key_validation_maps_auth_errors(self, get_opener):
        opener = Mock()
        get_opener.return_value = opener
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.read.return_value = b'{"data": []}'
        opener.open.return_value = response
        ok, message = tokenlavka_manager.test_connection("sk-test-key")
        self.assertTrue(ok)
        opener.open.side_effect = urllib.error.HTTPError(
            tokenlavka_manager.MODELS_URL, 401, "Unauthorized", {}, None)
        ok, message = tokenlavka_manager.test_connection("sk-bad")
        self.assertFalse(ok)
        self.assertIn("401", message)

    @patch("tokenlavka_manager.subprocess.run")
    @patch("tokenlavka_manager.openai_manager.find_opencode_cli", return_value="opencode-cli")
    def test_opencode_credential_uses_key_variant(self, _find_cli, run):
        run.return_value.returncode = 0
        tokenlavka_manager.sync_opencode_credential("sk-test-key")
        imported = json.loads(run.call_args.kwargs["input"])
        self.assertEqual(imported[0]["integrationID"], "tokenlavka")
        self.assertEqual(imported[0]["value"], {"type": "key", "key": "sk-test-key"})

    @patch("tokenlavka_manager._opener")
    def test_connection_strips_key_and_disconnect_resets_balance_state(self, get_opener):
        opener = Mock()
        get_opener.return_value = opener
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.read.return_value = b'{"data": []}'
        opener.open.return_value = response

        ok, _ = tokenlavka_manager.test_connection("  sk-trimmed  ")
        self.assertTrue(ok)
        self.assertEqual(opener.open.call_args.args[0].get_header("Authorization"), "Bearer sk-trimmed")
        ok_bad, _ = tokenlavka_manager.test_connection("sk-bad\r\nX-Test: 1")
        self.assertFalse(ok_bad)

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            cfg_file = root / "tokenlavka-state.json"
            cfg_file.write_text(json.dumps({"connected": True, "cached_balance": {"balance": 500}}), encoding="utf-8")
            secret_file = root / "tokenlavka.json"
            secret_file.write_text("{}", encoding="utf-8")
            with patch.object(tokenlavka_manager, "CONFIG_DIR", root), \
                 patch.object(tokenlavka_manager, "BALANCE_CONFIG_FILE", cfg_file), \
                 patch.object(tokenlavka_manager, "SECRET_FILE", secret_file), \
                 patch.object(tokenlavka_manager.openai_manager, "find_opencode_cli", return_value="opencode-cli"), \
                 patch("tokenlavka_manager.subprocess.run", return_value=Mock(returncode=0)):
                tokenlavka_manager.disconnect()
            saved = json.loads(cfg_file.read_text(encoding="utf-8"))
            self.assertFalse(saved["connected"])
            self.assertEqual(saved["cached_balance"], {})


if __name__ == "__main__":
    unittest.main()
