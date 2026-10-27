from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "gui-manager"))
import health_checker


class GoogleHealthTests(unittest.TestCase):
    @patch("health_checker._effective_proxy_from_config", return_value="http://127.0.0.1:20809")
    @patch("health_checker.urllib.request.build_opener")
    def test_google_health_uses_effective_proxy(self, build_opener, effective_proxy):
        opener = build_opener.return_value
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.read.return_value = b'{"models": {"gemini-test": {}}}'
        opener.open.return_value = response

        result = health_checker._test_google_account_health_once({"access": "token"})

        self.assertTrue(result["ok"])
        build_opener.assert_called_once()
        opener.open.assert_called_once()

    @patch("health_checker._test_google_account_health_once")
    def test_refreshes_missing_or_expired_token_before_test(self, check):
        check.return_value = {"ok": True}
        for account in ({}, {"accessToken": "old", "expires": 1}):
            fresh = {"accessToken": "new"}
            refresh = Mock(return_value=fresh)
            self.assertTrue(health_checker.test_google_account_health(account, refresh_account=refresh)["ok"])
            refresh.assert_called_once_with(account)
            check.assert_called_with(fresh, 10)

    @patch("health_checker._test_google_account_health_once")
    def test_retries_401_once(self, check):
        check.side_effect = [{"status": "expired", "ok": False}, {"ok": True}]
        refresh = Mock(return_value={"access": "new"})
        self.assertTrue(health_checker.test_google_account_health({"access": "old"}, refresh_account=refresh)["ok"])
        self.assertEqual(check.call_count, 2)
        refresh.assert_called_once()

    @patch("health_checker._test_google_account_health_once")
    def test_second_401_does_not_loop(self, check):
        check.return_value = {"status": "expired", "ok": False}
        refresh = Mock(return_value={"access": "new"})
        result = health_checker.test_google_account_health({"access": "old"}, refresh_account=refresh)
        self.assertIn("повторный вход", result["message"])
        self.assertEqual(check.call_count, 2)
        refresh.assert_called_once()

    @patch("health_checker._test_google_account_health_once")
    def test_refresh_failure_is_sanitized(self, check):
        refresh = Mock(side_effect=ValueError("secret-token"))
        result = health_checker.test_google_account_health({}, refresh_account=refresh)
        self.assertEqual(result["status"], "refresh_failed")
        self.assertNotIn("secret-token", result["message"])
        check.assert_not_called()

    @patch("health_checker._test_google_account_health_once")
    def test_other_errors_do_not_refresh(self, check):
        for status in ("rate_limited", "http_403", "network_error"):
            check.return_value = {"ok": False, "status": status}
            refresh = Mock()
            health_checker.test_google_account_health({"access": "token"}, refresh_account=refresh)
            refresh.assert_not_called()
