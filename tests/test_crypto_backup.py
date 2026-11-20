import hashlib
import hmac
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "gui-manager"))
import crypto_backup


class CryptoBackupTests(unittest.TestCase):
    def test_v2_roundtrip_randomization_tamper_and_wrong_password(self):
        data = {"accounts": [{"refreshToken": "sensitive"}]}
        first = crypto_backup.encrypt_backup(data, "long password")
        second = crypto_backup.encrypt_backup(data, "long password")
        self.assertTrue(first.startswith(b"AGY_ENCRYPTED_V2\n"))
        self.assertNotEqual(first, second)
        self.assertNotIn(b"sensitive", first)
        self.assertEqual(crypto_backup.decrypt_backup(first, "long password"), data)
        with self.assertRaises(ValueError):
            crypto_backup.decrypt_backup(first, "incorrect")
        with self.assertRaises(ValueError):
            crypto_backup.decrypt_backup(first[:-1] + bytes([first[-1] ^ 1]), "long password")

    def test_reads_historical_v1_payload(self):
        password = "legacy"
        plain = b'{"accounts":[]}'
        salt = bytes(range(16))
        keys = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 100_000, 64)
        stream = hashlib.sha256(keys[:32] + bytes(8)).digest()
        cipher = bytes(a ^ b for a, b in zip(plain, stream))
        tag = hmac.digest(keys[32:], salt + cipher, "sha256")
        old = b"AGY_ENCRYPTED_V1\n" + salt + tag + cipher
        self.assertEqual(crypto_backup.decrypt_backup(old, password), {"accounts": []})

    def test_resource_and_json_validation(self):
        with self.assertRaises(ValueError):
            crypto_backup.encrypt_backup({}, "")
        with self.assertRaises(ValueError):
            crypto_backup.load_backup_json(b'{"config":{},"config":{}}')
        with self.assertRaises(ValueError):
            crypto_backup.load_backup_json(b'{"number":1e1000}')
        with patch.object(crypto_backup, "MAX_BACKUP_BYTES", 32):
            with self.assertRaises(ValueError):
                crypto_backup.encrypt_backup({}, "password")
            with self.assertRaises(ValueError):
                crypto_backup.decrypt_backup(b"x" * 33, "password")
