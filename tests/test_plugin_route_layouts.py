"""Regression tests for newer installed plugin bundle layouts."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "gui-manager"))
from cloudcode_route_patch import (
    patch_auth_plugin_transport,
    get_prompt_sanitizer_status,
)


# Newer bundles keep the protocol/NO_PROXY guard below the try/catch instead of
# at the top of getHttpsProxy. This is the layout shipped with the reported bug.
NEW_LAYOUT = '''function getHttpsProxy(url) {
  try {
    const configPath = getUserConfigPath();
    if (existsSync5(configPath)) {
      const parsed = JSON.parse(readFileSync2(configPath, "utf-8"));
      if (parsed.vless_enabled && parsed.vless_url) {
        const hubRoutePort = 10880;
        const gateHost = url.hostname.endsWith('.googleapis.com') || url.hostname.endsWith('.google.com');
        const vlessPort = Number(parsed.vless_http_port) > 0 ? Number(parsed.vless_http_port) : 10879;
        return new URL(`http://127.0.0.1:${gateHost ? hubRoutePort : vlessPort}`);
      }
      if (parsed.proxy && typeof parsed.proxy === "string" && parsed.proxy.trim()) {
        return new URL(parsed.proxy.trim());
      }
    }
  } catch {}
  if (url.protocol !== "https:" || noProxyIncludes(url.hostname))
    return void 0;
  const rawProxy = process.env.HTTPS_PROXY || process.env.https_proxy || process.env.ALL_PROXY || process.env.all_proxy;
  if (!rawProxy)
    return void 0;
  try {
    return new URL(rawProxy);
  } catch {
    return void 0;
  }
}
'''


class PluginRouteLayoutTests(unittest.TestCase):
    def _bundle(self, directory, source):
        dist = Path(directory) / "node_modules/@cortexkit/opencode-antigravity-auth/dist"
        dist.mkdir(parents=True)
        plugin = dist / "server.js"
        plugin.write_text(source, encoding="utf-8")
        return plugin

    def test_patches_new_layout_below_try_catch(self):
        with tempfile.TemporaryDirectory() as directory:
            plugin = self._bundle(directory, NEW_LAYOUT)
            changed = []
            self.assertTrue(patch_auth_plugin_transport(Path(directory), changed_files=changed))
            patched = plugin.read_text(encoding="utf-8")
            self.assertIn("const hubGoogleRoute = parsed.provider_routes?.google;", patched)
            self.assertIn('return new URL("http://127.0.0.1:10880");', patched)
            self.assertIn(str(plugin.resolve()), changed)
            # Idempotent on a second click.
            changed.clear()
            self.assertTrue(patch_auth_plugin_transport(Path(directory), changed_files=changed))
            self.assertEqual(plugin.read_text(encoding="utf-8"), patched)
            self.assertEqual(changed, [])

    def test_patches_both_layouts_together(self):
        with tempfile.TemporaryDirectory() as directory:
            dist = Path(directory) / "node_modules/@cortexkit/opencode-antigravity-auth/dist"
            dist.mkdir(parents=True)
            (dist / "server.js").write_text(NEW_LAYOUT, encoding="utf-8")
            old = NEW_LAYOUT.replace(
                "  try {\n    const configPath",
                '  if (url.protocol !== "https:" || noProxyIncludes(url.hostname))\n'
                "    return void 0;\n  try {\n    const configPath",
            ).replace(
                '  if (url.protocol !== "https:" || noProxyIncludes(url.hostname))\n    return void 0;\n  const rawProxy',
                '  const rawProxy',
            )
            (dist / "index.js").write_text(old, encoding="utf-8")
            self.assertTrue(patch_auth_plugin_transport(Path(directory)))
            for name in ("server.js", "index.js"):
                self.assertIn("const hubGoogleRoute", (dist / name).read_text(encoding="utf-8"))

    def test_full_status_reports_active_copies_not_pending(self):
        with tempfile.TemporaryDirectory() as directory:
            dist = Path(directory) / "node_modules/@cortexkit/opencode-antigravity-auth/dist"
            dist.mkdir(parents=True)
            source = (
                "function sanitizeRequestPayloadForAntigravity(payload) {\n"
                "function sanitizeAntigravitySystemInstruction(payload) {}\n"
                "sanitizeAntigravitySystemInstruction(requestPayload);\n"
                'getDynamicWireModel("antigravity-gemini-4-hydrogen") || "gemini-4-hydrogen-sonar";\n'
                "/* hub-identity-fix:v1 */\n"
                'var AGY_CLIENT_KIND = "hub";\n'
            )
            (dist / "server.js").write_text(source, encoding="utf-8")
            before = get_prompt_sanitizer_status(Path(directory), full=True)
            self.assertEqual(before["state"], "pending")
            self.assertEqual(before["pending"], 1)
            self.assertIn("0 из 1", before["message"])
            (dist / "server.js").write_text(
                source + 'const hubGoogleRoute = parsed.provider_routes?.google;\n', encoding="utf-8")
            self.assertEqual(get_prompt_sanitizer_status(Path(directory), full=True)["state"], "pending")
            shipped = Path(__file__).resolve().parent.parent / "plugin" / "dist" / "server.js"
            (dist / "server.js").write_bytes(shipped.read_bytes())
            self.assertTrue(patch_auth_plugin_transport(Path(directory)))
            after = get_prompt_sanitizer_status(Path(directory), full=True)
            self.assertEqual(after["state"], "patched")
            self.assertEqual(after["patched"], 1)


if __name__ == "__main__":
    unittest.main()
