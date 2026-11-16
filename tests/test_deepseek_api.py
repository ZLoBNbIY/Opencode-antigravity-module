import io
import json
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock, patch

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "gui-manager"))
import deepseek_api


BALANCE_PAYLOAD = {
    "is_available": True,
    "balance_infos": [
        {
            "currency": "CNY",
            "total_balance": "110.00",
            "granted_balance": "10.00",
            "topped_up_balance": "100.00",
        }
    ],
}


class DeepSeekApiTests(unittest.TestCase):
    def setUp(self):
        deepseek_api._auto_import_pending = False
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.config_file = root / "deepseek-api.json"
        self.secret_file = root / "deepseek-api-key.json"
        self.patches = [
            patch.object(deepseek_api, "CONFIG_FILE", self.config_file),
            patch.object(deepseek_api, "SECRET_FILE", self.secret_file),
        ]
        for item in self.patches:
            item.start()
        self.addCleanup(self._cleanup)

    def _cleanup(self):
        for item in reversed(self.patches):
            item.stop()
        self.tmp.cleanup()

    def _fake_opener(self, payload=None, status=200):
        opener = MagicMock()
        response = MagicMock()
        response.read.return_value = json.dumps(payload if payload is not None else BALANCE_PAYLOAD).encode("utf-8")
        response.__enter__.return_value = response
        opener.open.return_value = response
        if status != 200:
            opener.open.side_effect = urllib.error.HTTPError(
                "https://api.deepseek.com/user/balance", status, "error", {}, io.BytesIO()
            )
        return opener

    def test_parse_balance_payload_official_example(self):
        result = deepseek_api.parse_balance_payload(BALANCE_PAYLOAD)
        self.assertEqual(result["status"], "ok")
        self.assertTrue(result["is_available"])
        self.assertEqual(result["currency"], "CNY")
        self.assertEqual(result["total_balance"], 110.0)
        self.assertEqual(result["granted_balance"], 10.0)
        self.assertEqual(result["topped_up_balance"], 100.0)

    def test_parse_balance_payload_rejects_empty_response(self):
        with self.assertRaises(ValueError):
            deepseek_api.parse_balance_payload({"is_available": True})
        with self.assertRaises(ValueError):
            deepseek_api.parse_balance_payload({"balance_infos": []})

    def test_fetch_balance_success_and_cache(self):
        opener = self._fake_opener()
        with patch.object(deepseek_api, "get_http_opener", return_value=opener):
            result = deepseek_api.fetch_balance("sk-test-key-1234567890")
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["total_balance"], 110.0)
        request = opener.open.call_args[0][0]
        self.assertEqual(request.full_url, "https://api.deepseek.com/user/balance")
        self.assertEqual(request.get_header("Authorization"), "Bearer sk-test-key-1234567890")
        self.assertEqual(deepseek_api.cached_balance()["total_balance"], 110.0)

    def test_fetch_balance_401_does_not_invent_balance(self):
        opener = self._fake_opener(status=401)
        with patch.object(deepseek_api, "get_http_opener", return_value=opener):
            result = deepseek_api.fetch_balance("sk-bad-key-1234567890")
        self.assertEqual(result["status"], "error")
        self.assertIsNone(result["total_balance"])
        self.assertIn("401", result["error"])

    def test_fetch_balance_failure_keeps_previous_values_as_stale(self):
        first = self._fake_opener()
        with patch.object(deepseek_api, "get_http_opener", return_value=first):
            deepseek_api.fetch_balance("sk-test-key-1234567890")
        failing = self._fake_opener(status=429)
        with patch.object(deepseek_api, "get_http_opener", return_value=failing):
            result = deepseek_api.fetch_balance("sk-test-key-1234567890")
        self.assertEqual(result["status"], "stale")
        self.assertEqual(result["total_balance"], 110.0)
        self.assertIn("429", result["error"])

    def test_key_storage_roundtrip_and_masking(self):
        deepseek_api.save_api_key("sk-secret-key-1234567890")
        loaded = deepseek_api.load_api_key()
        self.assertEqual(loaded, "sk-secret-key-1234567890")
        self.assertEqual(deepseek_api.mask_key(loaded), "sk-••••7890")
        self.assertTrue(deepseek_api.provider_state()["hasKey"])
        self.assertTrue(deepseek_api.provider_state()["connected"])
        deepseek_api.clear_api_key()
        self.assertEqual(deepseek_api.load_api_key(), "")
        self.assertFalse(deepseek_api.provider_state()["hasKey"])

    def test_auto_import_from_opencode_credential_db(self):
        conn = MagicMock()
        conn.execute.return_value.fetchone.return_value = (
            json.dumps({"type": "key", "key": "sk-db-key-1234567890"}),
        )
        conn.__enter__.return_value = conn
        with patch.object(deepseek_api.sqlite3, "connect", return_value=conn):
            self.assertEqual(deepseek_api._key_from_opencode_db(), "sk-db-key-1234567890")

        with patch.object(deepseek_api, "_key_from_environment", return_value=""), \
             patch.object(deepseek_api, "_key_from_opencode_config", return_value=""), \
             patch.object(deepseek_api, "_key_from_opencode_db", return_value="sk-db-key-1234567890"):
            self.assertEqual(deepseek_api.load_api_key(), "sk-db-key-1234567890")
        self.assertTrue(deepseek_api._auto_import_pending)

    def test_auto_import_from_environment(self):
        with patch.dict("os.environ", {"DEEPSEEK_API_KEY": "sk-env-key-1234567890"}, clear=True):
            self.assertEqual(deepseek_api.load_api_key(), "sk-env-key-1234567890")
        self.assertTrue(self.secret_file.exists())
        self.assertEqual(deepseek_api.load_api_key(), "sk-env-key-1234567890")

    def test_api_origin_rejects_non_https_and_credentials(self):
        for bad in ("http://api.deepseek.com", "https://user:pass@api.deepseek.com"):
            with self.assertRaises(ValueError):
                deepseek_api.api_origin(bad)


if __name__ == "__main__":
    unittest.main()
