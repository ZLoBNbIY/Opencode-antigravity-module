import json
import sqlite3
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "gui-manager"))
import opencode_usage


def _ms(value: datetime) -> int:
    return int(value.timestamp() * 1000)


class OpenCodeUsageTests(unittest.TestCase):
    def setUp(self):
        opencode_usage._cache.clear()
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "opencode.db"
        self.patch = patch.object(opencode_usage, "DB_PATH", self.db_path)
        self.patch.start()
        self.addCleanup(self._cleanup)
        self.now = datetime(2026, 11, 17, 12, 0, 0)

    def _cleanup(self):
        self.patch.stop()
        self.tmp.cleanup()
        opencode_usage._cache.clear()

    def _create_db(self):
        con = sqlite3.connect(self.db_path)
        con.executescript(
            """
            create table session_v2 (
                id text primary key, model text, cost real,
                tokens_input integer, tokens_output integer, tokens_reasoning integer,
                tokens_cache_read integer, time_created integer, time_updated integer
            );
            create table session_message (
                id text, session_id text, type text, time_created integer, data text
            );
            """
        )
        deepseek_model = json.dumps({"id": "deepseek-flash", "providerID": "deepseek"})
        team = json.dumps({"id": "deepseek-chat", "providerID": "deepseek"})
        google_model = json.dumps({"id": "antigravity", "providerID": "google"})
        day1 = datetime(2026, 11, 16, 10, 0, 0)
        day2 = datetime(2026, 11, 17, 9, 0, 0)
        con.execute(
            "insert into session_v2 values (?,?,?,?,?,?,?,?,?)",
            ("ses_a", deepseek_model, 0.1, 100, 10, 5, 1000, _ms(day1), _ms(day1)),
        )
        con.execute(
            "insert into session_v2 values (?,?,?,?,?,?,?,?,?)",
            ("ses_b", team, 0.2, 200, 20, 0, 0, _ms(day2), _ms(day2)),
        )
        con.execute(
            "insert into session_v2 values (?,?,?,?,?,?,?,?,?)",
            ("ses_google", google_model, 0.9, 999, 99, 0, 0, _ms(day2), _ms(day2)),
        )
        messages = [
            ("m1", "ses_a", "assistant", day1, {
                "time": {"created": _ms(day1)}, "model": {"providerID": "deepseek"},
                "cost": 0.1, "tokens": {"input": 100, "output": 10, "reasoning": 5,
                                        "cache": {"read": 1000, "write": 0}},
            }),
            ("m2", "ses_a", "assistant", day1, {
                "time": {"created": _ms(day1)}, "model": {"providerID": "google"},
                "cost": 0.9, "tokens": {"input": 999, "output": 99},
            }),
            ("m3", "ses_b", "assistant", day2, {
                "time": {"created": _ms(day2)}, "model": {"providerID": "deepseek"},
                "cost": 0.2, "tokens": {"input": 200, "output": 20, "cache": {"read": 0}},
            }),
            ("m4", "ses_b", "user", day2, {"model": {"providerID": "deepseek"}}),
        ]
        for message_id, session_id, kind, when, payload in messages:
            con.execute("insert into session_message values (?,?,?,?,?)",
                        (message_id, session_id, kind, _ms(when), json.dumps(payload)))
        con.commit()
        con.close()

    def test_usage_is_aggregated_per_day_and_only_for_deepseek(self):
        self._create_db()
        result = opencode_usage.deepseek_usage(30, now=self.now)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["currency"], "USD")
        days = {item["date"]: item for item in result["days"]}
        self.assertEqual(days["2026-11-16"]["cost"], 0.1)
        self.assertEqual(days["2026-11-16"]["tokens_total"], 100 + 10 + 5 + 1000)
        self.assertEqual(days["2026-11-16"]["messages"], 1)
        self.assertEqual(days["2026-11-17"]["cost"], 0.2)
        self.assertEqual(days["2026-11-17"]["tokens_total"], 220)
        self.assertEqual(result["totals"]["cost"], 0.3)
        self.assertEqual(result["totals"]["tokens_total"], 1115 + 220)
        self.assertEqual(result["totals"]["messages"], 2)
        self.assertEqual(len(result["days"]), 30)
        self.assertEqual(result["days"][-1]["date"], "2026-11-17")

    def test_sessions_without_messages_fall_back_to_session_totals(self):
        self._create_db()
        con = sqlite3.connect(self.db_path)
        con.execute(
            "insert into session_v2 values (?,?,?,?,?,?,?,?,?)",
            ("ses_legacy", json.dumps({"providerID": "deepseek"}), 0.4, 400, 40, 0, 0,
             _ms(datetime(2026, 11, 15, 8, 0)), _ms(datetime(2026, 11, 17, 8, 0))),
        )
        con.commit()
        con.close()
        result = opencode_usage.deepseek_usage(30, now=self.now)
        days = {item["date"]: item for item in result["days"]}
        self.assertAlmostEqual(days["2026-11-17"]["cost"], 0.6)
        self.assertEqual(days["2026-11-17"]["tokens_total"], 220 + 440)

    def test_missing_database_is_reported_without_inventing_usage(self):
        result = opencode_usage.deepseek_usage(7, now=self.now)
        self.assertEqual(result["status"], "unavailable")
        self.assertIn("OpenCode", result["error"])
        self.assertEqual(result["totals"]["cost"], 0.0)
        self.assertEqual(result["totals"]["tokens_total"], 0)
        self.assertEqual(len(result["days"]), 7)

    def test_window_ignores_usage_outside_requested_days(self):
        self._create_db()
        result = opencode_usage.deepseek_usage(1, now=self.now)
        days = {item["date"]: item for item in result["days"]}
        self.assertEqual(list(days), ["2026-11-17"])
        self.assertEqual(days["2026-11-17"]["cost"], 0.2)

    def test_results_are_cached_for_a_short_time(self):
        self._create_db()
        first = opencode_usage.deepseek_usage(30, now=self.now)
        self.db_path.unlink()
        second = opencode_usage.deepseek_usage(30, now=self.now)
        self.assertEqual(first["totals"], second["totals"])


if __name__ == "__main__":
    unittest.main()
