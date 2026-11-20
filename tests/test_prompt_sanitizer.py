import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
BUNDLES = ("server.js", "index.js")


class PromptSanitizerTests(unittest.TestCase):
    def test_shipped_bundles_still_wire_the_existing_sanitizer(self):
        for name in BUNDLES:
            source = (ROOT / "plugin" / "dist" / name).read_text(encoding="utf-8")
            self.assertIn("function sanitizeAntigravitySystemInstruction(", source, name)
            self.assertIn("sanitizeAntigravitySystemInstruction(requestPayload);", source, name)


if __name__ == "__main__":
    unittest.main()
