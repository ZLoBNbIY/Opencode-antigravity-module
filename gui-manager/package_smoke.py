"""Offline capability check for a Windows distribution, without starting Hub."""

import json
import subprocess


def check_bundle(bundle, report):
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        from playwright.sync_api import sync_playwright
        import webview
        import webview_backend
        from webview.http import start_server
        from webview.platforms import edgechromium

        for name in ("index.html", "app.js", "style.css", "icon.png"):
            if not (bundle / "web" / name).is_file():
                raise FileNotFoundError(f"web/{name}")
        if not (bundle / "icon.ico").is_file():
            raise FileNotFoundError("icon.ico")
        # Match the real window: pywebview serves only the directory containing index.html.
        address, _, _ = start_server([str(bundle / "web" / "index.html")])
        with sync_playwright() as playwright:
            with playwright.chromium.launch(channel="chromium") as browser:
                page = browser.new_page(reduced_motion="no-preference")
                page.goto(f"{address}index.html", timeout=15000)
                if page.title() != "AI HUB":
                    raise RuntimeError("Bundled AI HUB page did not load")
                logo = page.locator(".brand-icon")
                if not logo.evaluate("(img) => img.complete && img.naturalWidth > 0"):
                    raise RuntimeError("Sidebar logo did not load")
                if not logo.evaluate("""(img) => img.getAnimations().some(
                    (animation) => animation.animationName === 'logo-breathe'
                        && animation.playState === 'running'
                        && animation.effect.getTiming().iterations === Infinity
                )"""):
                    raise RuntimeError("Sidebar logo animation is not running")
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
