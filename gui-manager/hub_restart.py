"""Restart Hub only after its previous process has exited."""
import ctypes
import os
from pathlib import Path
import subprocess
import sys
import time

def wait_for_exit(pid: int, timeout: float = 60) -> bool:
    """Wait without signalling or terminating any process."""
    if not 0 < pid <= 0x7FFFFFFF or pid == os.getpid():
        return False
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
            return kernel.WaitForSingleObject(handle, int(max(0, timeout) * 1000)) == 0
        finally:
            kernel.CloseHandle(handle)
    deadline = time.monotonic() + timeout
    while True:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        except OSError:
            return False
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        time.sleep(min(0.2, remaining))


def schedule_restart():
    # This function can be imported by the old Hub after its files have been
    # updated. The fresh helper, not the old process, cleans up its environment.
    if getattr(sys, "frozen", False):
        subprocess.Popen([sys.executable, "--restart-after", str(os.getpid())],
                         cwd=str(Path(sys.executable).parent),
                         env={**os.environ, "PYINSTALLER_RESET_ENVIRONMENT": "1"})
        return
    kwargs = {"cwd": str(Path(__file__).resolve().parent)}
    if os.name == "nt":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    subprocess.Popen(
        [sys.executable, str(Path(__file__).resolve()), str(os.getpid())],
        **kwargs,
    )


def _parent_has_exited(parent_pid: str) -> bool:
    try:
        pid = int(parent_pid)
    except ValueError:
        return False
    return wait_for_exit(pid)


def relaunch_packaged(parent_pid: str) -> int:
    if not _parent_has_exited(parent_pid):
        return 1
    from proxy_config import opencode_launch_environment

    subprocess.Popen([sys.executable], cwd=str(Path(sys.executable).parent),
                     env={**opencode_launch_environment(), "PYINSTALLER_RESET_ENVIRONMENT": "1"})
    return 0


def relaunch_source(parent_pid: str) -> int:
    if not _parent_has_exited(parent_pid):
        return 1
    from proxy_config import opencode_launch_environment

    script = Path(__file__).resolve().with_name("antigravity_manager.pyw")
    subprocess.Popen([sys.executable, str(script)], cwd=str(script.parent), close_fds=True,
                     env=opencode_launch_environment())
    return 0


if __name__ == "__main__":
    sys.exit(relaunch_source(sys.argv[1]) if len(sys.argv) == 2 else 1)
