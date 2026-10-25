import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "gui-manager"))
import claude_manager
from claude_manager import ClaudeAccountManager, CLAUDE_MODELS


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


if __name__ == "__main__":
    unittest.main()
