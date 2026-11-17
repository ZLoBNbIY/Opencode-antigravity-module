import io
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "gui-manager"))
import claude_manager
from claude_manager import ClaudeAccountManager, ClaudeSubscriptionBridge, CLAUDE_MODELS


class ClaudeManagerTests(unittest.TestCase):
    def test_models_defined(self):
        self.assertIn("claude-3-7-sonnet", CLAUDE_MODELS)
        self.assertIn("claude-3-5-sonnet", CLAUDE_MODELS)
        self.assertIn("claude-3-opus", CLAUDE_MODELS)
        self.assertEqual(CLAUDE_MODELS["claude-3-7-sonnet"]["limit"]["context"], 200000)

    def test_claude_manager_empty_accounts(self):
        mgr = ClaudeAccountManager()
        # Verify load_accounts returns a list
        accs = mgr.load_accounts()
        self.assertIsInstance(accs, list)

    def test_non_streaming_completion_returns_json_and_uses_web_completion_endpoint(self):
        bridge = ClaudeSubscriptionBridge()
        handler = MagicMock()
        handler.wfile = io.BytesIO()

        seen_urls = []

        class FakeResp:
            def __init__(self, body: bytes):
                self._body = body

            def read(self):
                return self._body

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        def fake_open(req, timeout=45):
            seen_urls.append(req.full_url)
            if req.full_url.endswith("/chat_conversations"):
                return FakeResp(b'{"uuid":"conv-1"}')
            return FakeResp(b'data: {"completion":"Hello "}\n\ndata: {"completion":"world"}\n\n')

        opener = MagicMock()
        opener.open.side_effect = fake_open

        with patch.object(claude_manager, "get_http_opener", return_value=opener):
            bridge.handle_completion_request(
                handler,
                {"model": "claude-pro/claude-3-7-sonnet", "stream": False, "messages": [{"role": "user", "content": "hi"}]},
                {"session_key": "sk-ant-sid01-test", "org_id": "org-123", "token_type": "session_key"},
            )

        handler.send_response.assert_called_once_with(200)
        body = json.loads(handler.wfile.getvalue().decode("utf-8"))
        self.assertEqual(body["choices"][0]["message"]["content"], "Hello world")
        self.assertEqual(len(seen_urls), 2)
        self.assertEqual(seen_urls[0], "https://claude.ai/api/organizations/org-123/chat_conversations")
        self.assertTrue(seen_urls[1].startswith("https://claude.ai/api/organizations/org-123/chat_conversations/"))
        self.assertTrue(seen_urls[1].endswith("/completion"))

    def test_bridge_requires_token_and_protects_accounts_at_rest(self):
        import tempfile
        import urllib.request
        import urllib.error

        bridge = ClaudeSubscriptionBridge(port=0)
        self.assertFalse(bridge._is_authorized({}))
        self.assertFalse(bridge._is_authorized({"Authorization": "Bearer wrong"}))
        self.assertTrue(bridge._is_authorized({"Authorization": f"Bearer {bridge.bridge_token}"}))
        self.assertTrue(bridge._is_authorized({"x-api-key": bridge.bridge_token}))

        with tempfile.TemporaryDirectory() as tmp:
            accounts_file = Path(tmp) / "claude-accounts.json"
            with patch.object(claude_manager, "CLAUDE_ACCOUNTS_FILE", accounts_file), \
                 patch.object(claude_manager, "CONFIG_DIR", Path(tmp)):
                mgr = ClaudeAccountManager()
                self.assertTrue(mgr.save_accounts([{"email": "c@example.com", "session_key": "sk-ant-secret"}]))
                raw_text = accounts_file.read_text(encoding="utf-8")
                if claude_manager.os.name == "nt":
                    self.assertNotIn("sk-ant-secret", raw_text)
                loaded = mgr.load_accounts()
                self.assertEqual(loaded[0]["session_key"], "sk-ant-secret")


if __name__ == "__main__":
    unittest.main()
