import io
import json
import os
import sqlite3
import tempfile
import time
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock, patch

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "gui-manager"))
import deepseek_api
import opencode_credentials


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
            # Keep tests away from the developer's real OpenCode database.
            patch.object(opencode_credentials, "database_path", return_value=None),
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

    def test_parse_balance_payload_prefers_funded_currency_whatever_the_order(self):
        # The live API flips the order of balance_infos between calls; a zero
        # USD entry must not shadow the funded CNY balance.
        usd_first = {
            "is_available": True,
            "balance_infos": [
                {"currency": "USD", "total_balance": "0.00",
                 "granted_balance": "0.00", "topped_up_balance": "0.00"},
                {"currency": "CNY", "total_balance": "6.05",
                 "granted_balance": "0.00", "topped_up_balance": "6.05"},
            ],
        }
        for payload in (usd_first, {"is_available": True,
                                    "balance_infos": list(reversed(usd_first["balance_infos"]))}):
            result = deepseek_api.parse_balance_payload(payload)
            self.assertEqual(result["currency"], "CNY")
            self.assertEqual(result["total_balance"], 6.05)

    def test_parse_balance_payload_all_zero_prefers_cny(self):
        payload = {
            "is_available": False,
            "balance_infos": [
                {"currency": "USD", "total_balance": "0.00",
                 "granted_balance": "0.00", "topped_up_balance": "0.00"},
                {"currency": "CNY", "total_balance": "0.00",
                 "granted_balance": "0.00", "topped_up_balance": "0.00"},
            ],
        }
        result = deepseek_api.parse_balance_payload(payload)
        self.assertEqual(result["currency"], "CNY")
        self.assertEqual(result["total_balance"], 0.0)

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
        with patch.object(deepseek_api, "_opencode_candidate",
                          return_value=("sk-db-key-1234567890", int(time.time() * 1000))):
            self.assertEqual(deepseek_api.load_api_key(), "sk-db-key-1234567890")
        self.assertTrue(deepseek_api._auto_import_pending)

    def test_auto_import_accepts_legacy_api_credential_variant(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "opencode.db"
            conn = sqlite3.connect(db)
            conn.execute("CREATE TABLE credential (id text PRIMARY KEY, integration_id text, "
                         "value text, time_updated integer)")
            conn.execute("INSERT INTO credential VALUES (?, ?, ?, ?)",
                         ("cred_1", "deepseek", json.dumps({"type": "api", "key": "sk-legacy-key-1234567890"}), 7))
            conn.commit()
            conn.close()
            with patch.object(opencode_credentials, "database_path", return_value=db):
                opencode_credentials.invalidate()
                self.assertEqual(deepseek_api._key_from_opencode_db(), "sk-legacy-key-1234567890")

    def test_newer_opencode_key_replaces_the_stored_one(self):
        deepseek_api.save_api_key("sk-hub-key-1234567890")
        past = time.time() - 3600
        os.utime(self.secret_file, (past, past))
        with patch.object(deepseek_api, "_opencode_candidate",
                          return_value=("sk-new-key-1234567890", int(time.time() * 1000))):
            self.assertEqual(deepseek_api.load_api_key(), "sk-new-key-1234567890")
        self.assertTrue(deepseek_api._auto_import_pending)
        self.assertEqual(deepseek_api._stored_key()[0], "sk-new-key-1234567890")

    def test_older_opencode_key_does_not_replace_the_stored_one(self):
        deepseek_api.save_api_key("sk-hub-key-1234567890")
        with patch.object(deepseek_api, "_opencode_candidate",
                          return_value=("sk-old-key-1234567890", 1)):
            self.assertEqual(deepseek_api.load_api_key(), "sk-hub-key-1234567890")
        self.assertFalse(deepseek_api._auto_import_pending)
        self.assertEqual(deepseek_api._stored_key()[0], "sk-hub-key-1234567890")

    def test_saving_key_re_enables_adoption_after_disconnect(self):
        deepseek_api.clear_api_key()
        self.assertTrue(deepseek_api.load_config()["auto_import_disabled"])
        deepseek_api.save_api_key("sk-new-key-1234567890")
        self.assertFalse(deepseek_api.load_config()["auto_import_disabled"])
        self.assertEqual(deepseek_api.load_api_key(), "sk-new-key-1234567890")

    def test_auto_import_from_environment(self):
        with patch.dict("os.environ", {"DEEPSEEK_API_KEY": "sk-env-key-1234567890"}, clear=True):
            self.assertEqual(deepseek_api.load_api_key(), "sk-env-key-1234567890")
        self.assertTrue(self.secret_file.exists())
        self.assertEqual(deepseek_api.load_api_key(), "sk-env-key-1234567890")

    def test_api_origin_rejects_non_https_and_credentials(self):
        for bad in ("http://api.deepseek.com", "https://user:pass@api.deepseek.com"):
            with self.assertRaises(ValueError):
                deepseek_api.api_origin(bad)

    def test_fetch_models_reads_real_catalog(self):
        opener = self._fake_opener({"object": "list", "data": [
            {"id": "deepseek-chat", "object": "model"},
            {"id": "deepseek-reasoner", "object": "model"},
            {"bad": True},
        ]})
        with patch.object(deepseek_api, "get_http_opener", return_value=opener):
            models = deepseek_api.fetch_models("sk-test-key-1234567890")
        self.assertEqual([m["id"] for m in models], ["deepseek-chat", "deepseek-reasoner"])
        self.assertEqual(models[0]["context"], 65536)
        request = opener.open.call_args[0][0]
        self.assertEqual(request.full_url, "https://api.deepseek.com/models")
        self.assertEqual(request.get_header("Authorization"), "Bearer sk-test-key-1234567890")

    def test_configure_opencode_models_registers_provider_and_preserves_user_settings(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg_path = root / "opencode.json"
            cfg_path.write_text(json.dumps({
                "provider": {
                    "deepseek": {
                        "npm": "@ai-sdk/openai-compatible",
                        "name": "My DeepSeek",
                        "options": {"baseURL": "https://api.deepseek.com"},
                        "models": {"deepseek-chat": {"name": "Keep me"}},
                    }
                }
            }), encoding="utf-8")
            deepseek_api.save_api_key("sk-test-key-1234567890")
            with patch.object(deepseek_api, "_opencode_config_path", return_value=cfg_path):
                # Adopt the user's existing provider id instead of duplicating it.
                self.assertEqual(deepseek_api.find_provider_id(), "deepseek")
                saved = deepseek_api.configure_opencode_models(
                    ["deepseek-chat", "deepseek-reasoner"], "sk-test-key-1234567890")
                self.assertEqual(saved, ["deepseek-chat", "deepseek-reasoner"])
                data = json.loads(cfg_path.read_text(encoding="utf-8"))
                self.assertEqual(data["provider"]["deepseek"]["name"], "My DeepSeek")
                self.assertEqual(
                    sorted(data["provider"]["deepseek"]["models"]),
                    ["deepseek-chat", "deepseek-reasoner"])
                self.assertEqual(deepseek_api.selected_models(), ["deepseek-chat", "deepseek-reasoner"])

    def test_configure_opencode_models_creates_provider_when_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg_path = Path(tmp) / "opencode.jsonc"
            cfg_path.write_text('{\n  // keep\n  "model": "x"\n}\n', encoding="utf-8")
            deepseek_api.save_api_key("sk-test-key-1234567890")
            with patch.object(deepseek_api, "_opencode_config_path", return_value=cfg_path):
                saved = deepseek_api.configure_opencode_models(["deepseek-chat"], "sk-test-key-1234567890")
                self.assertEqual(saved, ["deepseek-chat"])
                text = cfg_path.read_text(encoding="utf-8")
                self.assertIn("// keep", text)
                data = deepseek_api.jsonc_config.parse_config(text)
                provider = data["provider"]["deepseek-account"]
                self.assertEqual(provider["npm"], "@ai-sdk/openai-compatible")
                self.assertEqual(provider["options"]["baseURL"], "https://api.deepseek.com")
                self.assertIn("deepseek-chat", provider["models"])

    def test_find_provider_id_reuses_the_opencode_login(self):
        with patch.object(opencode_credentials, "has_credential", return_value=True):
            self.assertEqual(deepseek_api.find_provider_id({}), "deepseek")

    def test_configure_opencode_models_keeps_the_builtin_provider_descriptor(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg_path = Path(tmp) / "opencode.json"
            cfg_path.write_text(json.dumps({"provider": {}}), encoding="utf-8")
            deepseek_api.save_api_key("sk-test-key-1234567890")
            with patch.object(deepseek_api, "_opencode_config_path", return_value=cfg_path), \
                 patch.object(opencode_credentials, "has_credential", return_value=True):
                saved = deepseek_api.configure_opencode_models(["deepseek-chat"], "sk-test-key-1234567890")
                self.assertEqual(saved, ["deepseek-chat"])
                data = json.loads(cfg_path.read_text(encoding="utf-8"))
                provider = data["provider"]["deepseek"]
                # Only the model list is attached; OpenCode keeps its own npm/baseURL.
                self.assertNotIn("npm", provider)
                self.assertNotIn("options", provider)
                self.assertIn("deepseek-chat", provider["models"])

    def test_sync_updates_the_existing_opencode_credential_row(self):
        with patch.object(deepseek_api, "find_provider_id", return_value="deepseek"), \
             patch.object(opencode_credentials, "credential_id", return_value="cred_existing"), \
             patch.object(deepseek_api.openai_manager, "find_opencode_cli", return_value="cli"), \
             patch("subprocess.run", return_value=MagicMock(returncode=0)) as run:
            deepseek_api.sync_opencode_credential("sk-test-key-1234567890")
        imported = json.loads(run.call_args.kwargs["input"])[0]
        self.assertEqual(imported["id"], "cred_existing")
        self.assertEqual(imported["integrationID"], "deepseek")
        self.assertEqual(imported["value"], {"type": "key", "key": "sk-test-key-1234567890"})


if __name__ == "__main__":
    unittest.main()
