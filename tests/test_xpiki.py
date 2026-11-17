import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "gui-manager"))
import xpiki_manager


class FakeResponse:
    def __init__(self, payload):
        self.payload = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return self.payload


class FakeOpener:
    def __init__(self, response):
        self.response = response
        self.request = None

    def open(self, request, timeout):
        self.request = request
        return self.response


class XpikiQuotaTests(unittest.TestCase):
    def test_uses_actual_account_quota_and_bodyless_post(self):
        opener = FakeOpener(FakeResponse({
            "code": 0,
            "data": {
                "quota_limit": 15000000,
                "quota_used": 2000000,
                "effective_rpm": 42,
                "effective_tpm": 123456,
                "expires_at": "2030-01-01T00:00:00Z",
            },
        }))
        with patch.object(xpiki_manager, "get_http_opener", return_value=opener), \
             patch.object(xpiki_manager, "load_xpiki_config", return_value={}), \
             patch.object(xpiki_manager, "save_xpiki_config"):
            result = xpiki_manager.fetch_xpiki_quota("sk-test")

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["quota_limit"], 15000000)
        self.assertEqual(result["remaining_tokens"], 13000000)
        self.assertEqual(result["effective_rpm"], 42)
        self.assertEqual(opener.request.get_method(), "POST")
        self.assertIsNone(opener.request.data)
        self.assertEqual(opener.request.get_header("Authorization"), "Bearer sk-test")

    def test_does_not_invent_default_quota_on_error(self):
        opener = FakeOpener(FakeResponse({"code": 1, "message": "invalid key"}))
        with patch.object(xpiki_manager, "get_http_opener", return_value=opener), \
             patch.object(xpiki_manager, "load_xpiki_config", return_value={}), \
             patch.object(xpiki_manager, "save_xpiki_config"):
            result = xpiki_manager.fetch_xpiki_quota("sk-test")

        self.assertEqual(result["status"], "error")
        self.assertIsNone(result["quota_limit"])
        self.assertIsNone(result["remaining_tokens"])

    def test_xpiki_config_protected_at_rest_and_reads_legacy_plaintext(self):
        import os
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            cfg_file = Path(tmp) / "xpiki.json"
            with patch.object(xpiki_manager, "XPIKI_CONFIG_FILE", cfg_file), \
                 patch.object(xpiki_manager, "CONFIG_DIR", Path(tmp)):
                self.assertTrue(xpiki_manager.save_xpiki_config({"api_key": "sk-xpiki-secret", "connected": True}))
                raw = cfg_file.read_text(encoding="utf-8")
                if os.name == "nt":
                    self.assertNotIn("sk-xpiki-secret", raw)
                self.assertEqual(xpiki_manager.load_xpiki_config()["api_key"], "sk-xpiki-secret")

                # Legacy plaintext fallback
                cfg_file.write_text(json.dumps({"api_key": "sk-legacy", "connected": True}), encoding="utf-8")
                self.assertEqual(xpiki_manager.load_xpiki_config()["api_key"], "sk-legacy")

                with patch.object(xpiki_manager, "configure_opencode", return_value=True):
                    self.assertTrue(xpiki_manager.disconnect_xpiki())
                cleared = xpiki_manager.load_xpiki_config()
                self.assertFalse(cleared["connected"])
                self.assertEqual(cleared["api_key"], "")
                self.assertEqual(cleared["cached_quota"], {})

    def test_connection_does_not_mask_401_with_messages_probe(self):
        import io
        import urllib.error
        opener = FakeOpener(None)
        def fail_401(req, timeout):
            raise urllib.error.HTTPError(req.full_url, 401, "Unauthorized", {}, io.BytesIO(b""))
        with patch.object(xpiki_manager, "get_http_opener", return_value=opener), \
             patch.object(opener, "open", side_effect=fail_401) as open_mock:
            ok, msg, _ = xpiki_manager.test_xpiki_connection("sk-bad")
        self.assertFalse(ok)
        self.assertIn("401", msg)
        self.assertEqual(open_mock.call_count, 1)


if __name__ == "__main__":
    unittest.main()
