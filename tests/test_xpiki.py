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


if __name__ == "__main__":
    unittest.main()
