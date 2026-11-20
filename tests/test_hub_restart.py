from pathlib import Path
import importlib.util
import subprocess
import sys
from types import ModuleType
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "gui-manager"))
import hub_restart


class HubRestartTests(unittest.TestCase):
    @patch("hub_restart.subprocess.Popen")
    def test_old_hub_can_import_new_restart_helper(self, popen):
        spec = importlib.util.spec_from_file_location("updated_restart", hub_restart.__file__)
        helper = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {"proxy_config": ModuleType("proxy_config")}):
            spec.loader.exec_module(helper)
            helper.schedule_restart()
        self.assertEqual(Path(popen.call_args.args[0][1]), Path(hub_restart.__file__))

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

    @patch("hub_restart.subprocess.Popen")
    def test_fresh_packaged_helper_drops_only_hub_proxy(self, popen):
        with patch.object(hub_restart, "wait_for_exit", return_value=True), \
             patch.dict("os.environ", {"HTTPS_PROXY": "http://127.0.0.1:10880",
                                       "NO_PROXY": "example.test"}, clear=True):
            self.assertEqual(hub_restart.relaunch_packaged("123"), 0)
        self.assertEqual(popen.call_args.kwargs["env"], {
            "NO_PROXY": "example.test", "PYINSTALLER_RESET_ENVIRONMENT": "1",
        })
