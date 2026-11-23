import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "gui-manager"))
import auto_updater


class AutoUpdaterTests(unittest.TestCase):
    def test_remote_ancestor_does_not_show_update_for_local_ahead_commit(self):
        with patch.object(auto_updater, "_git_commit_contains", return_value=True):
            self.assertFalse(auto_updater._has_newer_remote_commit(Path("."), "local", "remote"))

    def test_equal_or_missing_sha_does_not_show_update(self):
        with patch.object(auto_updater, "_git_commit_contains") as contains:
            self.assertFalse(auto_updater._has_newer_remote_commit(Path("."), "same", "same"))
            self.assertFalse(auto_updater._has_newer_remote_commit(Path("."), "", "remote"))
            contains.assert_not_called()

    def test_remote_not_contained_locally_shows_update(self):
        with patch.object(auto_updater, "_git_commit_contains", return_value=False):
            self.assertTrue(auto_updater._has_newer_remote_commit(Path("."), "local", "remote"))

    def test_commit_contains_uses_git_ancestry(self):
        result = subprocess.CompletedProcess(["git"], 0, "", "")
        with patch.object(auto_updater.subprocess, "run", return_value=result) as run:
            self.assertTrue(auto_updater._git_commit_contains(Path("repo"), "remote-sha"))
        command = run.call_args.args[0]
        self.assertIn("--no-replace-objects", command)
        self.assertEqual(command[-4:], ["merge-base", "--is-ancestor", "remote-sha", "HEAD"])

    def test_fetch_failure_stops_before_merge(self):
        with patch.object(auto_updater, "_clean_v2_head", return_value="a" * 40), \
             patch.object(auto_updater, "_upstream_sha", return_value="b" * 40), \
             patch.object(auto_updater, "_git_output", side_effect=RuntimeError("fetch failed")) as git:
            ok, msg = auto_updater.apply_update_git(Path("repo"))
        self.assertFalse(ok)
        self.assertIn("fetch failed", msg)
        git.assert_called_once()
        self.assertEqual(git.call_args.args[1], "fetch")

    def test_changed_remote_commit_requires_new_confirmation(self):
        with patch.object(auto_updater, "_clean_v2_head", return_value="a" * 40), \
             patch.object(auto_updater, "_upstream_sha", return_value="b" * 40), \
             patch.object(auto_updater, "_git_output") as git:
            ok, _ = auto_updater.apply_update_git(Path("repo"), expected_commit="c" * 40)
        self.assertFalse(ok)
        git.assert_not_called()


if __name__ == "__main__":
    unittest.main()
