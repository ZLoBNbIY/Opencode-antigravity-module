import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "gui-manager"))
import museai_manager
import deepseek_storage


class MuseAiManagerTests(unittest.TestCase):
    def test_fetch_models_uses_bearer_auth_and_catalog(self):
        class Response:
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self): return b'{"data":[{"id":"muse-chat","name":"Muse Chat"}]}'

        with patch.object(museai_manager.urllib.request, "urlopen", return_value=Response()) as request:
            result = museai_manager.fetch_models("http://127.0.0.1:18610/v1", "secret")
        self.assertEqual(result, [{"id":"muse-chat", "name":"Muse Chat"}])
        self.assertEqual(request.call_args.args[0].get_header("Authorization"), "Bearer secret")

    def test_configure_opencode_preserves_existing_settings(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "opencode.json"
            path.write_text('{"model":"google/gemini","provider":{"google":{"options":{"apiKey":"x"}}}}', encoding="utf-8")
            museai_manager.configure_opencode("http://127.0.0.1:18610/v1", [{"id":"muse-chat","name":"Muse Chat"}], temp)
            config = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(config["model"], "google/gemini")
        self.assertIn("google", config["provider"])
        provider = config["provider"]["museai"]
        self.assertEqual(provider["options"]["baseURL"], "http://127.0.0.1:18610/v1")
        self.assertIn("muse-chat", provider["models"])
        self.assertNotIn("apiKey", provider["options"])

    def test_rejects_invalid_endpoint_and_missing_key(self):
        with self.assertRaisesRegex(ValueError, "URL"):
            museai_manager.fetch_models("file:///tmp", "key")
        with self.assertRaisesRegex(ValueError, "API-ключ"):
            museai_manager.fetch_models("http://127.0.0.1:18610/v1", "")

    def test_gateway_credentials_use_supported_protected_secret_purpose(self):
        payload = {"gateway_api_key":"local-api", "gateway_admin_key":"local-admin"}
        record = deepseek_storage.protect_secret(museai_manager.SECRET_PURPOSE, payload)
        self.assertEqual(deepseek_storage.unprotect_secret(record, museai_manager.SECRET_PURPOSE), payload)

    def test_cookie_expirations_are_normalized_to_integer_seconds(self):
        result = museai_manager.normalize_cookie_expiry({"hatch_sess": 1794160618.75, "session": None,
                                                          "bad": "not-a-time"})
        self.assertEqual(result, {"hatch_sess": 1794160618})

    def test_cookie_filter_drops_host_prefixed_and_unrelated_cookies(self):
        result = museai_manager.filter_museai_cookies({
            "hatch_sess": "session", "hatch_gw": "gateway",
            "hatch_native_auth_device": "device", "hatch_vml": "lease", "datr": "meta",
            "__Host-hatch_one_tap": "host-only", "_fbp": "analytics", "wd": "viewport",
        })
        self.assertEqual(set(result), set(museai_manager.MUSEAI_COOKIE_ALLOWLIST))
        self.assertNotIn("__Host-hatch_one_tap", result)

    def test_relogin_updates_existing_primary_account(self):
        class Response:
            def __init__(self, body=b"", status=200): self.body, self.status = body, status
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self): return self.body

        with patch.object(museai_manager.urllib.request, "urlopen", side_effect=[
            Response(b'{"data":[{"id":"acc_existing","label":"primary-account"}]}'),
            Response(status=200),
        ]) as request:
            museai_manager._upsert_gateway_account("admin-key", {"cookies":{"hatch_sess":"secret"}})
        update = request.call_args_list[1].args[0]
        self.assertEqual(update.get_method(), "PATCH")
        self.assertTrue(update.full_url.endswith("/acc_existing"))


if __name__ == "__main__":
    unittest.main()
