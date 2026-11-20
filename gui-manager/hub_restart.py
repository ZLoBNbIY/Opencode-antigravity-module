"""Restart Hub only after its previous process has exited."""
import ctypes
import os
from pathlib import Path
import signal
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


def _force_kill_pid(pid: int) -> None:
    try:
        if os.name == "nt":
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            subprocess.run(
                ["taskkill", "/f", "/t", "/pid", str(pid)],
                capture_output=True, creationflags=flags, timeout=10,
            )
        else:
            os.kill(pid, signal.SIGKILL)
    except Exception:
        pass


def _kill_stray_hub_processes(exclude_pids: set[int]) -> None:
    if os.name != "nt":
        return
    try:
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        ps_cmd = (
            "Get-CimInstance Win32_Process -ErrorAction SilentlyContinue "
            "| Where-Object { $_.CommandLine -match 'antigravity_manager\\.pyw' } "
            "| Select-Object -ExpandProperty ProcessId"
        )
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_cmd],
            capture_output=True, text=True, creationflags=flags, timeout=10,
        )
        for line in proc.stdout.splitlines():
            line = line.strip()
            if line.isdigit():
                pid = int(line)
                if pid not in exclude_pids:
                    _force_kill_pid(pid)
                    wait_for_exit(pid, timeout=3)
    except Exception:
        pass


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


def relaunch_packaged(parent_pid: str) -> int:
    try:
        pid = int(parent_pid)
    except ValueError:
        return 1
    if pid <= 0 or not wait_for_exit(pid):
        return 1
    from proxy_config import opencode_launch_environment

    subprocess.Popen([sys.executable], cwd=str(Path(sys.executable).parent),
                     env={**opencode_launch_environment(), "PYINSTALLER_RESET_ENVIRONMENT": "1"})
    return 0


if __name__ == "__main__":
    from proxy_config import opencode_launch_environment

    if len(sys.argv) < 2:
        sys.exit(1)
    try:
        parent_pid = int(sys.argv[1])
    except ValueError:
        sys.exit(1)
    if not wait_for_exit(parent_pid, timeout=10):
        _force_kill_pid(parent_pid)
        wait_for_exit(parent_pid, timeout=5)
    _kill_stray_hub_processes({os.getpid(), parent_pid})
    script = Path(__file__).resolve().with_name("antigravity_manager.pyw")
    subprocess.Popen([sys.executable, str(script)], cwd=str(script.parent), close_fds=True,
                     env=opencode_launch_environment())
