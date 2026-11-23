from pathlib import Path
import sys
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "gui-manager"))
import win_tray


class WindowsTrayTests(unittest.TestCase):
    def setUp(self):
        self.user = Mock()
        self.shell = Mock()
        self.user.LoadImageW.return_value = 10
        self.user.CreateWindowExW.return_value = 20
        self.kernel = Mock()
        self.kernel.GetModuleHandleW.return_value = 30
        self.message_loop_exit = threading.Event()
        self.user.GetMessageW.side_effect = lambda *_: self.message_loop_exit.wait(timeout=3) and 0
        self.user.PostMessageW.side_effect = lambda *_: self.message_loop_exit.set()
        self.enterContext(patch.object(win_tray, "sys", SimpleNamespace(platform="win32")))
        self.enterContext(patch.object(win_tray.ctypes, "windll", SimpleNamespace(
            user32=self.user, kernel32=self.kernel, shell32=self.shell,
        ), create=True))
        self.tray = win_tray.WindowsTrayIcon(icon_path="icon.ico")
        self.addCleanup(self.cleanup_tray)

    def cleanup_tray(self):
        self.tray.remove()
        self.message_loop_exit.set()
        if self.tray._thread is not None:
            self.tray._thread.join(timeout=3)

    def test_reports_success_after_icon_is_added_and_reuses_live_tray(self):
        self.shell.Shell_NotifyIconW.return_value = True
        self.assertTrue(self.tray.start())
        self.assertTrue(self.tray.start())
        self.assertTrue(self.tray.is_visible)
        self.shell.Shell_NotifyIconW.assert_called_once()
        self.assertEqual(self.shell.Shell_NotifyIconW.call_args.args[0], win_tray.NIM_ADD)
        self.cleanup_tray()
        self.assertFalse(self.tray.is_visible)
        self.assertFalse(self.tray.start())
        self.assertEqual(self.shell.Shell_NotifyIconW.call_args.args[0], win_tray.NIM_DELETE)
        self.user.DestroyWindow.assert_called_once_with(20)
        self.user.DestroyIcon.assert_called_once_with(10)

    def test_rejected_icon_is_not_ready_and_window_is_destroyed(self):
        self.shell.Shell_NotifyIconW.return_value = False
        self.assertFalse(self.tray.start())
        self.assertFalse(self.tray.is_visible)
        self.shell.Shell_NotifyIconW.assert_called_once()
        self.user.DestroyWindow.assert_called_once_with(20)
        self.user.UnregisterClassW.assert_called_once()
        self.user.DestroyIcon.assert_called_once_with(10)
        self.user.GetMessageW.assert_not_called()

    def test_create_window_failure_is_not_ready(self):
        self.user.CreateWindowExW.return_value = 0
        self.assertFalse(self.tray.start())
        self.user.UnregisterClassW.assert_called_once()
        self.shell.Shell_NotifyIconW.assert_not_called()

    def test_class_registration_failure_is_not_ready(self):
        self.user.RegisterClassExW.return_value = 0
        self.assertFalse(self.tray.start())
        self.user.DestroyIcon.assert_called_once_with(10)
        self.user.UnregisterClassW.assert_not_called()
        self.user.CreateWindowExW.assert_not_called()

    def test_late_icon_after_start_timeout_is_removed_without_entering_message_loop(self):
        adding = threading.Event()
        release = threading.Event()

        def notify(action, _):
            if action == win_tray.NIM_ADD:
                adding.set()
                return release.wait(timeout=3)
            return True

        def startup_wait(*, timeout):
            self.assertTrue(adding.wait(timeout=timeout))
            return False

        self.shell.Shell_NotifyIconW.side_effect = notify
        with patch.object(self.tray._startup_done, "wait", side_effect=startup_wait):
            try:
                self.assertFalse(self.tray.start())
            finally:
                release.set()
        self.tray._thread.join(timeout=3)
        self.assertFalse(self.tray.is_visible)
        actions = [call.args[0] for call in self.shell.Shell_NotifyIconW.call_args_list]
        self.assertEqual(actions, [win_tray.NIM_ADD, win_tray.NIM_DELETE])
        self.user.GetMessageW.assert_not_called()

    def test_unsupported_platform_is_not_ready(self):
        with patch.object(win_tray, "sys", SimpleNamespace(platform="linux")):
            self.assertFalse(self.tray.start())
        self.user.LoadImageW.assert_not_called()
