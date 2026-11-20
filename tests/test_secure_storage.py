import json
import os
from pathlib import Path
import sys
import unittest

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
