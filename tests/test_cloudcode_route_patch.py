import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "gui-manager"))
from cloudcode_route_patch import patch_auth_plugin_transport, restore_auth_plugin_transport


PLUGIN_SOURCE = '''function getHttpsProxy(url) {
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
    }
  } catch {}
}
const shouldRetryEndpoint = geoBlockedLocation || response.status === 403 || response.status === 404 || response.status >= 500;
'''


class CloudCodeRoutePatchTests(unittest.TestCase):
    def test_patches_only_cloud_code_host_selection_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            plugin = Path(directory) / "node_modules/@cortexkit/opencode-antigravity-auth/dist/server.js"
            plugin.parent.mkdir(parents=True)
            plugin.write_text(PLUGIN_SOURCE, encoding="utf-8")

            self.assertTrue(patch_auth_plugin_transport(Path(directory)))
            patched = plugin.read_text(encoding="utf-8")
            self.assertIn("gateHost ? hubRoutePort : vlessPort", patched)
            self.assertIn("url.hostname === 'daily-cloudcode-pa.googleapis.com'", patched)
            self.assertIn("url.hostname === 'cloudcode-pa.googleapis.com'", patched)
            self.assertTrue(plugin.with_suffix(".js.hub-route.bak").exists())
            self.assertTrue(patch_auth_plugin_transport(Path(directory)))

            restore_auth_plugin_transport(Path(directory))
            self.assertEqual(plugin.read_text(encoding="utf-8"), PLUGIN_SOURCE)

    def test_does_not_claim_success_when_plugin_pattern_changed(self):
        with tempfile.TemporaryDirectory() as directory:
            plugin = Path(directory) / "node_modules/@cortexkit/opencode-antigravity-auth/dist/server.js"
            plugin.parent.mkdir(parents=True)
            plugin.write_text("function getHttpsProxy() {}", encoding="utf-8")
            self.assertFalse(patch_auth_plugin_transport(Path(directory)))


if __name__ == "__main__":
    unittest.main()
