from pathlib import Path
import json
import io
import shutil
import subprocess
import sys
import time
import unittest
import urllib.error
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "gui-manager"))
import health_checker
from google_health_auth import refresh_google_health_account


class GoogleHealthAuthTests(unittest.TestCase):
    def test_consumes_fresh_pipe_response_not_old_disk_token(self):
        old = {"email": "test@example.com", "accessToken": "old", "access": "also-old"}
        fresh = {"email": old["email"], "accessToken": "new", "expires": time.time() * 1000 + 3600000}
        run = Mock(return_value=SimpleNamespace(returncode=0, stdout=json.dumps(fresh)))
        updated = refresh_google_health_account(old, run, "node", "cli.js")
        self.assertEqual(updated["accessToken"], "new")
        self.assertEqual(updated["access"], "new")
        self.assertEqual(old["accessToken"], "old")
        run.assert_called_once_with(["node", "cli.js", "health-token", "--email", old["email"]], timeout=30)

    def test_rejects_bad_or_wrong_account_responses_without_leaking_secrets(self):
        for payload in ["secret-invalid-json", {}, {"email": "other", "accessToken": "secret"},
                        {"email": "test@example.com", "accessToken": "secret", "expires": 1}]:
            run = Mock(return_value=SimpleNamespace(returncode=0, stdout=json.dumps(payload)))
            with self.assertRaisesRegex(ValueError, "^Google token refresh failed$"):
                refresh_google_health_account({"email": "test@example.com"}, run, "node", "cli")
        run = Mock(return_value=SimpleNamespace(returncode=1, stdout="secret", stderr="secret"))
        with self.assertRaisesRegex(ValueError, "^Google token refresh failed$"):
            refresh_google_health_account({"email": "test@example.com"}, run, "node", "cli")

    @unittest.skipUnless(shutil.which("node"), "Node.js required")
    @patch("health_checker.urllib.request.urlopen")
    def test_cli_pipe_to_gui_retry_uses_new_token(self, urlopen):
        # Disk account remains stale throughout. Only the captured CLI response changes.
        old = {"email": "test@example.com", "accessToken": "old", "expires": time.time() * 1000 + 3600000}
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.read.return_value = b'{"models":{"gemini-test":{},"claude-test":{}}}'
        urlopen.side_effect = [
            urllib.error.HTTPError("https://unused", 401, "Unauthorized", {}, io.BytesIO(b'{}')),
            response,
        ]

        def run(cmd, timeout):
            return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)

        fixture = Path(__file__).parent / "fixtures" / "google_health_cli.mjs"
        refresh = lambda account: refresh_google_health_account(account, run, shutil.which("node"), str(fixture))
        result = health_checker.test_google_account_health(old, refresh_account=refresh)
        self.assertTrue(result["ok"])
        self.assertEqual(urlopen.call_count, 2)
        self.assertEqual(urlopen.call_args_list[0].args[0].get_header("Authorization"), "Bearer old")
        request = urlopen.call_args.args[0]
        self.assertEqual(request.get_header("Authorization"), "Bearer fresh-from-node")
        self.assertEqual(json.loads(request.data)["project"], "fresh-project")
        self.assertEqual(old["accessToken"], "old")
