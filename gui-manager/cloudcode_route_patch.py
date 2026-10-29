from pathlib import Path


def patch_auth_plugin_transport(plugin_cache: Path | None = None) -> bool:
    """Route Cloud Code through Hub while preserving the plugin's other VLESS routes."""
    import re

    root = plugin_cache or (Path.home() / ".cache" / "opencode" / "npm")
    candidates = list(root.glob("**/@cortexkit/opencode-antigravity-auth/dist/server.js"))
    if not candidates:
        return False
    patched = False
    for path in candidates:
        try:
            source = path.read_text(encoding="utf-8")
            marker = "const hubRoutePort = 10880;"
            if marker in source:
                continue
            pattern = re.compile(
                r"const vlessPort = Number\(parsed\.vless_http_port\) > 0 \? Number\(parsed\.vless_http_port\) : 10879;\s*"
                r"return new URL\(`http://127\.0\.0\.1:\$\{vlessPort\}`\);"
            )
            replacement = (
                "const hubRoutePort = 10880;\n"
                "        const gateHost = url.hostname === 'daily-cloudcode-pa.googleapis.com' || "
                "url.hostname === 'cloudcode-pa.googleapis.com';\n"
                "        const vlessPort = Number(parsed.vless_http_port) > 0 ? Number(parsed.vless_http_port) : 10879;\n"
                "        return new URL(`http://127.0.0.1:${gateHost ? hubRoutePort : vlessPort}`);"
            )
            updated, count = pattern.subn(replacement, source, count=1)
            if count:
                backup = path.with_suffix(path.suffix + ".hub-route.bak")
                if not backup.exists():
                    backup.write_text(source, encoding="utf-8")
                path.write_text(updated, encoding="utf-8")
                patched = True
        except OSError:
            continue
    return patched or any("const hubRoutePort = 10880;" in p.read_text(encoding="utf-8")
                          for p in candidates if p.exists())


def restore_auth_plugin_transport(plugin_cache: Path | None = None) -> None:
    """Restore patched plugin files before a plugin upgrade or Hub removal."""
    root = plugin_cache or (Path.home() / ".cache" / "opencode" / "npm")
    for backup in root.glob("**/server.js.hub-route.bak"):
        target = backup.with_name("server.js")
        try:
            target.write_text(backup.read_text(encoding="utf-8"), encoding="utf-8")
            backup.unlink()
        except OSError:
            pass


def main():
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "restore":
        restore_auth_plugin_transport()
    else:
        print("patched" if patch_auth_plugin_transport() else "no auth plugin found or patch failed")


if __name__ == "__main__":
    main()
