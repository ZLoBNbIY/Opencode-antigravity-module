"""Tests for closing OpenCode windows the Hub did not start itself."""
import importlib.util
import os
import sys
import unittest
from importlib.machinery import SourceFileLoader
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_loader(
    "antigravity_manager_restart",
    SourceFileLoader("antigravity_manager_restart",
                     str(ROOT / "gui-manager" / "antigravity_manager.pyw")),
)
manager = importlib.util.module_from_spec(spec)
spec.loader.exec_module(manager)


def tasklist(*pids):
    rows = "".join(f'"OpenCode.exe","{pid}","Console","1","1 000 K"\r\n' for pid in pids)
    return SimpleNamespace(returncode=0, stdout=rows, stderr="")


class OpenCodeDesktopTerminationTests(unittest.TestCase):
    def test_lists_only_opencode_pids_and_skips_self(self):
        output = SimpleNamespace(returncode=0, stdout=(
            '"OpenCode.exe","123","Console","1","1 K"\r\n'
            f'"OpenCode.exe","{os.getpid()}","Console","1","1 K"\r\n'
            '"explorer.exe","999","Console","1","1 K"\r\n'), stderr="")
        with patch.object(manager, "run_silent_cmd", return_value=output):
            self.assertEqual(manager._list_opencode_desktop_pids(), [123])

    def test_no_window_is_success_without_taskkill(self):
        calls = []
        with patch.object(manager, "run_silent_cmd", side_effect=lambda cmd, **kw: (
                calls.append(cmd) or tasklist())):
            result = manager.terminate_opencode_desktop()
        self.assertTrue(result["ok"])
        self.assertEqual(result["closed"], 0)
        self.assertFalse(any("taskkill" in call for call in calls))

    def test_kills_all_windows_and_waits_for_exit(self):
        responses = [tasklist(10, 11), tasklist(10, 11), tasklist()]
        calls = []
        with patch.object(manager, "run_silent_cmd", side_effect=lambda cmd, **kw: (
                calls.append(cmd) or responses.pop(0))), \
                patch.object(manager.time, "sleep"):
            result = manager.terminate_opencode_desktop()
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["closed"], 2)
        self.assertTrue(any("taskkill" in call for call in calls))

    def test_reports_failure_when_window_survives(self):
        with patch.object(manager, "run_silent_cmd", return_value=tasklist(10)), \
                patch.object(manager.time, "sleep"), \
                patch.object(manager.time, "monotonic", side_effect=[0, 0, 0, 11, 11, 11]):
            result = manager.terminate_opencode_desktop()
        self.assertFalse(result["ok"])
        self.assertIn("10", result["message"])


if __name__ == "__main__":
    unittest.main()
