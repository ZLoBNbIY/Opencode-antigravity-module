import ctypes
from importlib.machinery import SourceFileLoader
from importlib.util import module_from_spec, spec_from_loader
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch


class HubEntryTests(unittest.TestCase):
    def setUp(self):
        entry = Path(__file__).resolve().parents[1] / "gui-manager" / "antigravity_manager.pyw"
        loader = SourceFileLoader("hub_entry_under_test", str(entry))
        self.manager = module_from_spec(spec_from_loader(loader.name, loader))
        loader.exec_module(self.manager)
        self.kernel = Mock()
        self.enterContext(patch.object(self.manager, "sys", SimpleNamespace(platform="win32")))
        self.enterContext(patch.object(ctypes, "WinDLL", return_value=self.kernel, create=True))
        self.enterContext(patch.object(ctypes, "set_last_error", create=True))

    def test_first_acquire_keeps_the_handle_and_a_repeat_does_not_reopen_it(self):
        self.kernel.CreateMutexW.return_value = 0x123456789
        with patch.object(ctypes, "get_last_error", return_value=0, create=True):
            self.assertTrue(self.manager.acquire_single_instance())
            self.assertTrue(self.manager.acquire_single_instance())
        self.assertEqual(self.manager._SINGLE_INSTANCE_MUTEX, 0x123456789)
        self.kernel.CreateMutexW.assert_called_once_with(None, True, "Local\\AntigravityHub.SingleInstance")
        self.kernel.CloseHandle.assert_not_called()

    def test_duplicate_acquire_closes_the_returned_handle_and_exits(self):
        self.kernel.CreateMutexW.return_value = 0x123456789
        with patch.object(ctypes, "get_last_error", return_value=183, create=True):
            self.assertFalse(self.manager.acquire_single_instance())
        self.assertIsNone(self.manager._SINGLE_INSTANCE_MUTEX)
        self.kernel.CloseHandle.assert_called_once_with(0x123456789)
