import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "gui-manager"))
import mwapi_manager


class MwapiManagerTests(unittest.TestCase):
    @patch("mwapi_manager._request_with_fallback")
    def test_catalog_parses_models_and_infers_limits(self, mock_request):
        mock_request.return_value = json.dumps({"data": [
            {"id": "claude-3-7-sonnet-20250219", "name": "Claude 3.7 Sonnet"},
            {"id": "claude-3-5-sonnet-20241022", "name": "Claude 3.5 Sonnet"},
            {"id": "gemini-2.5-pro", "name": "Gemini 2.5 Pro"},
            {"id": "gpt-4o", "name": "GPT-4o"},
            {"id": "custom-code-model", "context_length": 65536},
        ]}).encode()

        models = mwapi_manager.fetch_models("sk-test-mwapi-key")
        self.assertEqual(len(models), 5)

        c37 = next(m for m in models if m["id"] == "claude-3-7-sonnet-20250219")
        self.assertEqual(c37["context"], 200000)
        self.assertEqual(c37["output"], 65536)

        c35 = next(m for m in models if m["id"] == "claude-3-5-sonnet-20241022")
        self.assertEqual(c35["context"], 200000)
        self.assertEqual(c35["output"], 16384)

        gem = next(m for m in models if m["id"] == "gemini-2.5-pro")
        self.assertEqual(gem["context"], 1000000)
        self.assertEqual(gem["output"], 65536)

        custom = next(m for m in models if m["id"] == "custom-code-model")
        self.assertEqual(custom["context"], 65536)

    def test_config_adds_selected_models_in_provider(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "opencode.json"
            config_path.write_text(json.dumps({"provider": {
                "google": {"options": {"apiKey": "antigravity"}}
            }}), encoding="utf-8")

            mwapi_manager.configure_models([
                {"id": "claude-3-7-sonnet-20250219", "name": "Claude 3.7 Sonnet", "context": 200000, "output": 64000},
            ], api_key="sk-test-key", config_dir=temp_dir)

            saved = json.loads(config_path.read_text(encoding="utf-8"))
            mw_provider = saved["provider"]["mwapi"]
            self.assertEqual(mw_provider["name"], "MWAPI (Cloud Code)")
            self.assertEqual(mw_provider["options"]["baseURL"], "https://api.mwapi.dev/v1")
            self.assertEqual(mw_provider["options"]["apiKey"], "sk-test-key")
            self.assertIn("claude-3-7-sonnet-20250219", mw_provider["models"])
            self.assertEqual(saved["provider"]["google"]["options"]["apiKey"], "antigravity")

    def test_api_key_is_protected_in_hub_storage(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "mwapi.json"
            with patch.object(mwapi_manager, "SECRET_FILE", path):
                mwapi_manager.save_api_key("sk-mwapi-secret-token")
                self.assertNotIn("sk-mwapi-secret-token", path.read_text(encoding="utf-8"))
                self.assertEqual(mwapi_manager.load_api_key(), "sk-mwapi-secret-token")

    @patch("mwapi_manager.subprocess.run")
    @patch("mwapi_manager.openai_manager.find_opencode_cli", return_value="opencode-cli")
    def test_opencode_credential_uses_current_key_variant(self, _find_cli, run):
        run.return_value.returncode = 0
        mwapi_manager.sync_opencode_credential("sk-mwapi-test-secret")
        imported = json.loads(run.call_args.kwargs["input"])
        self.assertEqual(imported[0]["value"], {"type": "key", "key": "sk-mwapi-test-secret"})
        self.assertEqual(imported[0]["integrationID"], "mwapi")

    @patch("mwapi_manager.subprocess.run")
    @patch("mwapi_manager.openai_manager.find_opencode_cli", return_value="opencode-cli")
    def test_disconnect_removes_provider_and_key(self, _find_cli, run):
        run.return_value.returncode = 0
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "opencode.json"
            config_path.write_text(json.dumps({
                "provider": {
                    "google": {"options": {"apiKey": "antigravity"}},
                    "mwapi": {"name": "MWAPI"}
                }
            }), encoding="utf-8")
            secret_path = Path(temp_dir) / "mwapi.json"
            secret_path.write_text("{}", encoding="utf-8")

            with patch.object(mwapi_manager, "SECRET_FILE", secret_path):
                mwapi_manager.disconnect(config_dir=temp_dir)
                saved = json.loads(config_path.read_text(encoding="utf-8"))
                self.assertNotIn("mwapi", saved.get("provider", {}))
                self.assertIn("google", saved["provider"])
                self.assertFalse(secret_path.exists())


if __name__ == "__main__":
    unittest.main()
