"""Private files and user-bound DPAPI protection for Hub secrets."""
import base64
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import secrets
import stat


class StorageError(Exception):
    pass


def regular_file_stat(path: Path):
    """Stat a regular file without following a symlink or Windows reparse point."""
    info = path.lstat()
    if (not stat.S_ISREG(info.st_mode) or
            getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT):
        raise OSError(f"Not an ordinary file: {path.name}")
    return info


def atomic_write(path: Path, text: str, *, private_parent=True, private_windows=False):
    atomic_write_bytes(path, text.encode("utf-8"), private_parent=private_parent,
                       private_windows=private_windows)


def _win_function(library, name, result, *args):
    function = getattr(library, name)
    function.restype = result
    function.argtypes = args
    return function


def _windows_user_sid(kernel, advapi):
    p = ctypes.c_void_p
    dword_p = ctypes.POINTER(wintypes.DWORD)
    close = _win_function(kernel, "CloseHandle", wintypes.BOOL, wintypes.HANDLE)
    free = _win_function(kernel, "LocalFree", p, p)
    process = _win_function(kernel, "GetCurrentProcess", wintypes.HANDLE)
    open_token = _win_function(advapi, "OpenProcessToken", wintypes.BOOL,
                               wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE))
    token_info = _win_function(advapi, "GetTokenInformation", wintypes.BOOL,
                               wintypes.HANDLE, ctypes.c_int, p, wintypes.DWORD, dword_p)
    sid_string = _win_function(advapi, "ConvertSidToStringSidW", wintypes.BOOL,
                               p, ctypes.POINTER(ctypes.c_wchar_p))
    token = wintypes.HANDLE()
    if not open_token(process(), 0x0008, ctypes.byref(token)):  # TOKEN_QUERY
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        length = wintypes.DWORD()
        token_info(token, 1, None, 0, ctypes.byref(length))  # TokenUser, size query
        if not length.value:
            raise ctypes.WinError(ctypes.get_last_error())
        buffer = ctypes.create_string_buffer(length.value)
        if not token_info(token, 1, buffer, length, ctypes.byref(length)):
            raise ctypes.WinError(ctypes.get_last_error())
        # TOKEN_USER starts with SID_AND_ATTRIBUTES, whose first member is PSID.
        sid = ctypes.cast(buffer, ctypes.POINTER(p))[0]
        text = ctypes.c_wchar_p()
        if not sid_string(sid, ctypes.byref(text)):
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            return text.value
        finally:
            free(ctypes.cast(text, p))
    finally:
        close(token)


def _open_windows_private_file(path: Path):
    """Create an empty file with a protected DACL, before writing any secret."""
    import msvcrt

    p = ctypes.c_void_p

    class SecurityAttributes(ctypes.Structure):
        _fields_ = [("length", wintypes.DWORD), ("descriptor", p), ("inherit", wintypes.BOOL)]

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    close = _win_function(kernel, "CloseHandle", wintypes.BOOL, wintypes.HANDLE)
    free = _win_function(kernel, "LocalFree", p, p)
    convert = _win_function(advapi, "ConvertStringSecurityDescriptorToSecurityDescriptorW",
                            wintypes.BOOL, wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(p), p)
    create = _win_function(kernel, "CreateFileW", wintypes.HANDLE, wintypes.LPCWSTR,
                           wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(SecurityAttributes),
                           wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE)
    volume_info = _win_function(kernel, "GetVolumeInformationByHandleW", wintypes.BOOL,
                                wintypes.HANDLE, p, wintypes.DWORD, p, p,
                                ctypes.POINTER(wintypes.DWORD), p, wintypes.DWORD)
    sid = _windows_user_sid(kernel, advapi)
    # Protected DACL, full access for this process's user SID and LocalSystem.
    # Neither inheritance nor membership in Users/Administrators grants access.
    descriptor = p()
    if not convert(f"D:P(A;;FA;;;{sid})(A;;FA;;;SY)", 1, ctypes.byref(descriptor), None):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        attrs = SecurityAttributes(ctypes.sizeof(SecurityAttributes), descriptor, False)
        handle = create(str(path), 0x40000000, 0, ctypes.byref(attrs), 1, 0x80, None)
        if handle == p(-1).value:  # INVALID_HANDLE_VALUE; CREATE_NEW, never open existing
            raise ctypes.WinError(ctypes.get_last_error())
    finally:
        free(descriptor)
    try:
        flags = wintypes.DWORD()
        if not volume_info(handle, None, 0, None, None, ctypes.byref(flags), None, 0):
            raise ctypes.WinError(ctypes.get_last_error())
        if not flags.value & 0x00000008:  # FS_PERSISTENT_ACLS
            raise OSError("The target volume does not support persistent Windows ACLs.")
        return msvcrt.open_osfhandle(handle, os.O_WRONLY | os.O_BINARY)
    except BaseException:
        close(handle)
        path.unlink(missing_ok=True)
        raise


