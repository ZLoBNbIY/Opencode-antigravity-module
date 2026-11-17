import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "gui-manager"))
from cloudcode_route_patch import get_prompt_sanitizer_status, patch_prompt_sanitizer


PLUGIN_SOURCE = '''function sanitizeRequestPayloadForAntigravity(payload) {
  return payload;
}
function buildRequest(requestPayload) {
        if ("system_instruction" in requestPayload) {
          requestPayload.systemInstruction = requestPayload.system_instruction;
          delete requestPayload.system_instruction;
        }
  return requestPayload;
}
'''


def write_plugin(root: Path, name: str, source: str) -> Path:
    path = root / "node_modules" / "@cortexkit" / "opencode-antigravity-auth" / "dist" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as handle:
        handle.write(source)
    return path


class PromptSanitizerPatchTests(unittest.TestCase):
    def test_patches_server_and_index_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            server = write_plugin(root, "server.js", PLUGIN_SOURCE)
            index = write_plugin(root, "index.js", PLUGIN_SOURCE)

            result = patch_prompt_sanitizer(root)

            self.assertTrue(result["ok"])
            self.assertEqual(len(result["changed"]), 2)
            self.assertIn("Перезапустите OpenCode", result["message"])
            for path in (server, index):
                text = path.read_text(encoding="utf-8")
                self.assertIn("function sanitizeAntigravitySystemInstruction(", text)
                self.assertIn("sanitizeAntigravitySystemInstruction(requestPayload);", text)
                self.assertIn('tools.opencode["session_move"]', text)
                self.assertTrue(path.with_suffix(".js.hub-prompt.bak").exists())

            second = patch_prompt_sanitizer(root)
            self.assertTrue(second["ok"])
            self.assertEqual(second["changed"], [])
            self.assertEqual(len(second["already"]), 2)
            self.assertIn("уже применён", second["message"])

    def test_reports_changed_plugin_layout_without_corrupting_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = "function buildRequest() {\n  return {};\n}\n"
            server = write_plugin(root, "server.js", source)

            result = patch_prompt_sanitizer(root)

            self.assertFalse(result["ok"])
            self.assertEqual(len(result["missing"]), 1)
            self.assertIn("scripts/patch_plugin.mjs", result["message"])
            self.assertEqual(server.read_text(encoding="utf-8"), source)
            self.assertFalse(server.with_suffix(".js.hub-prompt.bak").exists())

    def test_preserves_crlf_line_endings(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = PLUGIN_SOURCE.replace("\n", "\r\n")
            server = write_plugin(root, "server.js", source)

            self.assertTrue(patch_prompt_sanitizer(root)["ok"])

            with open(server, "r", encoding="utf-8", newline="") as handle:
                text = handle.read()
            self.assertIn("function sanitizeAntigravitySystemInstruction(", text)
            self.assertIn("\r\n", text)
            self.assertNotIn("\n", text.replace("\r\n", ""))

    def test_missing_plugin_reports_actionable_message(self):
        with tempfile.TemporaryDirectory() as directory:
            result = patch_prompt_sanitizer(Path(directory))

            self.assertFalse(result["ok"])
            self.assertIn("не найден", result["message"])

    def test_status_tracks_pending_and_patched_copies(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_plugin(root, "server.js", PLUGIN_SOURCE)
            write_plugin(root, "index.js", PLUGIN_SOURCE)

            pending = get_prompt_sanitizer_status(root)
            self.assertEqual(pending["state"], "pending")
            self.assertEqual(pending["pending"], 2)

            patch_prompt_sanitizer(root)

            patched = get_prompt_sanitizer_status(root)
            self.assertEqual(patched["state"], "patched")
            self.assertEqual(patched["patched"], 2)
            self.assertEqual(patched["pending"], 0)

    def test_status_reports_missing_plugin(self):
        with tempfile.TemporaryDirectory() as directory:
            status = get_prompt_sanitizer_status(Path(directory))
            self.assertEqual(status["state"], "missing")
            self.assertEqual(status["found"], 0)


if __name__ == "__main__":
    unittest.main()
