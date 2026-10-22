"""Private files and user-bound DPAPI protection for Hub secrets and channels."""
import base64
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import secrets
from deepseek_browser import WebError


def atomic_write(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    if os.name != "nt":
        path.parent.chmod(0o700)
    temporary = path.with_name(path.name + "." + secrets.token_hex(6) + ".tmp")
    try:
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(text)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def dpapi(data, decrypt=False):
    class Blob(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte))]
    buffer = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
    source, output = Blob(len(data), buffer), Blob()
    crypt = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    operation = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    operation.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    operation.restype = wintypes.BOOL
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    if not operation(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(output)):
        raise WebError("browser-protocol")
    try:
        return ctypes.string_at(output.data, output.size)
    finally:
        ctypes.memset(output.data, 0, output.size)
        kernel.LocalFree(output.data)


def protect_channel(payload):
    if os.name == "nt":
        return {"version": 3, "protection": "dpapi-current-user", "payload": base64.b64encode(dpapi(json.dumps(payload).encode())).decode()}
    return {"version": 3, "protection": "private-file", "payload": payload}


def protect_secret(purpose, payload):
    """Protect Hub secrets at rest; never serialize them raw on Windows."""
    if purpose not in {"deepseek-web-session", "openrouter-api-key", "mwapi-api-key", "mwapi-dashboard-token"}:
        raise ValueError("Unknown protected secret purpose")
    raw = json.dumps({"purpose": purpose, "data": payload}, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if os.name == "nt":
        return {"version": 1, "protection": "dpapi-current-user", "payload": base64.b64encode(dpapi(raw)).decode("ascii")}
    return {"version": 1, "protection": "private-file", "payload": json.loads(raw)}


def unprotect_secret(record, purpose):
    if not isinstance(record, dict) or record.get("version") != 1:
        raise WebError("login-required")
    protection = record.get("protection")
    if os.name == "nt" and protection == "dpapi-current-user":
        try:
            raw = dpapi(base64.b64decode(record["payload"], validate=True), decrypt=True)
            value = json.loads(raw)
        except Exception:
            raise WebError("login-required") from None
    elif os.name != "nt" and protection == "private-file":
        value = record.get("payload")
    else:
        raise WebError("login-required")
    if not isinstance(value, dict) or value.get("purpose") != purpose or not isinstance(value.get("data"), dict):
        raise WebError("login-required")
    data = value["data"]
    if purpose == "deepseek-web-session" and (not isinstance(data.get("token"), str) or not data["token"]
            or not isinstance(data.get("cookies"), dict) or not isinstance(data.get("userAgent"), str)):
        raise WebError("login-required")
    if purpose in {"openrouter-api-key", "mwapi-api-key"} and (not isinstance(data.get("apiKey"), str) or not data["apiKey"].strip()):
        raise WebError("login-required")
    if purpose == "mwapi-dashboard-token" and (not isinstance(data.get("accessToken"), str) or not data["accessToken"].strip()):
        raise WebError("login-required")
    return data
