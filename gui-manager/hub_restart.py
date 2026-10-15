"""Restart Hub only after its previous process has exited."""
import ctypes
import os
from pathlib import Path
import subprocess
import sys
import time


def wait_for_exit(pid, timeout=60):
    if os.name == "nt":
        from ctypes import wintypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.OpenProcess(0x00100000, False, pid)
        if not handle:
            return ctypes.get_last_error() == 87  # Process already exited.
        try:
            return kernel.WaitForSingleObject(handle, int(timeout * 1000)) == 0
        finally:
            kernel.CloseHandle(handle)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        time.sleep(0.2)
    return False


def schedule_restart():
    subprocess.Popen(
        [sys.executable, str(Path(__file__).resolve()), str(os.getpid())],
        cwd=str(Path(__file__).resolve().parent),
    )


if __name__ == "__main__":
    if wait_for_exit(int(sys.argv[1])):
        script = Path(__file__).resolve().with_name("antigravity_manager.pyw")
        subprocess.Popen([sys.executable, str(script)], cwd=str(script.parent))
