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


if __name__ == "__main__":
    unittest.main()
