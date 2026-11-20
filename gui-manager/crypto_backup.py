"""
Encrypted Backup & Restore Module for Antigravity Hub
Provides password protection for exported account profiles using PBKDF2-HMAC-SHA256 + AES-256-GCM.
Supports decrypting legacy V1 backups for backward compatibility.
"""

import json
import hashlib
import hmac
import secrets

MAGIC_HEADER_V1 = b"AGY_ENCRYPTED_V1\n"
MAGIC_HEADER_V2 = b"AGY_ENCRYPTED_V2\n"
MAGIC_HEADER = MAGIC_HEADER_V2
PBKDF2_ITERATIONS_V1 = 100_000
PBKDF2_ITERATIONS_V2 = 600_000
MAX_BACKUP_BYTES = 16 * 1024 * 1024


def validate_password(password: str) -> None:
    if not isinstance(password, str) or not password or len(password) > 1024:
        raise ValueError("Укажите непустой пароль (не более 1024 символов)")


def load_backup_json(raw: bytes) -> dict:
    def unique(pairs):
        result = dict(pairs)
        if len(result) != len(pairs):
            raise ValueError("Резервная копия содержит повторяющиеся поля")
        return result

    def reject_constant(_):
        raise ValueError("Некорректное число в резервной копии")

    def finite_float(value):
        import math
        result = float(value)
        if not math.isfinite(result):
            reject_constant(value)
        return result

    parsed = json.loads(raw.decode("utf-8-sig"), object_pairs_hook=unique,
                        parse_constant=reject_constant, parse_float=finite_float)
    if not isinstance(parsed, dict):
        raise ValueError("Некорректная структура файла бэкапа")
    return parsed


def _derive_keys_v1(password: str, salt: bytes) -> tuple[bytes, bytes]:
    key_material = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        iterations=PBKDF2_ITERATIONS_V1,
        dklen=64,
    )
    return key_material[:32], key_material[32:]


def _derive_key_v2(password: str, salt: bytes) -> bytes:
    return hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        iterations=PBKDF2_ITERATIONS_V2,
        dklen=32,
    )


def _keystream_v1(key: bytes, length: int) -> bytes:
    stream = bytearray()
    counter = 0
    while len(stream) < length:
        block = hashlib.sha256(key + counter.to_bytes(8, "big")).digest()
        stream.extend(block)
        counter += 1
    return bytes(stream[:length])


def encrypt_backup(data_dict: dict, password: str) -> bytes:
    """Encrypts JSON dict into an authenticated AES-256-GCM binary payload."""
    if not isinstance(data_dict, dict):
        raise ValueError("Данные бэкапа должны быть JSON-объектом")
    validate_password(password)
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    raw_json = json.dumps(data_dict, ensure_ascii=False, allow_nan=False).encode("utf-8")
    if len(raw_json) + len(MAGIC_HEADER_V2) + 44 > MAX_BACKUP_BYTES:
        raise ValueError("Резервная копия превышает 16 МиБ")
    salt = secrets.token_bytes(16)
    nonce = secrets.token_bytes(12)
    key = _derive_key_v2(password, salt)
    ciphertext = AESGCM(key).encrypt(nonce, raw_json, MAGIC_HEADER_V2)
    return MAGIC_HEADER_V2 + salt + nonce + ciphertext


def decrypt_backup(encrypted_bytes: bytes, password: str) -> dict:
    """Decrypts authenticated V2 (AES-GCM) or legacy V1 payload back to JSON dict."""
    validate_password(password)
    if len(encrypted_bytes) > MAX_BACKUP_BYTES:
        raise ValueError("Резервная копия превышает 16 МиБ")

    if encrypted_bytes.startswith(MAGIC_HEADER_V2):
        from cryptography.exceptions import InvalidTag
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        offset = len(MAGIC_HEADER_V2)
        # salt (16) + nonce (12) + GCM tag (16) = 44 bytes minimum
        if len(encrypted_bytes) < offset + 44:
            raise ValueError("Файл бэкапа повреждён или усечён")
        salt = encrypted_bytes[offset:offset + 16]
        nonce = encrypted_bytes[offset + 16:offset + 28]
        ciphertext = encrypted_bytes[offset + 28:]
        key = _derive_key_v2(password, salt)
        try:
            plaintext = AESGCM(key).decrypt(nonce, ciphertext, MAGIC_HEADER_V2)
        except InvalidTag:
            raise ValueError("Неверный пароль или файл повреждён!") from None
    elif encrypted_bytes.startswith(MAGIC_HEADER_V1):
        offset = len(MAGIC_HEADER_V1)
        if len(encrypted_bytes) < offset + 48:
            raise ValueError("Файл бэкапа повреждён или усечён")
        salt = encrypted_bytes[offset:offset + 16]
        mac = encrypted_bytes[offset + 16:offset + 48]
        ciphertext = encrypted_bytes[offset + 48:]
        enc_key, hmac_key = _derive_keys_v1(password, salt)
        expected_mac = hmac.new(hmac_key, salt + ciphertext, hashlib.sha256).digest()
        if not hmac.compare_digest(mac, expected_mac):
            raise ValueError("Неверный пароль или файл повреждён!")
        ks = _keystream_v1(enc_key, len(ciphertext))
        plaintext = bytes(a ^ b for a, b in zip(ciphertext, ks))
    else:
        raise ValueError("Файл не является зашифрованным бэкапом Antigravity")

    return load_backup_json(plaintext)


def is_encrypted_backup(file_bytes: bytes) -> bool:
    return file_bytes.startswith(MAGIC_HEADER_V2) or file_bytes.startswith(MAGIC_HEADER_V1)
