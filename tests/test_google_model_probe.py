import io
import ast
import json
import sys
import unittest
import tempfile
import urllib.error
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "gui-manager"))
import health_checker


def response(data):
    result = Mock()
    result.__enter__ = Mock(return_value=result)
    result.__exit__ = Mock(return_value=False)
    result.read.return_value = ("data: " + json.dumps(data) + "\n\n").encode()
    return result


def http_error(code, message):
    return urllib.error.HTTPError("https://example.test", code, "error", {},
                                  io.BytesIO(json.dumps({"error": {"message": message}}).encode()))


class GoogleModelProbeTests(unittest.TestCase):
    def setUp(self):
        self.build = patch("health_checker.urllib.request.build_opener").start()
        self.addCleanup(patch.stopall)
        self.opener = self.build.return_value

    def probe(self):
        return health_checker.test_antigravity_model({"accessToken": "secret", "projectId": "project"},
                                                     "antigravity-gemini-3.8-flash", proxy_url="")

    def test_text_generation_stops_without_second_request(self):
        self.opener.open.return_value = response({"response": {"candidates": [
            {"content": {"parts": [{"text": "OK"}]}, "finishReason": "STOP"}]}})
        result = self.probe()
        self.assertTrue(result["ok"])
        self.assertEqual(result["response_text"], "OK")
        self.assertEqual(self.opener.open.call_count, 1)
        request = self.opener.open.call_args.args[0]
        self.assertEqual(json.loads(request.data)["model"], "gemini-3.8-flash-high")
        self.assertGreaterEqual(json.loads(request.data)["request"]["generationConfig"]["maxOutputTokens"], 2048)
        # Explicit direct mode must suppress inherited environment proxies.
        self.assertEqual(self.build.call_args.args[0].proxies, {})

    def test_thinking_or_candidate_alone_is_not_success(self):
        self.opener.open.return_value = response({"response": {"candidates": [
            {"content": {"parts": [{"text": "thinking", "thought": True}]}, "finishReason": "MAX_TOKENS"}]}})
        result = self.probe()
        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "output_limit")
        self.assertEqual(self.opener.open.call_count, 1)

    def test_preserves_region_and_quota_errors_separately(self):
        self.opener.open.side_effect = [http_error(400, "User location is not supported for the API use."),
                                       http_error(429, "Resource has been exhausted")]
        result = self.probe()
        self.assertEqual([item["status"] for item in result["attempts"]], ["geo_blocked", "rate_limited"])
        report = health_checker.format_model_probe_result(result)
        self.assertIn("daily-cloudcode-pa.googleapis.com", report)
        self.assertIn("cloudcode-pa.googleapis.com", report)
        self.assertNotIn("secret", report)

    def test_401_does_not_retry_other_endpoint(self):
        self.opener.open.side_effect = http_error(401, "Unauthorized")
        self.assertEqual(self.probe()["status"], "expired")
        self.assertEqual(self.opener.open.call_count, 1)

    def test_http_200_with_sse_error_is_failure(self):
        self.opener.open.return_value = response({"response": {"error": {"message": "backend failed"}}})
        result = self.probe()
        self.assertFalse(result["ok"])
        self.assertTrue(all(item["status"] == "api_error" for item in result["attempts"]))

    def test_invalid_or_empty_stream_is_not_success(self):
        self.opener.open.return_value = response({})
        self.assertEqual(self.probe()["status"], "empty_response")


class ActiveAccountSelectionTests(unittest.TestCase):
    def test_omitted_export_row_does_not_change_test_account(self):
        source = Path(__file__).resolve().parent.parent / "gui-manager" / "antigravity_manager.pyw"
        tree = ast.parse(source.read_text(encoding="utf-8-sig"))
        method = next(n for n in tree.body if isinstance(n, ast.FunctionDef)
                      and n.name == "get_active_google_health_account")
        namespace = {"Path": Path, "json": json,
                     "export_google_accounts": lambda: [{"id": "second", "email": "active@example.test"}],
                     "get_active_google_account_index": lambda: 1}
        exec(compile(ast.Module(body=[method], type_ignores=[]), str(source), "exec"), namespace)
        with tempfile.TemporaryDirectory() as directory, patch.object(Path, "home", return_value=Path(directory)):
            generation = Path(directory) / ".config" / "opencode" / "test.generation"
            generation.mkdir(parents=True)
            (generation / "config.json").write_text(json.dumps({"accounts": [{"id": "first"}, {"id": "second"}]}))
            self.assertEqual(namespace["get_active_google_health_account"]()["id"], "second")
            namespace["get_active_google_account_index"] = lambda: 0
            self.assertIsNone(namespace["get_active_google_health_account"]())


if __name__ == "__main__":
    unittest.main()
