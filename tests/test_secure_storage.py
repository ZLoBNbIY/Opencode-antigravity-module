import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "gui-manager"))

import secure_storage


class SecureStorageTests(unittest.TestCase):
    def test_payload_roundtrip_binds_purpose(self):
        payload = {"apiKey": "fake-key-for-unit-test"}
        record = secure_storage.protect_secret("provider-a", payload)
        if os.name == "nt":
            self.assertNotIn(payload["apiKey"], json.dumps(record))
        else:
            self.assertEqual(record["protection"], "private-file")
        self.assertEqual(secure_storage.unprotect_secret(record, "provider-a"), payload)
        with self.assertRaises(secure_storage.StorageError):
            secure_storage.unprotect_secret(record, "provider-b")

    def test_raw_credentials_are_not_a_protected_record(self):
        with self.assertRaises(secure_storage.StorageError):
            secure_storage.unprotect_secret({"apiKey": "fake-key-for-unit-test"}, "provider-a")

    def test_fsync_failure_leaves_old_file_and_no_temp(self):
        with TemporaryDirectory() as root:
            path = Path(root) / "secret"
            path.write_bytes(b"old")
            with patch.object(secure_storage.os, "fsync", side_effect=OSError("simulated fsync")):
                with self.assertRaises(OSError):
                    secure_storage.atomic_write_bytes(path, b"new")
            self.assertEqual(path.read_bytes(), b"old")
            self.assertEqual(list(path.parent.iterdir()), [path])

    def test_fsync_sees_new_bytes_before_replacement(self):
        with TemporaryDirectory() as root:
            path = Path(root) / "secret"
            path.write_bytes(b"old")

            def verify_sync(_fd):
                self.assertEqual(path.read_bytes(), b"old")
                files = list(path.parent.glob("*.tmp"))
                self.assertEqual(len(files), 1)
                self.assertEqual(files[0].read_bytes(), b"new")

            with patch.object(secure_storage, "_fsync_directory") as sync_dir, patch.object(
                secure_storage.os, "fsync", side_effect=verify_sync,
            ) as fsync:
                secure_storage.atomic_write_bytes(path, b"new")
                fsync.assert_called_once()
                sync_dir.assert_called_once_with(path.parent)
            self.assertEqual(path.read_bytes(), b"new")

    def test_windows_acl_is_protected_and_used_at_creation(self):
        kernel, advapi = MagicMock(), MagicMock()
        sid = "S-1-5-21-1-2-3-1001"
        kernel.CreateFileW.return_value = 123
        convert = advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW

        def set_descriptor(_sddl, _revision, output, _size):
            output._obj.value = 456
            return True

        convert.side_effect = set_descriptor

        def check_create(_path, _access, sharing, attrs, disposition, _flags, _template):
            self.assertEqual(sharing, 0)
            self.assertEqual(attrs._obj.descriptor, 456)
            self.assertFalse(attrs._obj.inherit)
            self.assertEqual(disposition, 1)  # CREATE_NEW
            return 123

        kernel.CreateFileW.side_effect = check_create

        def mark_persistent(*args):
            args[5]._obj.value = 0x8
            return True

        kernel.GetVolumeInformationByHandleW.side_effect = mark_persistent
        msvcrt = SimpleNamespace(open_osfhandle=MagicMock(return_value=42))
        target = MagicMock(spec=Path)
        with patch.dict(sys.modules, msvcrt=msvcrt), patch.object(
            secure_storage.ctypes, "WinDLL", side_effect=(kernel, advapi, kernel, advapi), create=True,
        ), patch.object(secure_storage.os, "O_BINARY", getattr(os, "O_BINARY", 0), create=True), patch.object(
            secure_storage, "_windows_user_sid", return_value=sid,
        ):
            self.assertEqual(secure_storage._open_windows_private_file(target), 42)
            self.assertEqual(convert.call_args.args[0], f"D:P(A;;FA;;;{sid})(A;;FA;;;SY)")
            self.assertEqual(msvcrt.open_osfhandle.call_args.args[0], 123)
            kernel.GetVolumeInformationByHandleW.side_effect = None
            kernel.GetVolumeInformationByHandleW.return_value = True
            with self.assertRaisesRegex(OSError, "persistent Windows ACLs"):
                secure_storage._open_windows_private_file(target)
            kernel.CloseHandle.assert_called_once_with(123)
            target.unlink.assert_called_once_with(missing_ok=True)
            msvcrt.open_osfhandle.assert_called_once()
