"""Offline capability check for a Windows distribution, without starting Hub."""

import json
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory


def check_plugin_recovery():
    from cloudcode_route_patch import (_local_plugin_dist_dir, get_identity_fix_status, get_prompt_sanitizer_status,
                                       patch_auth_plugin_transport, sync_local_plugin_bundles)

    source = _local_plugin_dist_dir()
    if source is None:
        raise RuntimeError("The packaged server.js or index.js recovery resource is missing")
    version = json.loads((source.parent / "package.json").read_text(encoding="utf-8"))["version"]
    with TemporaryDirectory() as tmp:
        cache = Path(tmp)
        if get_identity_fix_status(cache)["state"] != "missing":
            raise RuntimeError("Recovery resources were mistaken for an installed plugin")
        dist = cache / "node_modules" / "@cortexkit" / "opencode-antigravity-auth" / "dist"
        dist.mkdir(parents=True)
        (dist.parent / "package.json").write_text(json.dumps({"version": version}), encoding="utf-8")
        for name in ("server.js", "index.js", "cli.js"):
            (dist / name).write_text("// unpatched fixture\n", encoding="utf-8")
        result = sync_local_plugin_bundles(cache)
        if len(result["copied"]) != 3 or result.get("failed"):
            raise RuntimeError("Could not restore the packaged plugin bundles")
        if any(status(cache)["state"] != "patched"
               for status in (get_prompt_sanitizer_status, get_identity_fix_status)):
            raise RuntimeError("Restored plugin is missing patch markers")
        if not patch_auth_plugin_transport(cache):
            raise RuntimeError("Restored plugin does not support the Hub route patch")
        if get_prompt_sanitizer_status(cache, full=True)["state"] != "patched":
            raise RuntimeError("Full patch status does not match the repaired plugin")
        if sync_local_plugin_bundles(cache)["copied"]:
            raise RuntimeError("A repeat recovery unexpectedly rewrote the patched bundle")


def check_bundle(bundle, report):
    stage = "dependencies"
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        from playwright.sync_api import sync_playwright
        import webview
        import webview_backend
        from webview.http import start_server
        from webview.platforms import edgechromium

        stage = "frontend"
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
        stage = "plugin recovery"
        check_plugin_recovery()
        stage = "plugin CLI"
        node = bundle / "playwright" / "driver" / "node.exe"
        result = subprocess.run([str(node), str(bundle / "plugin" / "dist" / "cli.js"), "--help"],
                                capture_output=True, timeout=15, check=True)
        if not result.stdout:
            raise RuntimeError("Bundled plugin CLI did not produce help")
        checks = {"ok": True, "webview": bool(webview and edgechromium and webview_backend),
                   "aes256": len(AESGCM.generate_key(256)) == 32, "chromium": True, "node_cli": True,
                   "plugin_recovery": True}
    except Exception as exc:
        checks = {"ok": False, "stage": stage, "error_type": type(exc).__name__, "error": str(exc)}
    report.write_text(json.dumps(checks), encoding="utf-8")
    return 0 if checks["ok"] else 1
