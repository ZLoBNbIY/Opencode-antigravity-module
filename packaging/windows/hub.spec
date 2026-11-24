from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files
import os
from importlib.util import find_spec
import json

repo = Path(SPECPATH).resolve().parents[1]
manager = repo / "gui-manager"

version_file_env = os.environ.get("HUB_BUILD_VERSION_FILE", "").strip()
if not version_file_env:
    raise RuntimeError("HUB_BUILD_VERSION_FILE environment variable must be set")
version_file = Path(version_file_env)
if not version_file.is_file():
    raise FileNotFoundError(f"HUB_BUILD_VERSION_FILE does not exist: {version_file}")

browsers_env = os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "").strip()
if not browsers_env:
    raise RuntimeError("PLAYWRIGHT_BROWSERS_PATH environment variable must be set")
browser_root = Path(browsers_env)
if not browser_root.is_dir():
    raise FileNotFoundError(f"PLAYWRIGHT_BROWSERS_PATH directory does not exist: {browser_root}")

playwright_spec = find_spec("playwright")
if playwright_spec is None or not playwright_spec.origin:
    raise RuntimeError("playwright package is not installed in this Python environment")
driver_package = Path(playwright_spec.origin).parent / "driver" / "package"
browsers = json.loads((driver_package / "browsers.json").read_text(encoding="utf-8"))["browsers"]
required = {"chromium", "ffmpeg", "winldd"}
browser_datas = []
for entry in browsers:
    if entry.get("name") not in required:
        continue
    revision = entry.get("revisionOverrides", {}).get("win64", entry["revision"])
    folder_name = f"{entry['name']}-{revision}"
    folder_path = browser_root / folder_name
    if not folder_path.is_dir():
        raise FileNotFoundError(
            f"Required Playwright browser folder '{folder_name}' is missing in {browser_root}"
        )
    browser_datas.append((str(folder_path), f"browsers/{folder_name}"))

datas = [
    (str(manager / "web"), "web"),
    (str(manager / "icon.ico"), "."),
    (str(version_file), "."),
    (str(repo / "config-templates"), "config-templates"),
    (str(repo / "plugin" / "package.json"), "plugin"),
    (str(repo / "plugin" / "LICENSE"), "plugin"),
] + [
    (str(repo / "plugin" / "dist" / name), "plugin/dist")
    for name in ("cli.js", "server.js", "index.js", "google-due-store.mjs",
                 "google-cli-3113.mjs", "google-cli-3113-loader.mjs", "google-login-3113.mjs")
] + browser_datas + collect_data_files("webview")

a = Analysis(
    [str(manager / "antigravity_manager.pyw")],
    pathex=[str(manager)],
    datas=datas,
    hiddenimports=["webview.platforms.winforms", "webview.platforms.edgechromium", "clr",
                   "pythonnet", "bottle", "playwright.sync_api", "webview_backend", "proxy_tools"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [], exclude_binaries=True, name="AntigravityHub", console=False,
    icon=str(manager / "icon.ico"), upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="AntigravityHub", upx=False)
