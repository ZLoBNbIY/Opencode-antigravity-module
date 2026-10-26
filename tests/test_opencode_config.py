import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "gui-manager"))
import opencode_config


class OpencodeConfigTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.config_dir = Path(self.temp_dir.name)
        self.config_file = self.config_dir / "opencode.json"

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_check_nonexistent_file(self):
        valid, msg = opencode_config.check_session_title_config(self.config_file)
        self.assertFalse(valid)
        self.assertIn("не найден", msg)

    def test_check_valid_config(self):
        data = {
            "$schema": "https://opencode.ai/config.json",
            "model": "google/antigravity-gemini-3.8-flash",
            "small_model": "opencode/big-pickle",
            "agent": {"title": {"model": "opencode/big-pickle"}},
            "agents": {"title": {"model": "opencode/big-pickle"}},
        }
        self.config_file.write_text(json.dumps(data), encoding="utf-8")

        valid, msg = opencode_config.check_session_title_config(self.config_file)
        self.assertTrue(valid)
        self.assertIn("opencode/big-pickle", msg)

    def test_check_invalid_config_wrong_model(self):
        data = {
            "$schema": "https://opencode.ai/config.json",
            "model": "google/antigravity-gemini-3.8-flash",
            "small_model": "google/antigravity-gemini-3.5-flash",
            "agent": {"title": {"model": "google/antigravity-gemini-3.5-flash"}},
            "agents": {"title": {"model": "google/antigravity-gemini-3.5-flash"}},
        }
        self.config_file.write_text(json.dumps(data), encoding="utf-8")

        valid, msg = opencode_config.check_session_title_config(self.config_file)
        self.assertFalse(valid)
        self.assertIn("Некорректная настройка", msg)

    def test_ensure_creates_file_if_missing(self):
        modified, msg = opencode_config.ensure_session_title_config(self.config_file)
        self.assertTrue(modified)
        self.assertTrue(self.config_file.exists())

        data = json.loads(self.config_file.read_text(encoding="utf-8"))
        self.assertEqual(data["small_model"], "opencode/big-pickle")
        self.assertEqual(data["agents"]["title"]["model"], "opencode/big-pickle")
        self.assertEqual(data["agent"]["title"]["model"], "opencode/big-pickle")

    def test_ensure_fixes_existing_config_and_preserves_other_settings(self):
        data = {
            "$schema": "https://opencode.ai/config.json",
            "model": "google/antigravity-gemini-3.8-flash",
            "plugin": ["@cortexkit/opencode-antigravity-auth@latest"],
            "provider": {"google": {"options": {"apiKey": "antigravity"}}},
            "small_model": "google/antigravity-gemini-3.5-flash",
        }
        self.config_file.write_text(json.dumps(data), encoding="utf-8")

        modified, msg = opencode_config.ensure_session_title_config(self.config_file)
        self.assertTrue(modified)

        updated = json.loads(self.config_file.read_text(encoding="utf-8"))
        self.assertEqual(updated["small_model"], "opencode/big-pickle")
        self.assertEqual(updated["agents"]["title"]["model"], "opencode/big-pickle")
        self.assertEqual(updated["agent"]["title"]["model"], "opencode/big-pickle")
        # Preserved other settings
        self.assertEqual(updated["model"], "google/antigravity-gemini-3.8-flash")
        self.assertIn("provider", updated)
        self.assertIn("google", updated["provider"])

    def test_ensure_noop_when_already_correct(self):
        data = {
            "$schema": "https://opencode.ai/config.json",
            "small_model": "opencode/big-pickle",
            "agent": {"title": {"model": "opencode/big-pickle"}},
            "agents": {"title": {"model": "opencode/big-pickle"}},
        }
        self.config_file.write_text(json.dumps(data), encoding="utf-8")

        modified, msg = opencode_config.ensure_session_title_config(self.config_file)
        self.assertFalse(modified)
        self.assertIn("уже корректна", msg)


if __name__ == "__main__":
    unittest.main()
