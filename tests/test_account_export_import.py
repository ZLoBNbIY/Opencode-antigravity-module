import json
import math
import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "gui-manager"))

import antigravity_manager
import openai_manager


class AccountExportImportTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.config_dir = Path(self.temp_dir.name)
        self.patch_home = patch.object(Path, "home", return_value=self.config_dir.parent)
        self.patch_expanduser = patch("os.path.expanduser", lambda p: str(self.config_dir) if "~/.config/opencode" in p else p)
        self.patch_home.start()
        self.patch_expanduser.start()

    def tearDown(self):
        self.patch_expanduser.stop()
        self.patch_home.stop()
        self.temp_dir.cleanup()

    def test_google_import_into_generation_store(self):
        # Create a mock generation store directory
        gen_dir = self.config_dir / "antigravity-accounts.json.store.11111111-2222-3333-4444-555555555555.generation"
        gen_dir.mkdir(parents=True)
        pointer_file = self.config_dir / "antigravity-accounts.json.store.pointer.json"
        pointer_file.write_text(json.dumps({
            "schemaVersion": 1,
            "id": "11111111-2222-3333-4444-555555555555",
            "directoryBasename": gen_dir.name
        }))

        initial_cfg = {
            "version": 1,
            "accounts": [],
            "commonAuthPool": {"schemaVersion": 1, "rows": {}},
            "antigravityRouting": {"schemaVersion": 1, "activeIndex": 0}
        }
        initial_state = {
            "version": 1,
            "accounts": {}
        }
        (gen_dir / "config.json").write_text(json.dumps(initial_cfg))
        (gen_dir / "state.json").write_text(json.dumps(initial_state))

        # Create an obsolete legacy file to test cleanup
        legacy_file = self.config_dir / "antigravity-accounts.json"
        legacy_file.write_text("{}")

        imported_accs = [
            {
                "id": "acc-1",
                "email": "user1@example.com",
                "refreshToken": "refresh-token-1",
                "accessToken": "access-token-1",
                "expires": int(time.time() * 1000) + 3600000,
                "projectId": "test-project-1",
                "label": "User One"
            },
            {
                "id": "acc-2",
                "email": "user2@example.com",
                "refreshToken": "refresh-token-2",
                "projectId": "test-project-2",
            }
        ]

        count = antigravity_manager.import_google_accounts(imported_accs)
        self.assertEqual(count, 2)

        # 1. Verify legacy file was removed so OpenCode won't fail with 'legacy source was recreated'
        self.assertFalse(legacy_file.exists())

        # 2. Verify config.json structure
        saved_cfg = json.loads((gen_dir / "config.json").read_text())
        self.assertEqual(len(saved_cfg["accounts"]), 2)
        self.assertEqual(saved_cfg["accounts"][0]["id"], "acc-1")
        self.assertEqual(saved_cfg["accounts"][1]["id"], "acc-2")

        # Ensure commonAuthPool rows conform to generation schema
        pool_rows = saved_cfg["commonAuthPool"]["rows"]
        self.assertIn("acc-1", pool_rows)
        self.assertIn("acc-2", pool_rows)
        self.assertEqual(pool_rows["acc-1"]["credentialEpoch"], 1)
        self.assertFalse(pool_rows["acc-1"]["needsFirstReading"])
        self.assertNotIn("candidate", pool_rows["acc-1"])

        # Ensure routing points to the first account
        routing = saved_cfg["antigravityRouting"]
        self.assertEqual(routing["activeIndex"], 0)
        self.assertEqual(routing["activeRow"]["id"], "acc-1")
        self.assertEqual(routing["activeRowByFamily"]["claude"]["id"], "acc-1")
        self.assertEqual(routing["activeRowByFamily"]["gemini"]["id"], "acc-1")

        # 3. Verify state.json structure
        saved_state = json.loads((gen_dir / "state.json").read_text())
        st1 = saved_state["accounts"]["acc-1"]
        self.assertEqual(st1["refresh"], "refresh-token-1")
        self.assertEqual(st1["access"], "access-token-1")
        self.assertEqual(st1["commonAuthProviderState"]["metadata"]["email"], "user1@example.com")

        # Verify credential digest and dispatch stamp calculation
        stamp1 = st1["commonAuthPool"]
        self.assertEqual(stamp1["credentialEpoch"], 1)
        expected_digest = antigravity_manager.compute_google_credential_digest("refresh-token-1")
        self.assertEqual(stamp1["digest"], expected_digest)
        self.assertTrue(len(stamp1["dispatch"]) > 0)

        # 4. Verify re-importing updates the account instead of failing or duplicating
        updated_accs = [
            {
                "email": "user1@example.com",
                "refreshToken": "refresh-token-1-updated",
                "accessToken": "access-token-1-updated",
            }
        ]
        count2 = antigravity_manager.import_google_accounts(updated_accs)
        self.assertEqual(count2, 1)

        saved_state2 = json.loads((gen_dir / "state.json").read_text())
        st1_updated = saved_state2["accounts"]["acc-1"]
        self.assertEqual(st1_updated["refresh"], "refresh-token-1-updated")
        self.assertEqual(st1_updated["access"], "access-token-1-updated")
        self.assertEqual(len(saved_state2["accounts"]), 2)

    def test_openai_import_merges_and_refreshes_tokens(self):
        openai_manager.CONFIG_DIR = self.config_dir
        openai_manager.OPENAI_ACCOUNTS_FILE = self.config_dir / "openai-accounts.json"
        openai_manager.AUTH_FILES = [self.config_dir / "auth.json"]
        openai_manager.OPENCODE_DB_FILE = self.config_dir / "opencode.db"

        # Mock token refresh
        refresh_mock = MagicMock(side_effect=lambda acc: (True, acc.update({
            "access": "refreshed-access-token",
            "expires": int(time.time() * 1000) + 86400000
        })))

        with patch("openai_manager.refresh_openai_token", refresh_mock), \
             patch("openai_manager.sync_opencode_cli_openai"):

            raw_import = [
                {
                    "id": "openai-1",
                    "accountId": "openai-1",
                    "email": "chatgpt_user@example.com",
                    "name": "ChatGPT User",
                    "access": "expired-access-token",
                    "refresh": "refresh-token-openai",
                    "expires": int(time.time() * 1000) - 10000, # expired
                    "is_active": True
                }
            ]

            imported_count = openai_manager.import_openai_accounts(raw_import)
            self.assertEqual(imported_count, 1)
            refresh_mock.assert_called_once()

            loaded = openai_manager.load_openai_accounts()
            self.assertEqual(len(loaded), 1)
            self.assertEqual(loaded[0]["email"], "chatgpt_user@example.com")
            self.assertEqual(loaded[0]["access"], "refreshed-access-token")
            self.assertTrue(loaded[0]["is_active"])

            # Verify auth.json was written
            auth_data = json.loads((self.config_dir / "auth.json").read_text())
            self.assertEqual(auth_data["openai"]["access"], "refreshed-access-token")
            self.assertEqual(auth_data["openai"]["refresh"], "refresh-token-openai")


if __name__ == "__main__":
    unittest.main()
