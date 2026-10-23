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
            token_path = Path(temp_dir) / "mwapi_token.json"
            token_path.write_text("{}", encoding="utf-8")

            with patch.object(mwapi_manager, "SECRET_FILE", secret_path), \
                    patch.object(mwapi_manager, "TOKEN_SECRET_FILE", token_path):
                mwapi_manager.disconnect(config_dir=temp_dir)
                saved = json.loads(config_path.read_text(encoding="utf-8"))
                self.assertNotIn("mwapi", saved.get("provider", {}))
                self.assertIn("google", saved["provider"])
                self.assertFalse(secret_path.exists())
                self.assertFalse(token_path.exists())

    def test_dashboard_token_is_protected_in_hub_storage(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "mwapi_token.json"
            with patch.object(mwapi_manager, "TOKEN_SECRET_FILE", path):
                mwapi_manager.save_dashboard_token("eyJhbGciOiJIUzI1NiJ9.mwapi-secret-jwt")
                self.assertNotIn("mwapi-secret-jwt", path.read_text(encoding="utf-8"))
                self.assertEqual(mwapi_manager.load_dashboard_token(), "eyJhbGciOiJIUzI1NiJ9.mwapi-secret-jwt")

    def test_clear_dashboard_token_removes_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "mwapi_token.json"
            with patch.object(mwapi_manager, "TOKEN_SECRET_FILE", path):
                mwapi_manager.save_dashboard_token("some-jwt-token")
                self.assertTrue(path.exists())
                mwapi_manager.clear_dashboard_token()
                self.assertFalse(path.exists())

    @patch("mwapi_manager._request_with_fallback")
    def test_fetch_balance_parses_profile_response(self, mock_request):
        mock_request.return_value = json.dumps({"code": 0, "message": "success", "data": {
            "email": "user@example.com",
            "balance": 12.5,
            "frozen_balance": 1.25,
            "total_recharged": 50,
        }}).encode()

        info = mwapi_manager.fetch_balance("eyJhbGciOiJIUzI1NiJ9.some-token")
        self.assertEqual(info["balance"], 12.5)
        self.assertEqual(info["frozen_balance"], 1.25)
        self.assertEqual(info["total_recharged"], 50.0)
        self.assertEqual(info["email"], "user@example.com")

    def test_fetch_balance_requires_token(self):
        with self.assertRaises(ValueError):
            mwapi_manager.fetch_balance("")

    @patch("mwapi_manager._request_with_fallback")
    def test_fetch_balance_reports_expired_token(self, mock_request):
        import urllib.error
        mock_request.side_effect = urllib.error.HTTPError(
            mwapi_manager.PROFILE_URL, 401, "Unauthorized", {}, None
        )
        with self.assertRaises(ValueError) as ctx:
            mwapi_manager.fetch_balance("expired-token")
        self.assertIn("недействителен", str(ctx.exception))

    def test_parse_usage_data_with_full_payload(self):
        payload = {
            "isValid": True,
            "mode": "quota_limited",
            "status": "active",
            "quota": {
                "limit": 100.0,
                "remaining": 16.2589,
                "unit": "USD",
                "used": 83.7411,
            },
            "remaining": 16.2589,
            "usage": {
                "today": {
                    "requests": 5,
                    "actual_cost": 0.42,
                    "total_tokens": 12000,
                },
                "total": {
                    "requests": 122,
                    "actual_cost": 83.7411,
                    "total_tokens": 8199943,
                },
            },
        }

        parsed = mwapi_manager.parse_usage_data(payload)
        self.assertEqual(parsed["limit"], 100.0)
        self.assertAlmostEqual(parsed["used"], 83.7411)
        self.assertAlmostEqual(parsed["remaining"], 16.2589)
        self.assertAlmostEqual(parsed["used_pct"], 83.7411, places=3)
        self.assertAlmostEqual(parsed["rem_pct"], 16.2589, places=3)
        self.assertEqual(parsed["unit"], "USD")
        self.assertEqual(parsed["status"], "active")
        self.assertEqual(parsed["mode"], "quota_limited")
        self.assertEqual(parsed["total_requests"], 122)
        self.assertEqual(parsed["today_requests"], 5)
        self.assertEqual(parsed["total_tokens"], 8199943)

    def test_parse_usage_data_missing_fields_calculates_sensible_defaults(self):
        # Only limit and remaining
        parsed = mwapi_manager.parse_usage_data({"quota": {"limit": 50, "remaining": 20}})
        self.assertEqual(parsed["limit"], 50.0)
        self.assertEqual(parsed["remaining"], 20.0)
        self.assertEqual(parsed["used"], 30.0)
        self.assertAlmostEqual(parsed["rem_pct"], 40.0)
        self.assertAlmostEqual(parsed["used_pct"], 60.0)

        # Empty payload
        empty = mwapi_manager.parse_usage_data({})
        self.assertIsNone(empty["limit"])
        self.assertIsNone(empty["used"])
        self.assertIsNone(empty["remaining"])
        self.assertIsNone(empty["rem_pct"])

    @patch("mwapi_manager._request_with_fallback")
    def test_fetch_usage_fetches_and_parses_json(self, mock_request):
        mock_request.return_value = json.dumps({
            "quota": {"limit": 100, "used": 25, "remaining": 75, "unit": "USD"},
            "usage": {"total": {"requests": 10, "total_tokens": 50000}},
            "status": "active",
        }).encode("utf-8")

        res = mwapi_manager.fetch_usage("sk-test-key")
        self.assertEqual(res["limit"], 100.0)
        self.assertEqual(res["used"], 25.0)
        self.assertEqual(res["remaining"], 75.0)
        self.assertEqual(res["rem_pct"], 75.0)
        self.assertEqual(res["used_pct"], 25.0)
        self.assertEqual(res["total_requests"], 10)

    def test_fetch_usage_requires_api_key(self):
        with self.assertRaises(ValueError):
            mwapi_manager.fetch_usage("")


if __name__ == "__main__":
    unittest.main()
