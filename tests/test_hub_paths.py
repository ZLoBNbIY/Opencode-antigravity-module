import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "gui-manager"))

import hub_paths
from secure_storage import atomic_write_bytes


class HubPathsTests(unittest.TestCase):
    def test_sync_preserves_newer_valid_mirror_and_does_not_overwrite_invalid_json(self):
        with TemporaryDirectory() as root:
            central = Path(root) / "hub" / "antigravity.json"
            mirror = Path(root) / "opencode" / "antigravity.json"
            atomic_write_bytes(central, b'{"old":true}')
            atomic_write_bytes(mirror, b'{"new":true}')
            os.utime(central, (1, 1))
            with patch.multiple(hub_paths, HUB_CONFIG_FILE=central,
                                OPENCODE_SHARED_ANTIGRAVITY_CONFIG=mirror):
                hub_paths.sync_shared_antigravity_config()
                self.assertEqual(central.read_bytes(), b'{"new":true}')
                atomic_write_bytes(mirror, b"{")
                os.utime(central, (1, 1))
                hub_paths.sync_shared_antigravity_config()
                self.assertEqual(mirror.read_bytes(), b"{")
                self.assertEqual(hub_paths.read_mirrored_antigravity_config(), {"new": True})

    def test_config_dir_only_honors_absolute_overrides(self):
        with TemporaryDirectory() as root:
            home = Path(root) / "home"
            override = Path(root) / "override"
            xdg = Path(root) / "xdg"
            with patch.object(Path, "home", return_value=home):
                for direct, base, expected in (
                    (str(override), str(xdg), override),
                    ("relative", str(xdg), xdg / "opencode"),
                    ("", "relative", home / ".config" / "opencode"),
                ):
                    with self.subTest(direct=direct, base=base), patch.dict(
                        os.environ, OPENCODE_CONFIG_DIR=direct, XDG_CONFIG_HOME=base,
                        APPDATA=str(Path(root) / "roaming"),
                    ):
                        self.assertEqual(hub_paths.get_opencode_config_dir(), expected)
            self.assertEqual(list(Path(root).iterdir()), [])

    def test_startup_seeds_only_explicit_shared_config_without_copying_secrets(self):
        with TemporaryDirectory() as root:
            home = Path(root)
            legacy_opencode = home / ".config" / "opencode"
            legacy_secret = home / ".local" / "share" / "antigravity-hub"
            legacy_files = [legacy_opencode / "openai-accounts.json",
                            legacy_opencode / "xpiki.json",
                            legacy_opencode / "tokenlavka.json",
                            legacy_opencode / "claude_profile" / "Cookies",
                            legacy_secret / "openrouter.json", legacy_secret / "tokenlavka.json"]
            hub = home / "hub"
            for path in legacy_files:
                atomic_write_bytes(path, b'{"apiKey":"legacy-sample"}')
            with patch.object(Path, "home", return_value=home), patch.multiple(
                hub_paths, HUB_CONFIG_FILE=hub / "antigravity.json",
                OPENCODE_SHARED_ANTIGRAVITY_CONFIG=home / "active" / "antigravity.json",
                OPENAI_ACCOUNTS_FILE=hub / "openai-accounts.json",
                XPIKI_CONFIG_FILE=hub / "xpiki.json", TOKENLAVKA_CONFIG_FILE=hub / "state" / "tokenlavka.json",
                CLAUDE_PROFILE_DIR=hub / "claude_profile", OPENROUTER_SECRET_FILE=hub / "openrouter.json",
                TOKENLAVKA_SECRET_FILE=hub / "tokenlavka.json",
            ):
                atomic_write_bytes(hub_paths.HUB_CONFIG_FILE, b'{"setting":true}')
                hub_paths.migrate_legacy_locations()
                self.assertEqual(
                    json.loads(hub_paths.OPENCODE_SHARED_ANTIGRAVITY_CONFIG.read_text(encoding="utf-8")),
                    {"setting": True, "auto_update": False},
                )
                self.assertEqual(list(hub.iterdir()), [hub_paths.HUB_CONFIG_FILE])
            for path in legacy_files:
                self.assertEqual(path.read_bytes(), b'{"apiKey":"legacy-sample"}')

    def test_unavailable_copy_is_not_treated_as_absent(self):
        with TemporaryDirectory() as root:
            central, mirror = Path(root) / "central.json", Path(root) / "mirror.json"
            atomic_write_bytes(central, b'{"old":true}')
            atomic_write_bytes(mirror, b'{"new":true}')
            file_stat = hub_paths.regular_file_stat

            def restricted(path):
                if path == mirror:
                    raise PermissionError("unavailable")
                return file_stat(path)

            with patch.multiple(hub_paths, HUB_CONFIG_FILE=central,
                                OPENCODE_SHARED_ANTIGRAVITY_CONFIG=mirror), patch.object(
                hub_paths, "regular_file_stat", side_effect=restricted,
            ), patch.object(hub_paths, "atomic_write_bytes") as write:
                self.assertEqual(hub_paths.read_mirrored_antigravity_config(), {"old": True})
                hub_paths.sync_shared_antigravity_config()
                write.assert_not_called()

    @unittest.skipIf(os.name == "nt", "POSIX mode")
    def test_write_private_file_without_changing_existing_parent_permissions(self):
        with TemporaryDirectory() as root:
            directory = Path(root) / "shared"
            directory.mkdir()
            directory.chmod(0o755)
            target = directory / "config.json"
            atomic_write_bytes(target, b"{}", private_parent=False)
            self.assertEqual(target.stat().st_mode & 0o777, 0o600)
            self.assertEqual(directory.stat().st_mode & 0o777, 0o755)

    def test_ensure_auto_update_disabled_handles_empty_json_and_jsonc_comments(self):
        with TemporaryDirectory() as root:
            empty = Path(root) / "empty.json"
            empty.write_text("{}\n", encoding="utf-8")
            commented = Path(root) / "commented.jsonc"
            commented.write_text('{\n  // "auto_update": false\n  "auto_update": "true",\n  "k": 1,\n}\n', encoding="utf-8")
            res = hub_paths.ensure_auto_update_disabled([empty, commented])
            self.assertTrue(res["ok"])
            self.assertEqual(json.loads(empty.read_text(encoding="utf-8")), {"auto_update": False})
            import jsonc_config
            parsed = jsonc_config.parse_config(commented.read_text(encoding="utf-8"), jsonc=True)
            self.assertIs(parsed["auto_update"], False)
            self.assertIn('// "auto_update": false', commented.read_text(encoding="utf-8"))

    def test_read_mirrored_antigravity_config_supports_jsonc_mirror(self):
        with TemporaryDirectory() as root:
            central, mirror = Path(root) / "central.json", Path(root) / "mirror.json"
            atomic_write_bytes(central, b'{"old":true}')
            atomic_write_bytes(mirror, b'{\n  // comment\n  "new": true,\n}\n')
            with patch.multiple(hub_paths, HUB_CONFIG_FILE=central,
                                OPENCODE_SHARED_ANTIGRAVITY_CONFIG=mirror):
                self.assertEqual(hub_paths.read_mirrored_antigravity_config(), {"new": True})
