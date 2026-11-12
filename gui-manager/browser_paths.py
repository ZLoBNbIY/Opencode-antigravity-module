"""
Cross-platform browser discovery and CDP detection.
Used by Claude manager and browser automation.
"""
from __future__ import annotations

import os
import re
import shutil
import sys
from pathlib import Path


def browser_paths() -> dict[str, Path]:
    """Find installed browser executables."""
    found: dict[str, Path] = {}
    names = {"chrome": "chrome.exe", "edge": "msedge.exe"}
    if os.name == "nt":
        import winreg
        for brand, filename in names.items():
            for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
                try:
                    with winreg.OpenKey(hive, rf"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{filename}") as key:
                        value = Path(winreg.QueryValue(key, None).strip('"'))
                    if value.is_file() and value.name.lower() == filename:
                        found[brand] = value
                except OSError:
                    pass
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\Shell\Associations\UrlAssociations\https\UserChoice") as key:
                prog_id = winreg.QueryValueEx(key, "ProgId")[0]
            with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, prog_id + r"\shell\open\command") as key:
                command = winreg.QueryValueEx(key, None)[0]
            match = re.match(r'^\s*"([^\"]+\.exe)"|^\s*(.+?\.exe)(?:\s|$)', command, re.IGNORECASE)
            executable = Path(next(group for group in match.groups() if group).strip()) if match else None
            if executable and executable.is_file():
                found["default"] = executable
        except (OSError, StopIteration, AttributeError):
            pass
        roots = [
            Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")),
            Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")),
            Path.home() / "AppData/Local",
        ]
        for root in roots:
            for brand, relative in (("chrome", "Google/Chrome/Application/chrome.exe"), ("edge", "Microsoft/Edge/Application/msedge.exe")):
                candidate = root / relative
                if candidate.is_file():
                    found.setdefault(brand, candidate)
    elif sys.platform == "darwin":
        for brand, app, executable in (("chrome", "Google Chrome", "Google Chrome"), ("edge", "Microsoft Edge", "Microsoft Edge")):
            path = Path(f"/Applications/{app}.app/Contents/MacOS/{executable}")
            if path.is_file():
                found[brand] = path
    else:
        for brand, commands in (("chrome", ("google-chrome", "chromium", "chromium-browser")), ("edge", ("microsoft-edge",))):
            for command in commands:
                path = shutil.which(command)
                if path:
                    found[brand] = Path(path)
                    break
    return found


def supports_cdp(path: str | Path) -> bool:
    """Recognize installed Chromium-family executables; Firefox is not CDP."""
    name = Path(path).name.lower()
    return name in {
        "chrome.exe", "msedge.exe", "browser.exe", "brave.exe", "opera.exe", "vivaldi.exe",
        "chromium.exe", "chrome", "microsoft-edge", "google-chrome", "chromium", "chromium-browser",
    }
