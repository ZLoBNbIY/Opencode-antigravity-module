from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "gui-manager"))
import hub_restart


class HubRestartTests(unittest.TestCase):
    @patch("hub_restart.subprocess.Popen")
    def test_restart_uses_current_python_and_parent_pid(self, popen):
        hub_restart.schedule_restart()
        args = popen.call_args.args[0]
        self.assertEqual(args[0], sys.executable)
        self.assertEqual(Path(args[1]).name, "hub_restart.py")
        self.assertEqual(args[2], str(hub_restart.os.getpid()))

    def test_wait_for_running_process_and_exit(self):
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(1)"])
        try:
            self.assertFalse(hub_restart.wait_for_exit(child.pid, timeout=0))
            self.assertTrue(hub_restart.wait_for_exit(child.pid, timeout=10))
        finally:
            child.wait(timeout=10)

    @patch("hub_restart.subprocess.Popen")
    def test_installed_restart_relaunches_exe_not_python_script(self, popen):
        with patch.object(sys, "frozen", True, create=True):
            hub_restart.schedule_restart()
        self.assertEqual(popen.call_args.args[0],
                         [sys.executable, "--restart-after", str(hub_restart.os.getpid())])
        self.assertEqual(popen.call_args.kwargs["env"]["PYINSTALLER_RESET_ENVIRONMENT"], "1")

    @patch("hub_restart.subprocess.Popen")
    def test_installed_restart_aborts_if_parent_does_not_exit(self, popen):
        with patch.object(hub_restart, "wait_for_exit", return_value=False) as wait:
            self.assertEqual(hub_restart.relaunch_packaged("123"), 1)
        wait.assert_called_once_with(123)
        popen.assert_not_called()
