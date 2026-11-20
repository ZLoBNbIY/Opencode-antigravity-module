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
    def test_sync_preserves_newer_valid_mirror_and_skips_invalid_json(self):
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
                self.assertEqual(mirror.read_bytes(), b'{"new":true}')

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
