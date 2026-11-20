"""Offline capability check for a Windows distribution, without starting Hub."""

import json
import subprocess


def check_bundle(bundle, report):
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        from playwright.sync_api import sync_playwright
        import webview
        import webview_backend
        from webview.platforms import edgechromium

        for name in ("index.html", "app.js", "style.css"):
            if not (bundle / "web" / name).is_file():
                raise FileNotFoundError(name)
        with sync_playwright() as playwright:
            with playwright.chromium.launch(channel="chromium") as browser:
                page = browser.new_page()
                page.set_content("<title>Antigravity Hub</title>")
                if page.title() != "Antigravity Hub":
                    raise RuntimeError("Bundled Chromium is not responsive")
        node = bundle / "playwright" / "driver" / "node.exe"
        result = subprocess.run([str(node), str(bundle / "plugin" / "dist" / "cli.js"), "--help"],
                                capture_output=True, timeout=15, check=True)
        if not result.stdout:
            raise RuntimeError("Bundled plugin CLI did not produce help")
        checks = {"ok": True, "webview": bool(webview and edgechromium and webview_backend),
                  "aes256": len(AESGCM.generate_key(256)) == 32, "chromium": True, "node_cli": True}
    except Exception as exc:
        checks = {"ok": False, "error": str(exc)}
    report.write_text(json.dumps(checks), encoding="utf-8")
    return 0 if checks["ok"] else 1
