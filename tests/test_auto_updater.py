import subprocess
import sys
import tempfile
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

    def test_run_git_disables_filemode_noise(self):
        result = subprocess.CompletedProcess(["git"], 0, "", "")
        with patch.object(auto_updater.subprocess, "run", return_value=result) as run:
            auto_updater._run_git(Path("repo"), "status")
        command = run.call_args.args[0]
        self.assertIn("core.filemode=false", command)

    def test_dirty_worktree_error_lists_offending_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            subprocess.run(["git", "init", "-b", auto_updater.BRANCH], cwd=repo, check=True, capture_output=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True, capture_output=True)
            subprocess.run(["git", "config", "user.name", "Tester"], cwd=repo, check=True, capture_output=True)
            (repo / "tracked.txt").write_text("base\n", encoding="utf-8")
            subprocess.run(["git", "add", "tracked.txt"], cwd=repo, check=True, capture_output=True)
            subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True)
            for i in range(7):
                (repo / f"file_{i}.txt").write_text("dirty\n", encoding="utf-8")
            with self.assertRaises(RuntimeError) as ctx:
                auto_updater._clean_v2_head(repo)
        message = str(ctx.exception)
        self.assertIn("?? file_0.txt", message)
        self.assertIn("?? file_4.txt", message)
        self.assertIn("и ещё 2", message)
        self.assertNotIn("file_5.txt", message)

    def test_repo_gitignore_ignores_hub_backup_and_lock_artifacts(self):
        repo_root = Path(__file__).resolve().parent.parent
        ignored_samples = [
            "plugin/dist/server.js.hub-route.bak",
            "plugin/dist/server.js.hub-route.bak.json",
            "plugin/dist/server.js.hub-quota-breaker.bak",
            "plugin/dist/server.js.hub-cloaking.bak",
            "plugin/dist/server.js.hub-gemini4.bak",
            ".hub-plugin-patch-state.json",
            "package-lock.json",
            "bun.lock",
            "bun.lockb",
            ".version",
            "opencode.sha256",
        ]
        result = subprocess.run(
            ["git", "check-ignore", "--", *ignored_samples],
            cwd=repo_root,
            text=True,
            capture_output=True,
            check=True,
        )
        ignored = set(result.stdout.splitlines())
        for sample in ignored_samples:
            self.assertIn(sample, ignored)


if __name__ == "__main__":
    unittest.main()
