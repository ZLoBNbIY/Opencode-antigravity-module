import io
import json
import sqlite3
from contextlib import closing, redirect_stdout
import subprocess
import sys
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "gui-manager"))
import openai_manager as manager


def account(account_id, email, access, expires_delta=3_600_000):
    return {
        "id": account_id,
        "accountId": account_id,
        "email": email,
        "name": email.split("@")[0],
        "access": access,
        "refresh": f"refresh-{account_id}",
        "expires": int(time.time() * 1000) + expires_delta,
        "is_active": False,
    }


class FakeOpenCodeCli:
    """Faithful subset of OpenCode 2.3.2 auth import/switch/logout semantics."""

    def __init__(self, database: Path):
        self.database = database
        self.calls = []
        self.noop_switch = False
        self.fail_command = None

    def __call__(self, args, **kwargs):
        self.calls.append((list(args), kwargs.get("input")))
        argv = list(args)[1:]
        if self.fail_command and argv[:len(self.fail_command)] == self.fail_command:
            raise subprocess.CalledProcessError(1, args)

        if argv[:2] == ["auth", "logout"]:
            credential_id = argv[3]
            with closing(sqlite3.connect(self.database)) as conn, conn:
                conn.execute(
                    "DELETE FROM credential WHERE id = ? AND integration_id = 'openai'",
                    (credential_id,),
                )
        elif argv[:2] == ["auth", "import"]:
            entries = json.loads(kwargs["input"])
            with closing(sqlite3.connect(self.database)) as conn, conn:
                existing = conn.execute(
                    "SELECT COUNT(*) FROM credential WHERE integration_id = 'openai'"
                ).fetchone()[0]
                for entry in entries:
                    already = conn.execute(
                        "SELECT 1 FROM credential WHERE id = ?", (entry["id"],)
                    ).fetchone()
                    if already:
                        continue  # OpenCode 2.3.2 skips an existing ID.
                    activate = 1 if not existing and entry.get("active") else 0
                    conn.execute(
                        "INSERT INTO credential "
                        "(id, integration_id, label, value, active, time_created, time_updated) "
                        "VALUES (?, 'openai', ?, ?, ?, ?, ?)",
                        (
                            entry["id"], entry.get("label", "ChatGPT OAuth"),
                            json.dumps(entry["value"]), activate, 0, 0,
                        ),
                    )
        elif argv[:2] == ["auth", "switch"]:
            credential_id = argv[3]
            if not self.noop_switch:
                with closing(sqlite3.connect(self.database)) as conn, conn:
                    conn.execute("UPDATE credential SET active = 0 WHERE integration_id = 'openai'")
                    conn.execute("UPDATE credential SET active = 1 WHERE id = ?", (credential_id,))
        return Mock(returncode=0)

    def command(self, *prefix):
        return [call[0][1:] for call in self.calls if call[0][1:][:len(prefix)] == list(prefix)]


class OpenCodeCredentialSyncTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)
        self.db = self.root / "opencode.db"
        self.auth = self.root / "auth.json"
        self.pool = self.root / "openai-accounts.json"
        patches = patch.multiple(
            manager,
            CONFIG_DIR=self.root,
            OPENAI_ACCOUNTS_FILE=self.pool,
            AUTH_FILES=[self.auth],
            OPENCODE_DB_FILE=self.db,
        )
        patches.start()
        self.addCleanup(patches.stop)
        self.cli = FakeOpenCodeCli(self.db)
        cli_patch = patch.object(manager, "find_opencode_cli", return_value="opencode-cli.exe")
        run_patch = patch.object(manager.subprocess, "run", side_effect=self.cli)
        cli_patch.start()
        run_patch.start()
        self.addCleanup(run_patch.stop)
        self.addCleanup(cli_patch.stop)
        self._create_schema()

    def _create_schema(self):
        with closing(sqlite3.connect(self.db)) as conn, conn:
            conn.execute(
                "CREATE TABLE credential ("
                "id TEXT PRIMARY KEY, integration_id TEXT, label TEXT NOT NULL, "
                "value TEXT NOT NULL, active INTEGER, time_created INTEGER, time_updated INTEGER)"
            )

    def _insert_credential(self, credential_id, value, active=False, integration="openai"):
        with closing(sqlite3.connect(self.db)) as conn, conn:
            conn.execute(
                "INSERT INTO credential "
                "(id, integration_id, label, value, active, time_created, time_updated) "
                "VALUES (?, ?, ?, ?, ?, 0, 0)",
                (credential_id, integration, "ChatGPT", json.dumps(value), int(active)),
            )

    def _rows(self):
        with closing(sqlite3.connect(self.db)) as conn, conn:
            return conn.execute(
                "SELECT id, value, active FROM credential WHERE integration_id = 'openai'"
            ).fetchall()

    def test_switch_creates_distinct_credential_and_preserves_other_accounts(self):
        first = account("acc-a", "a@example.com", "access-a")
        second = account("acc-b", "b@example.com", "access-b")
        first_id = manager.get_openai_cred_id(first)
        second_id = manager.get_openai_cred_id(second)
        self.assertNotEqual(first_id, second_id)
        self.assertEqual(first_id, manager.get_openai_cred_id(dict(first)))
        self._insert_credential(first_id, manager._openai_credential_value(first), active=True)

        self.assertTrue(manager.sync_opencode_cli_openai(second))

        rows = {row[0]: (json.loads(row[1]), row[2]) for row in self._rows()}
        self.assertEqual(rows[first_id][1], 0)
        self.assertEqual(rows[first_id][0]["access"], "access-a")
        self.assertEqual(rows[second_id][0]["access"], "access-b")
        self.assertEqual(rows[second_id][1], 1)
        self.assertEqual(sum(row[2] for row in self._rows()), 1)
        self.assertEqual(self.cli.command("auth", "switch"), [["auth", "switch", "openai", second_id]])

    def test_changed_token_replaces_only_target_credential(self):
        first = account("acc-a", "a@example.com", "access-a")
        second = account("acc-b", "b@example.com", "old-access")
        first_id = manager.get_openai_cred_id(first)
        second_id = manager.get_openai_cred_id(second)
        self._insert_credential(first_id, manager._openai_credential_value(first))
        self._insert_credential(second_id, manager._openai_credential_value(second), active=True)

        updated = {**second, "access": "new-access", "refresh": "refresh-acc-b-2"}
        self.assertTrue(manager.sync_opencode_cli_openai(updated))

        rows = {row[0]: (json.loads(row[1]), row[2]) for row in self._rows()}
        self.assertEqual(rows[first_id][0]["access"], "access-a")
        self.assertEqual(rows[second_id][0]["access"], "new-access")
        self.assertEqual(rows[second_id][0]["refresh"], "refresh-acc-b-2")
        self.assertEqual(rows[second_id][1], 1)
        commands = [call[0][1:] for call in self.cli.calls]
        self.assertLess(
            commands.index(["auth", "logout", "openai", second_id]),
            commands.index(["auth", "import"]),
        )
        self.assertEqual(sum(row[2] for row in self._rows()), 1)

    def test_existing_credential_for_another_account_is_not_taken_over(self):
        first = account("acc-a", "a@example.com", "access-a")
        second = account("acc-b", "b@example.com", "access-b")
        second_id = manager.get_openai_cred_id(second)
        self._insert_credential(second_id, manager._openai_credential_value(first), active=True)

        self.assertFalse(manager.sync_opencode_cli_openai(second))
        self.assertEqual(self.cli.calls, [])
        rows = dict((row[0], json.loads(row[1])) for row in self._rows())
        self.assertEqual(rows[second_id]["access"], "access-a")

    def test_verification_failure_does_not_report_success(self):
        other = account("acc-a", "a@example.com", "access-a")
        target = account("acc-b", "b@example.com", "access-b")
        self._insert_credential(
            manager.get_openai_cred_id(other),
            manager._openai_credential_value(other),
            active=True,
        )
        self.cli.noop_switch = True
        self.assertFalse(manager.sync_opencode_cli_openai(target))
        rows = dict((row[0], json.loads(row[1])) for row in self._rows())
        credential_id = manager.get_openai_cred_id(target)
        self.assertNotIn(credential_id, rows)
        self.assertEqual(len(rows), 1)
        self.assertEqual(self._rows()[0][2], 1)

    def test_logout_removes_only_hub_managed_credentials(self):
        target = account("acc-b", "b@example.com", "access-b")
        managed_id = manager.get_openai_cred_id(target)
        other_id = "cred_opencode_unmanaged"
        self._insert_credential(managed_id, manager._openai_credential_value(target), active=True)
        self._insert_credential(other_id, {
            "type": "oauth", "methodID": "chatgpt-browser", "access": "other",
            "refresh": "other", "expires": 0, "metadata": {},
        })

        self.assertTrue(manager.sync_opencode_cli_openai(None))
        self.assertEqual({row[0] for row in self._rows()}, {other_id})

    def test_canonical_database_takes_precedence_over_legacy_auth_json(self):
        target = account("acc-b", "b@example.com", "access-b")
        credential_id = manager.get_openai_cred_id(target)
        self._insert_credential(credential_id, manager._openai_credential_value(target), active=True)
        self.auth.write_text(json.dumps({
            "openai": {"access": "stale-access", "refresh": "stale", "accountId": "stale"}
        }), encoding="utf-8")

        active = manager.get_active_auth_openai()
        self.assertEqual(active["access"], "access-b")
        self.assertEqual(active["accountId"], "acc-b")
        self.assertEqual(active["credentialId"], credential_id)

    def test_valid_empty_database_does_not_resurrect_legacy_token(self):
        self.auth.write_text(json.dumps({
            "openai": {"access": "stale-access", "refresh": "stale", "accountId": "stale"}
        }), encoding="utf-8")

        self.assertIsNone(manager.get_active_auth_openai())

    def test_unsupported_database_schema_fails_closed(self):
        self.db.unlink()
        with closing(sqlite3.connect(self.db)) as conn, conn:
            conn.execute("CREATE TABLE unrelated (value TEXT)")
        self.auth.write_text(json.dumps({
            "openai": {"access": "stale-access", "refresh": "stale", "accountId": "stale"}
        }), encoding="utf-8")

        self.assertIsNone(manager.get_active_auth_openai())

    def test_refresh_failure_does_not_log_tokens_or_email(self):
        target = account("acc-b", "private@example.com", "secret-access")
        target["refresh"] = "secret-refresh"
        opener = Mock()
        opener.open.side_effect = RuntimeError("secret-access secret-refresh")

        output = io.StringIO()
        with patch.object(manager, "_get_http_opener", return_value=opener), redirect_stdout(output):
            manager.refresh_openai_token(target)

        self.assertNotIn("secret-access", output.getvalue())
        self.assertNotIn("secret-refresh", output.getvalue())
        self.assertNotIn("private@example.com", output.getvalue())

    def test_set_active_commits_hub_state_only_after_opencode_acknowledgement(self):
        first = account("acc-a", "a@example.com", "access-a")
        second = account("acc-b", "b@example.com", "access-b")
        first["is_active"] = True
        calls = []
        with patch.object(manager, "load_openai_accounts", return_value=[first, second]), \
             patch.object(manager, "write_active_auth_openai",
                          side_effect=lambda acc: calls.append(("write", acc["id"])) or True), \
             patch.object(manager, "save_openai_accounts",
                          side_effect=lambda rows: calls.append(("save", [r["id"] for r in rows])) or True):
            self.assertTrue(manager.set_active_openai_account("acc-b"))

        self.assertEqual([name for name, _value in calls], ["write", "save"])
        self.assertEqual(calls[0][1], "acc-b")
        self.assertTrue(second["is_active"])
        self.assertFalse(first["is_active"])

    def test_set_active_rolls_back_server_on_hub_save_failure(self):
        first = account("acc-a", "a@example.com", "access-a")
        second = account("acc-b", "b@example.com", "access-b")
        first["is_active"] = True
        writes = []
        with patch.object(manager, "load_openai_accounts", return_value=[first, second]), \
             patch.object(manager, "write_active_auth_openai",
                          side_effect=lambda acc: writes.append(acc["id"]) or True), \
             patch.object(manager, "save_openai_accounts", return_value=False):
            self.assertFalse(manager.set_active_openai_account("acc-b"))

        self.assertEqual(writes, ["acc-b", "acc-a"])

    def test_unreadable_database_is_not_reported_as_success(self):
        target = account("acc-b", "b@example.com", "access-b")
        with patch.object(manager, "_read_opencode_credential_rows", return_value=None):
            self.assertFalse(manager.sync_opencode_cli_openai(target))
            self.assertFalse(manager.sync_opencode_db_openai(None))
            self.assertFalse(manager.remove_opencode_credentials_openai(target))
        self.assertEqual(self.cli.calls, [])

    def test_credential_id_collision_with_another_integration_is_rejected(self):
        target = account("acc-b", "b@example.com", "access-b")
        credential_id = manager.get_openai_cred_id(target)
        self._insert_credential(credential_id, manager._openai_credential_value(target), integration="google")

        self.assertFalse(manager.sync_opencode_cli_openai(target))
        self.assertEqual(self.cli.calls, [])
        with closing(sqlite3.connect(self.db)) as conn:
            integration = conn.execute(
                "SELECT integration_id FROM credential WHERE id = ?", (credential_id,)
            ).fetchone()[0]
        self.assertEqual(integration, "google")

    def test_import_does_not_commit_active_flag_before_opencode_acknowledgement(self):
        first = account("acc-a", "a@example.com", "access-a")
        second = account("acc-b", "b@example.com", "access-b")
        first["is_active"] = True
        calls = []
        with patch.object(manager, "load_openai_accounts", return_value=[first]), \
             patch.object(manager, "refresh_openai_token", return_value=(True, second)), \
             patch.object(manager, "write_active_auth_openai",
                          side_effect=lambda acc: calls.append(("write", acc["id"])) or True), \
             patch.object(manager, "save_openai_accounts",
                          side_effect=lambda rows: calls.append(("save", {r["id"]: r["is_active"] for r in rows})) or True):
            count = manager.import_openai_accounts([{**second, "is_active": True}])

        self.assertEqual(count, 1)
        self.assertEqual([name for name, _value in calls], ["save", "write", "save"])
        self.assertFalse(calls[0][1]["acc-b"])
        self.assertEqual(calls[1], ("write", "acc-b"))
        self.assertTrue(calls[2][1]["acc-b"])


if __name__ == "__main__":
    unittest.main()
