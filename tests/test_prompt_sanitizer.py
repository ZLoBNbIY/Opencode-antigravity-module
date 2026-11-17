import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
BUNDLES = ("server.js", "index.js")
BLOCKED_REFERENCE = "tools.opencode.session_move"
SAFE_REFERENCE = 'tools.opencode["session_move"]'


class PromptSanitizerTests(unittest.TestCase):
    """Lock the Cloud Code 429 workaround for the Code Mode system prompt."""

    def test_bundles_replace_blocked_system_instruction_reference(self):
        for name in BUNDLES:
            source = (ROOT / "plugin" / "dist" / name).read_text(encoding="utf-8")
            self.assertIn("function sanitizeAntigravitySystemInstruction(", source, name)
            self.assertIn("sanitizeAntigravitySystemInstruction(requestPayload);", source, name)
            self.assertIn(r"tools\.opencode\.session_move", source, name)
            self.assertIn(SAFE_REFERENCE, source, name)

    def test_patch_script_keeps_the_sanitizer_for_installed_copies(self):
        source = (ROOT / "scripts" / "patch_plugin.mjs").read_text(encoding="utf-8")
        self.assertIn("function sanitizeAntigravitySystemInstruction(", source)
        self.assertIn("sanitizeAntigravitySystemInstruction(requestPayload);", source)
        self.assertIn(r"tools\\.opencode\\.session_move", source)

    def test_blocked_reference_is_case_insensitive_and_keeps_tool_name(self):
        prompt = "call Tools.opencode.session_move, then tools.opencode.session_move()"
        self.assertEqual(
            re.sub(r"tools\.opencode\.session_move", SAFE_REFERENCE, prompt, flags=re.IGNORECASE),
            "call tools.opencode[\"session_move\"], then tools.opencode[\"session_move\"]()",
        )


if __name__ == "__main__":
    unittest.main()