def _fsync_directory(path: Path):
    """Best effort: failure after replace cannot be reported as a failed write."""
    if os.name != "nt":
        try:
            descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        except OSError:
            pass  # Some filesystems do not support directory fsync.


def _ensure_real_dir(directory: Path):
    info = os.lstat(directory)
    if (not stat.S_ISDIR(info.st_mode) or
            stat.S_ISLNK(info.st_mode) or
            getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT):
        raise OSError(f"Not an ordinary directory: {directory.name}")
    return info


def atomic_write_bytes(path: Path, data: bytes, *, private_parent=True, private_windows=False):
    if private_parent:
        created = []
        probe = path.parent
        while probe != probe.parent and not probe.exists():
            created.append(probe)
            probe = probe.parent
        for directory in reversed(created):
            directory.mkdir(mode=0o700, exist_ok=True)
            _ensure_real_dir(directory)
            if os.name != "nt":
                os.chmod(directory, 0o700)
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
    _ensure_real_dir(path.parent)
    if private_parent and os.name != "nt":
        os.chmod(path.parent, 0o700)
    if private_windows:
        try:
            regular_file_stat(path)
        except FileNotFoundError:
            pass
    temporary = path.with_name(path.name + "." + secrets.token_hex(6) + ".tmp")
    if private_windows and os.name == "nt":
        descriptor = _open_windows_private_file(temporary)
    else:
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                             getattr(os, "O_BINARY", 0), 0o600)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        if private_windows:
            try:
                regular_file_stat(path)
            except FileNotFoundError:
                pass
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    _fsync_directory(path.parent)


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
    free = _win_function(kernel, "LocalFree", ctypes.c_void_p, ctypes.c_void_p)
    try:
        if not operation(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(output)):
            raise StorageError("dpapi-operation-failed")
        return ctypes.string_at(output.data, output.size)
    finally:
        ctypes.memset(buffer, 0, len(data))
        if output.data:
            ctypes.memset(output.data, 0, output.size)
            free(output.data)


def protect_payload(purpose: str, payload: dict) -> dict:
    """Protect arbitrary JSON dict payloads at rest using DPAPI on Windows."""
    if not isinstance(payload, dict):
        raise StorageError("invalid-payload")
    raw = json.dumps({"purpose": purpose, "data": payload}, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if os.name == "nt":
        return {"version": 1, "protection": "dpapi-current-user", "payload": base64.b64encode(dpapi(raw)).decode("ascii")}
    return {"version": 1, "protection": "private-file", "payload": json.loads(raw)}


def unprotect_payload(record: dict, purpose: str) -> dict:
    if not isinstance(record, dict) or type(record.get("version")) is not int or record.get("version") != 1:
        raise StorageError("invalid-secret-record")
    protection = record.get("protection")
    if os.name == "nt" and protection == "dpapi-current-user":
        try:
            raw = dpapi(base64.b64decode(record["payload"], validate=True), decrypt=True)
            value = json.loads(raw)
        except Exception:
            raise StorageError("dpapi-decrypt-failed") from None
    elif os.name != "nt" and protection == "private-file":
        value = record.get("payload")
    else:
        raise StorageError("unsupported-protection")
    if not isinstance(value, dict) or value.get("purpose") != purpose or not isinstance(value.get("data"), dict):
        raise StorageError("secret-purpose-mismatch")
    return value["data"]


def protect_secret(purpose: str, payload: dict) -> dict:
    """Protect Hub secrets at rest; never serialize them raw on Windows."""
    return protect_payload(purpose, payload)


def unprotect_secret(record: dict, purpose: str) -> dict:
    data = unprotect_payload(record, purpose)
    if not isinstance(data.get("apiKey"), str) or not data["apiKey"].strip():
        raise StorageError("invalid-api-key")
    return data
