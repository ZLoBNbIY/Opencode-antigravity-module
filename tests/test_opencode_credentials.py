import json
import os
import sqlite3
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "gui-manager"))
import opencode_credentials


def _make_db(path, rows):
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE credential (id text PRIMARY KEY, integration_id text, value text, "
        "time_updated integer)"
    )
    for credential_id, integration_id, value, updated in rows:
        conn.execute("INSERT INTO credential VALUES (?, ?, ?, ?)",
                     (credential_id, integration_id, json.dumps(value), updated))
    conn.commit()
    conn.close()


class OpencodeCredentialsTests(unittest.TestCase):
    def setUp(self):
        opencode_credentials.invalidate()
        self.addCleanup(opencode_credentials.invalidate)

    def test_reads_the_newest_key_credential(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "opencode.db"
            _make_db(db, [
                ("cred_old", "deepseek", {"type": "key", "key": "sk-old-0000000001"}, 1000),
                ("cred_new", "deepseek-account", {"type": "key", "key": "sk-new-0000000002"}, 5000),
                # OAuth rows never carry an API key and must be ignored.
                ("cred_oauth", "deepseek", {"type": "oauth", "access": "token"}, 9000),
            ])
            with patch.object(opencode_credentials, "database_path", return_value=db):
                key, updated = opencode_credentials.read_key(("deepseek", "deepseek-account"))
            self.assertEqual(key, "sk-new-0000000002")
            self.assertEqual(updated, 5000)

    def test_credential_id_exposes_the_existing_row(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "opencode.db"
            _make_db(db, [("cred_abc", "deepseek", {"type": "key", "key": "sk-key-0000000003"}, 7)])
            with patch.object(opencode_credentials, "database_path", return_value=db):
                self.assertTrue(opencode_credentials.has_credential("deepseek"))
                self.assertEqual(opencode_credentials.credential_id("deepseek"), "cred_abc")
                self.assertFalse(opencode_credentials.has_credential("tokenlavka"))

    def test_key_in_opencode_config_is_read_with_file_time(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "opencode.json"
            path.write_text(json.dumps({
                "provider": {"deepseek": {"options": {"apiKey": "sk-config-0000000004"}}}
            }), encoding="utf-8")
            key, updated = opencode_credentials.read_config_key(path, "deepseek")
            self.assertEqual(key, "sk-config-0000000004")
            self.assertEqual(updated, int(path.stat().st_mtime_ns // 1_000_000))

    def test_newest_source_wins_between_db_and_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "opencode.db"
            _make_db(db, [("cred_db", "deepseek", {"type": "key", "key": "sk-db-0000000005"}, 1000)])
            path = Path(tmp) / "opencode.json"
            path.write_text(json.dumps({
                "provider": {"deepseek": {"options": {"apiKey": "sk-config-0000000006"}}}
            }), encoding="utf-8")
            with patch.object(opencode_credentials, "database_path", return_value=db):
                key, _ = opencode_credentials.read_key(("deepseek",), path, "deepseek")
            self.assertEqual(key, "sk-config-0000000006")

    def test_placeholders_and_missing_files_are_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "opencode.json"
            path.write_text(json.dumps({
                "provider": {"deepseek": {"options": {"apiKey": "your-api-key"}}}
            }), encoding="utf-8")
            self.assertEqual(opencode_credentials.read_config_key(path, "deepseek"), ("", 0))
            self.assertEqual(opencode_credentials.read_config_key(Path(tmp) / "missing.json", "deepseek"),
                             ("", 0))
            with patch.object(opencode_credentials, "database_path", return_value=None):
                self.assertEqual(opencode_credentials.read_key(("deepseek",)), ("", 0))
                self.assertFalse(opencode_credentials.has_credential("deepseek"))
                self.assertEqual(opencode_credentials.credential_id("deepseek"), "")


class DatabaseLocationTests(unittest.TestCase):
    def test_xdg_data_home_is_used_when_present(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "opencode" / "opencode.db"
            db.parent.mkdir(parents=True)
            db.write_bytes(b"")
            with patch.dict(os.environ, {"XDG_DATA_HOME": tmp, "OPENCODE_DATA_DIR": ""}, clear=False):
                self.assertEqual(opencode_credentials.database_path(), db)


if __name__ == "__main__":
    unittest.main()
