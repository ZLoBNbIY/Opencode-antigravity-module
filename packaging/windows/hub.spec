from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files
import os
from importlib.util import find_spec
import json

repo = Path(SPECPATH).resolve().parents[1]
manager = repo / "gui-manager"
browser_root = Path(os.environ["PLAYWRIGHT_BROWSERS_PATH"])
driver_package = Path(find_spec("playwright").origin).parent / "driver" / "package"
browsers = json.loads((driver_package / "browsers.json").read_text(encoding="utf-8"))["browsers"]
required = {"chromium", "ffmpeg", "winldd"}

datas = [
    (str(manager / "web"), "web"),
    (str(manager / "icon.ico"), "."),
    (os.environ["HUB_BUILD_VERSION_FILE"], "."),
    (str(repo / "config-templates"), "config-templates"),
    (str(repo / "plugin" / "package.json"), "plugin"),
    (str(repo / "plugin" / "LICENSE"), "plugin"),
] + [
    (str(repo / "plugin" / "dist" / name), "plugin/dist")
    for name in ("cli.js", "server.js", "index.js")
] + [
    (str(browser_root / folder_name), f"browsers/{folder_name}")
    for entry in browsers if entry["name"] in required
    for folder_name in [f"{entry['name']}-{entry['revisionOverrides'].get('win64', entry['revision'])}"
                        if "revisionOverrides" in entry else f"{entry['name']}-{entry['revision']}"]
    if (browser_root / folder_name).is_dir()
] + collect_data_files("webview")

a = Analysis(
    [str(manager / "antigravity_manager.pyw")],
    pathex=[str(manager)],
    datas=datas,
    hiddenimports=["webview.platforms.winforms", "webview.platforms.edgechromium", "clr",
                   "pythonnet", "bottle", "playwright.sync_api", "webview_backend"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [], exclude_binaries=True, name="AntigravityHub", console=False,
    icon=str(manager / "icon.ico"), upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="AntigravityHub", upx=False)
