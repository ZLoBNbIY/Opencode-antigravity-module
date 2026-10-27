"""One-off helper: apply the getHttpsProxy VLESS-priority patch to all plugin copies.

Mirrors the patch added to scripts/patch_plugin.mjs (used by auto_updater when
Node.js is available). Safe to re-run: patches only replace the stock snippet.
"""

TARGET = '''function getHttpsProxy(url) {
  try {
    const configPath = getUserConfigPath();
    if (existsSync5(configPath)) {
      const parsed = JSON.parse(readFileSync2(configPath, "utf-8"));
      if (parsed.proxy && typeof parsed.proxy === "string" && parsed.proxy.trim()) {
        return new URL(parsed.proxy.trim());
      }
    }
  } catch {}'''

REPL = '''function getHttpsProxy(url) {
  try {
    const configPath = getUserConfigPath();
    if (existsSync5(configPath)) {
      const parsed = JSON.parse(readFileSync2(configPath, "utf-8"));
      if (parsed.vless_enabled && parsed.vless_url) {
        if (noProxyIncludes(url.hostname))
          return void 0;
        const vlessPort = Number(parsed.vless_http_port) > 0 ? Number(parsed.vless_http_port) : 10879;
        return new URL(`http://127.0.0.1:${vlessPort}`);
      }
      if (parsed.proxy && typeof parsed.proxy === "string" && parsed.proxy.trim()) {
        return new URL(parsed.proxy.trim());
      }
    }
  } catch {}'''

import os
from pathlib import Path

home = Path.home()
candidates = [
    Path(r"D:\Opencode-antigravity-module") / "plugin",
    home / "Opencode-antigravity-module" / "plugin",
    home / ".cache" / "opencode" / "packages",
    home / ".cache" / "opencode" / "npm",
]

roots = [c for c in candidates if c.exists()]

patched = 0
for root in roots:
    if (root / "dist").exists():
        files = [root / "dist" / name for name in ("index.js", "server.js")]
    else:
        files = []
        for base, dirs, names in os.walk(root):
            if base.count(os.sep) - len(str(root).split(os.sep)) > 8:
                dirs[:] = []
                continue
            for name in ("index.js", "server.js"):
                if (Path(base) / "dist").name == "dist" and name in names:
                    files.append(Path(base) / name)

    for f in files:
        try:
            text = f.read_text(encoding="utf-8")
        except Exception as e:
            print(f"SKIP {f}: {e}")
            continue
        marker = "parsed.vless_enabled && parsed.vless_url"
        if marker in text:
            print(f"ALREADY {f}")
            continue
        if TARGET in text:
            text = text.replace(TARGET, REPL)
            f.write_text(text, encoding="utf-8")
            patched += 1
            print(f"PATCHED {f}")
        else:
            print(f"TARGET NOT FOUND {f}")

print(f"Done. {patched} file(s) patched.")
