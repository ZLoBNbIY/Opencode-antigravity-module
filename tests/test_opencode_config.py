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

    def test_ensure_does_not_wipe_malformed_config(self):
        broken = '{"provider": {"openai": {"options": {"apiKey": "keep"}}}, broken'
        self.config_file.write_text(broken, encoding="utf-8")

        modified, msg = opencode_config.ensure_session_title_config(self.config_file)
        self.assertFalse(modified)
        self.assertIn("Ошибка чтения", msg)
        self.assertEqual(self.config_file.read_text(encoding="utf-8"), broken)

    def test_ensure_preserves_jsonc_comments(self):
        jsonc_file = self.config_dir / "opencode.jsonc"
        jsonc_file.write_text(
            '{\n  // keep this comment\n  "model": "google/antigravity-gemini-3.8-flash"\n}\n',
            encoding="utf-8",
        )
        modified, _ = opencode_config.ensure_session_title_config(jsonc_file)
        self.assertTrue(modified)
        updated_text = jsonc_file.read_text(encoding="utf-8")
        self.assertIn("// keep this comment", updated_text)
        parsed = opencode_config._parse_config_text(updated_text)
        self.assertEqual(parsed["small_model"], "opencode/big-pickle")
        self.assertEqual(parsed["agent"]["title"]["model"], "opencode/big-pickle")
        self.assertEqual(parsed["agents"]["title"]["model"], "opencode/big-pickle")

    def test_jsonc_set_property_distinguishes_bool_from_int_and_handles_bom(self):
        import jsonc_config
        raw = '\ufeff{\n  "flag": 1\n}\n'
        updated = jsonc_config.set_property(raw, ("flag",), True)
        self.assertEqual(jsonc_config.parse_config(updated)["flag"], True)
        self.assertIs(jsonc_config.parse_config(updated)["flag"], True)


if __name__ == "__main__":
    unittest.main()
