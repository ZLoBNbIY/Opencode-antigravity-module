"""
Encrypted Backup & Restore Module for Antigravity Hub
Provides optional password protection for exported account profiles using PBKDF2 + HMAC.
Uses standard Python library only (hashlib, hmac, secrets).
"""

import json
import hashlib
import hmac
import secrets
import base64

MAGIC_HEADER = b"AGY_ENCRYPTED_V1\n"

def _derive_keys(password: str, salt: bytes) -> tuple[bytes, bytes]:
    """Derives 32-byte encryption key and 32-byte HMAC key from password using PBKDF2-SHA256."""
    key_material = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        iterations=100_000,
        dklen=64
    )
    return key_material[:32], key_material[32:]

def _keystream(key: bytes, length: int) -> bytes:
    """Generates keystream using CTR mode with SHA256."""
    stream = bytearray()
    counter = 0
    while len(stream) < length:
        block = hashlib.sha256(key + counter.to_bytes(8, "big")).digest()
        stream.extend(block)
        counter += 1
    return bytes(stream[:length])

def encrypt_backup(data_dict: dict, password: str) -> bytes:
    """Encrypts JSON dict into authenticated binary payload."""
    raw_json = json.dumps(data_dict, ensure_ascii=False).encode("utf-8")
    salt = secrets.token_bytes(16)
    enc_key, hmac_key = _derive_keys(password, salt)

    # CTR keystream encryption
    ks = _keystream(enc_key, len(raw_json))
    ciphertext = bytes(a ^ b for a, b in zip(raw_json, ks))

    # HMAC-SHA256 authentication tag
    mac = hmac.new(hmac_key, salt + ciphertext, hashlib.sha256).digest()

    return MAGIC_HEADER + salt + mac + ciphertext

def decrypt_backup(encrypted_bytes: bytes, password: str) -> dict:
    """Decrypts authenticated payload back to JSON dict."""
    if not encrypted_bytes.startswith(MAGIC_HEADER):
        raise ValueError("Файл не является зашифрованным бэкапом Antigravity")

    offset = len(MAGIC_HEADER)
    salt = encrypted_bytes[offset:offset + 16]
    mac = encrypted_bytes[offset + 16:offset + 48]
    ciphertext = encrypted_bytes[offset + 48:]

    enc_key, hmac_key = _derive_keys(password, salt)

    expected_mac = hmac.new(hmac_key, salt + ciphertext, hashlib.sha256).digest()
    if not hmac.compare_digest(mac, expected_mac):
        raise ValueError("Неверный пароль или файл повреждён!")

    ks = _keystream(enc_key, len(ciphertext))
    plaintext = bytes(a ^ b for a, b in zip(ciphertext, ks))

    return json.loads(plaintext.decode("utf-8"))

def is_encrypted_backup(file_bytes: bytes) -> bool:
    return file_bytes.startswith(MAGIC_HEADER)
