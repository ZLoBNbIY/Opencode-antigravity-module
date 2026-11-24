from pathlib import Path
import importlib.util
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import Mock, patch

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

    def test_wait_for_windows_process_only_opens_a_synchronization_handle(self):
        kernel = Mock()
        kernel.OpenProcess.return_value = 10
        kernel.WaitForSingleObject.side_effect = [258, 0]
        with patch.object(hub_restart, "os", SimpleNamespace(name="nt", getpid=lambda: 1)), \
             patch("hub_restart.ctypes.WinDLL", return_value=kernel, create=True):
            self.assertFalse(hub_restart.wait_for_exit(123, timeout=0))
            self.assertTrue(hub_restart.wait_for_exit(123))
        kernel.OpenProcess.assert_called_with(0x00100000, False, 123)
        kernel.CloseHandle.assert_called_with(10)
        self.assertEqual(kernel.CloseHandle.call_count, 2)

    def test_windows_probe_only_treats_a_missing_process_as_exited(self):
        kernel = Mock()
        kernel.OpenProcess.return_value = None
        with patch.object(hub_restart, "os", SimpleNamespace(name="nt", getpid=lambda: 1)), \
             patch("hub_restart.ctypes.WinDLL", return_value=kernel, create=True), \
             patch("hub_restart.ctypes.get_last_error", side_effect=[5, 87], create=True):
            self.assertFalse(hub_restart.wait_for_exit(123))
            self.assertTrue(hub_restart.wait_for_exit(123))
        kernel.CloseHandle.assert_not_called()

    def test_posix_poll_never_sends_a_signal_and_fails_closed_on_denied_access(self):
        probe = Mock(side_effect=[None, PermissionError, ProcessLookupError])
        with patch.object(hub_restart, "os", SimpleNamespace(name="posix", getpid=lambda: 1, kill=probe)):
            self.assertFalse(hub_restart.wait_for_exit(123, timeout=0))
            self.assertFalse(hub_restart.wait_for_exit(123))
            self.assertTrue(hub_restart.wait_for_exit(123))
        self.assertEqual(probe.call_count, 3)
        probe.assert_called_with(123, 0)

    @patch("hub_restart.subprocess.run")
    @patch("hub_restart.subprocess.Popen")
    def test_source_restart_aborts_on_timeout_without_kill_or_process_discovery(self, popen, run):
        with patch.object(hub_restart, "wait_for_exit", return_value=False) as wait:
            self.assertEqual(hub_restart.relaunch_source("123"), 1)
        wait.assert_called_once_with(123)
        popen.assert_not_called()
        run.assert_not_called()

    @patch("hub_restart.subprocess.Popen")
    def test_source_restart_uses_same_checkout_and_clean_environment(self, popen):
        script = Path(hub_restart.__file__).with_name("antigravity_manager.pyw")
        pythonw = Path(sys.executable).with_name("pythonw.exe")
        with patch.object(hub_restart, "wait_for_exit", return_value=True), \
             patch("proxy_config.opencode_launch_environment", return_value={"NO_PROXY": "example.test"}):
            self.assertEqual(hub_restart.relaunch_source("123"), 0)
        if hub_restart.os.name == "nt":
            if pythonw.is_file():
                popen.assert_called_once_with([str(pythonw), str(script)], cwd=str(script.parent),
                                              close_fds=True, env={"NO_PROXY": "example.test"})
            else:
                popen.assert_called_once_with([sys.executable, str(script)], cwd=str(script.parent),
                                              close_fds=True, env={"NO_PROXY": "example.test"},
                                              creationflags=getattr(hub_restart.subprocess, "CREATE_NO_WINDOW", 0))
        else:
            popen.assert_called_once_with([sys.executable, str(script)], cwd=str(script.parent),
                                          close_fds=True, env={"NO_PROXY": "example.test"})

    @patch("hub_restart.subprocess.Popen")
    def test_source_restart_uses_create_no_window_when_pythonw_missing(self, popen):
        script = Path(hub_restart.__file__).with_name("antigravity_manager.pyw")
        with patch.object(hub_restart, "wait_for_exit", return_value=True), \
             patch.object(hub_restart, "os", SimpleNamespace(name="nt")), \
             patch.object(Path, "is_file", return_value=False), \
             patch("proxy_config.opencode_launch_environment", return_value={"NO_PROXY": "example.test"}):
            self.assertEqual(hub_restart.relaunch_source("123"), 0)
        popen.assert_called_once_with(
            [sys.executable, str(script)],
            cwd=str(script.parent),
            close_fds=True,
            env={"NO_PROXY": "example.test"},
            creationflags=getattr(hub_restart.subprocess, "CREATE_NO_WINDOW", 0),
        )

    @patch("hub_restart.subprocess.Popen")
    def test_invalid_pid_does_not_launch(self, popen):
        for pid in ("not a pid", "0", "-1", "4294967296", str(hub_restart.os.getpid())):
            with self.subTest(pid=pid):
                self.assertEqual(hub_restart.relaunch_source(pid), 1)
                self.assertEqual(hub_restart.relaunch_packaged(pid), 1)
        popen.assert_not_called()

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
