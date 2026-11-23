import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "gui-manager"))
from google_proactive_refresh import GoogleProactiveRefresh, find_cli_3113


class FakeStop:
    def __init__(self):
        self.now = 0
        self.closed = False
        self.waits = []
        self.stop_at = float("inf")

    def is_set(self):
        return self.closed

    def wait(self, seconds):
        self.waits.append(seconds)
        self.now = min(self.stop_at, self.now + seconds)
        self.closed |= self.now >= self.stop_at
        return self.closed


class GoogleProactiveRefreshTests(unittest.TestCase):
    def setUp(self):
        self.stop = FakeStop()
        self.calls = []
        self.rows = []
        self.generation = "generation"
        self.reply = {}
        self.enabled = Mock(return_value=True)
        self.worker = GoogleProactiveRefresh(
            self.run_cli, self.stop, self.enabled, monotonic=lambda: self.stop.now, jitter=lambda: 2,
        )

    def run_cli(self, args, timeout):
        self.calls.append((self.stop.now, args))
        self.assertEqual(timeout, 45)
        if args == ["refresh-due", "--list"]:
            result = {"status": "ready", "generation": self.generation, "accounts": self.rows}
        else:
            self.assertEqual(args[:3], ["refresh-due", "--account", self.generation])
            result = self.reply.get(args[3], {"status": "refreshed"})
        if isinstance(result, Exception):
            raise result
        return SimpleNamespace(returncode=0, stdout=json.dumps(result), stderr="must not log")

    @staticmethod
    def row(id, epoch=1):
        return {"id": id, "epoch": epoch, "expires": 1720000000000}

    def attempts(self):
        return [(when, args[3]) for when, args in self.calls if args[1] == "--account"]

    def test_batch_deduplicates_and_spaces_sequential_cli_requests(self):
        self.rows = [self.row("one"), self.row("one"), self.row("two"),
                     self.row("--fake"), self.row("malformed", epoch=True), None]
        self.worker.check()
        self.assertEqual(self.attempts(), [(0, "one"), (14, "two")])
        self.assertEqual(self.stop.waits, [14])

    def test_invalid_grant_waits_for_reauthentication_or_new_generation(self):
        self.rows = [self.row("revoked"), self.row("good")]
        self.reply["revoked"] = {"status": "invalid_grant"}
        self.worker.check()
        self.rows = [self.row("revoked")]
        self.stop.now = 900
        self.worker.check()
        self.assertEqual(self.attempts(), [(0, "revoked"), (14, "good")])
        self.rows = [self.row("revoked", epoch=2)]
        self.stop.now = 1200
        self.worker.check()
        self.generation = "new-generation"
        self.stop.now = 1500
        self.worker.check()
        self.assertEqual(self.attempts()[-2:], [(1200, "revoked"), (1500, "revoked")])

    def test_429_stops_batch_and_honors_retry_after_globally(self):
        self.rows = [self.row("first"), self.row("second")]
        self.reply["first"] = {"status": "rate_limited", "retryAfterSeconds": 660}
        self.worker.check()
        self.assertEqual(len(self.calls), 2)
        for now in (300, 600, 659):
            self.stop.now = now
            self.worker.check()
        self.assertEqual(len(self.calls), 2)
        self.stop.now = 660
        self.reply.clear()
        self.worker.check()
        self.assertEqual(self.attempts(), [(0, "first"), (660, "first"), (674, "second")])

    def test_429_without_retry_after_backs_off_fifteen_minutes(self):
        self.rows = [self.row("first")]
        self.reply["first"] = {"status": "rate_limited"}
        self.worker.check()
        self.stop.now = 899
        self.worker.check()
        self.assertEqual(len(self.calls), 2)
        self.stop.now = 900
        self.worker.check()
        self.assertEqual(self.attempts(), [(0, "first"), (900, "first")])

    def test_transient_errors_are_sanitized_and_back_off_that_row(self):
        self.rows = [self.row("bad"), self.row("good")]
        self.reply["bad"] = RuntimeError("private child output")
        self.worker.check()
        self.rows = [self.row("bad")]
        self.stop.now = 899
        self.worker.check()
        self.stop.now = 900
        self.worker.check()
        self.assertEqual(self.attempts(), [(0, "bad"), (14, "good"), (900, "bad")])

    def test_five_minute_lifecycle_and_opt_out(self):
        self.stop.stop_at = 1201
        self.enabled.side_effect = lambda: self.stop.now != 900
        self.worker.run()
        self.assertEqual(self.calls, [(now, ["refresh-due", "--list"]) for now in (300, 600, 1200)])
        self.assertTrue(self.stop.is_set())

    def test_stop_interrupts_pacing_without_starting_next_subprocess(self):
        self.rows = [self.row("one"), self.row("two")]
        self.stop.stop_at = 5
        self.worker.check()
        self.assertEqual(self.attempts(), [(0, "one")])

    def test_only_one_exact_cache_layout_is_accepted(self):
        with tempfile.TemporaryDirectory() as root:
            cache = Path(root)
            def add(version, install):
                cli = (cache / f"@cortexkit/opencode-antigravity-auth@{version}" / install / "node_modules" /
                       "@cortexkit" / "opencode-antigravity-auth" / "dist" / "cli.js")
                cli.parent.mkdir(parents=True)
                cli.touch()
                return cli

            add("3.1.14", "1")
            self.assertIsNone(find_cli_3113(cache))
            expected = add("3.1.13", "1")
            self.assertEqual(find_cli_3113(cache), expected)
            add("3.1.13", "2")
            self.assertIsNone(find_cli_3113(cache))


if __name__ == "__main__":
    unittest.main()
