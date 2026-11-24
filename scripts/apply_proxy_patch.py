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

import json
import os
import secrets
from pathlib import Path

TARGET_PLUGIN_NAMES = {
    "@cortexkit/opencode-antigravity-auth",
    "opencode-antigravity-auth",
    "opencode-antigravity-multi-auth",
}


def _is_target_plugin_dir(pkg_dir: Path) -> bool:
    manifest = pkg_dir / "package.json"
    if manifest.is_file() and not manifest.is_symlink():
        try:
            data = json.loads(manifest.read_text(encoding="utf-8-sig"))
            if isinstance(data, dict) and isinstance(data.get("name"), str):
                return data["name"] in TARGET_PLUGIN_NAMES
        except (OSError, ValueError):
            return False
    return (
        (pkg_dir.name == "opencode-antigravity-auth" and pkg_dir.parent.name == "@cortexkit")
        or pkg_dir.name == "opencode-antigravity-multi-auth"
    )


def _atomic_write_text(path: Path, text: str) -> None:
    tmp = path.with_name(f"{path.name}.{secrets.token_hex(6)}.tmp")
    fd = os.open(
        tmp,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0),
        0o600,
    )
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(text.encode("utf-8"))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


home = Path.home()
candidates = [
    Path(__file__).resolve().parent.parent / "plugin",
    home / "Opencode-antigravity-module" / "plugin",
    home / ".cache" / "opencode" / "packages",
    home / ".cache" / "opencode" / "npm",
]

roots = [c for c in candidates if c.exists()]

patched = 0
for root in roots:
    if (root / "dist").is_dir() and _is_target_plugin_dir(root):
        files = [
            root / "dist" / name
            for name in ("index.js", "server.js")
            if (root / "dist" / name).is_file() and not (root / "dist" / name).is_symlink()
        ]
    else:
        files = []
        for base, dirs, names in os.walk(root):
            if base.count(os.sep) - len(str(root).split(os.sep)) > 8:
                dirs[:] = []
                continue
            base_path = Path(base)
            if base_path.name != "dist" or not _is_target_plugin_dir(base_path.parent):
                continue
            for name in ("index.js", "server.js"):
                target = base_path / name
                if name in names and target.is_file() and not target.is_symlink():
                    files.append(target)

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
            _atomic_write_text(f, text)
            patched += 1
            print(f"PATCHED {f}")
        else:
            print(f"TARGET NOT FOUND {f}")

print(f"Done. {patched} file(s) patched.")
