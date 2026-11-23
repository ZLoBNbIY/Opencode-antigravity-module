import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "gui-manager"))
from cloudcode_route_patch import patch_auth_plugin_transport, restore_auth_plugin_transport


PLUGIN_SOURCE = '''function getHttpsProxy(url) {
  if (url.protocol !== "https:" || noProxyIncludes(url.hostname))
    return void 0;
  try {
    const configPath = getUserConfigPath();
    if (existsSync5(configPath)) {
      const parsed = JSON.parse(readFileSync2(configPath, "utf-8"));
      if (parsed.vless_enabled && parsed.vless_url) {
        const vlessPort = Number(parsed.vless_http_port) > 0 ? Number(parsed.vless_http_port) : 10879;
        return new URL(`http://127.0.0.1:${vlessPort}`);
      }
      if (parsed.proxy && typeof parsed.proxy === "string" && parsed.proxy.trim()) {
        return new URL(parsed.proxy.trim());
      }
    }
  } catch {}
  const rawProxy = process.env.HTTPS_PROXY || process.env.https_proxy || process.env.ALL_PROXY || process.env.all_proxy;
  if (!rawProxy)
    return void 0;
  try {
    return new URL(rawProxy);
  } catch {
    return void 0;
  }
}
const shouldRetryEndpoint = geoBlockedLocation || response.status === 403 || response.status === 404 || response.status >= 500;
'''

LEGACY_SOURCE = PLUGIN_SOURCE.replace(
    "        const vlessPort",
    "        const hubRoutePort = 10880;\n"
    "        const gateHost = url.hostname === 'daily-cloudcode-pa.googleapis.com' || url.hostname.endsWith('.googleapis.com');\n"
    "        const vlessPort",
).replace("${vlessPort}", "${gateHost ? hubRoutePort : vlessPort}")


def node_executable():
    if node := shutil.which("node"):
        return node
    try:
        from playwright._impl._driver import compute_driver_executable
        node, _ = compute_driver_executable()
    except ImportError:
        return None
    return node if Path(node).is_file() else None


def execute_selector(node, selector, cases):
    script = selector + r'''
const getUserConfigPath = () => "fixture.json";
const existsSync5 = () => config !== null;
let config;
let exclude;
const noProxyIncludes = () => exclude;
const readFileSync2 = () => typeof config === "string" ? config : "\uFEFF" + JSON.stringify(config);
const process = {env: {}};
const outputs = [];
for (const [saved, env, noProxy, url] of JSON.parse(require("node:fs").readFileSync(0, "utf8"))) {
  config = saved;
  process.env = env;
  exclude = noProxy;
  outputs.push(getHttpsProxy(new URL(url))?.origin ?? null);
}
console.log(JSON.stringify(outputs));
'''
    return subprocess.run([node, "-e", script], input=json.dumps(cases), capture_output=True, text=True, timeout=10)


def write_version(plugin, version="3.0.0"):
    (plugin.parent.parent / "package.json").write_text(json.dumps({
        "name": "@cortexkit/opencode-antigravity-auth",
        "version": version,
    }), encoding="utf-8")


class CloudCodeRoutePatchTests(unittest.TestCase):
    def test_patches_unmodified_and_legacy_selectors_idempotently(self):
        with tempfile.TemporaryDirectory() as directory:
            dist = Path(directory) / "node_modules/@cortexkit/opencode-antigravity-auth/dist"
            dist.mkdir(parents=True)
            server, index = dist / "server.js", dist / "index.js"
            server.write_bytes(LEGACY_SOURCE.encode("utf-8"))
            index.write_bytes(PLUGIN_SOURCE.encode("utf-8"))
            write_version(server)
            # An earlier migration already saved the true original.
            server.with_suffix(".js.hub-route.bak").write_text(PLUGIN_SOURCE, encoding="utf-8")

            self.assertTrue(patch_auth_plugin_transport(Path(directory)))
            patched = server.read_text(encoding="utf-8")
            self.assertIn("parsed.provider_routes?.google", patched)
            self.assertNotIn("gateHost", patched)
            self.assertEqual(patched, index.read_text(encoding="utf-8"))
            self.assertTrue(patch_auth_plugin_transport(Path(directory)))
            self.assertEqual(patched, server.read_text(encoding="utf-8"))

            result = restore_auth_plugin_transport(Path(directory))
            self.assertEqual(result, {"restored": [str(index.resolve())], "skipped": [str(server.resolve())]})
            self.assertEqual(server.read_text(encoding="utf-8"), patched)
            self.assertEqual(index.read_text(encoding="utf-8"), PLUGIN_SOURCE)

    @unittest.skipUnless(node_executable(), "Node is needed to execute the patched selector")
    def test_explicit_google_routes_override_proxy_environment_only_for_google(self):
        with tempfile.TemporaryDirectory() as directory:
            plugin = Path(directory) / "node_modules/@cortexkit/opencode-antigravity-auth/dist/server.js"
            plugin.parent.mkdir(parents=True)
            plugin.write_text(LEGACY_SOURCE, encoding="utf-8")
            self.assertTrue(patch_auth_plugin_transport(Path(directory)))
            script = plugin.read_text(encoding="utf-8").split("\nconst shouldRetryEndpoint", 1)[0]
            cloudcode = "https://daily-cloudcode-pa.googleapis.com/v1internal:streamGenerateContent"
            env = {"HTTPS_PROXY": "http://env-proxy.test:3128"}
            dns = {"provider_routes": {"google": "dns"}, "vless_enabled": False}
            vless = {"vless_enabled": True, "vless_url": "fixture", "vless_http_port": 20809}
            configured = {"proxy": "http://config-proxy.test:3128"}
            dispatcher = "http://127.0.0.1:10880"
            cases = [
                (({"provider_routes": {"google": mode}}, {}, False, cloudcode), dispatcher)
                for mode in ("default", "auto", "direct", "vless", "proxy", "dns")
            ] + [
                (({**dns, **configured}, env, True, cloudcode), dispatcher),
                ((dns, {}, False, "https://gemini.google/v1"), dispatcher),
                ((dns, env, False, "https://googleapis.com.example.test/"), env["HTTPS_PROXY"]),
                ((dns, env, True, "https://example.test/"), None),
                ((dns, env, False, cloudcode.replace("https:", "http:")), None),
                ((vless, env, False, cloudcode), "http://127.0.0.1:20809"),
                (({**vless, "provider_routes": {"google": "proxy"}}, env, False, "https://example.test/"),
                 "http://127.0.0.1:20809"),
                ((vless, env, True, cloudcode), None),
                ((configured, env, False, cloudcode), configured["proxy"]),
                (({"provider_routes": {"google": "invalid"}}, env, False, cloudcode), env["HTTPS_PROXY"]),
                (("{bad JSON", env, False, cloudcode), env["HTTPS_PROXY"]),
                ((None, env, True, cloudcode), None),
                ((None, env, False, cloudcode), env["HTTPS_PROXY"]),
            ]
            result = execute_selector(node_executable(), script, [case for case, _ in cases])
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout), [expected for _, expected in cases])

    def test_does_not_claim_success_when_plugin_pattern_changed(self):
        with tempfile.TemporaryDirectory() as directory:
            plugin = Path(directory) / "node_modules/@cortexkit/opencode-antigravity-auth/dist/server.js"
            plugin.parent.mkdir(parents=True)
            source = "function getHttpsProxy() {\n  const hubRoutePort = 10880;\n}\n" + PLUGIN_SOURCE.splitlines()[-1]
            plugin.write_text(source, encoding="utf-8")
            self.assertFalse(patch_auth_plugin_transport(Path(directory)))
            self.assertEqual(plugin.read_text(encoding="utf-8"), source)

    def test_patches_404_retry_without_geoblocked_prefix(self):
        with tempfile.TemporaryDirectory() as directory:
            plugin = Path(directory) / "node_modules/@cortexkit/opencode-antigravity-auth/dist/server.js"
            plugin.parent.mkdir(parents=True)
            plugin.write_text(
                PLUGIN_SOURCE.replace("geoBlockedLocation || ", ""),
                encoding="utf-8",
            )
            self.assertTrue(patch_auth_plugin_transport(Path(directory)))
            patched = plugin.read_text(encoding="utf-8")
            self.assertIn("/* no retry on 404 */", patched)
            self.assertNotIn("response.status === 404", patched)

    def test_restore_is_exact_and_only_undoes_transport(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plugin = root / "node_modules/@cortexkit/opencode-antigravity-auth/dist/server.js"
            plugin.parent.mkdir(parents=True)
            write_version(plugin)
            original = ("\ufeff" + PLUGIN_SOURCE).replace("\n", "\r\n").encode("utf-8")
            plugin.write_bytes(original)
            unrelated = plugin.with_name("server.js.hub-prompt.bak")
            unrelated.write_bytes(b"unrelated backup")
            other_package = root / "node_modules/other-plugin/dist"
            other_package.mkdir(parents=True)
            (other_package / "index.js").write_bytes(b"keep")
            (other_package / "index.js.hub-route.bak").write_bytes(b"not this package")
            self.assertTrue(patch_auth_plugin_transport(root))
            concurrent_edit = b"// a later nontransport patch\r\n"
            plugin.write_bytes(plugin.read_bytes() + concurrent_edit)

            self.assertEqual(restore_auth_plugin_transport(root), {"restored": [str(plugin.resolve())], "skipped": []})
            self.assertEqual(plugin.read_bytes(), original + concurrent_edit)
            self.assertEqual(unrelated.read_bytes(), b"unrelated backup")
            self.assertEqual((other_package / "index.js").read_bytes(), b"keep")
            self.assertFalse(plugin.with_suffix(".js.hub-route.bak").exists())
            self.assertFalse(plugin.with_suffix(".js.hub-route.bak.json").exists())

    def test_restore_leaves_changed_versions_and_conflicting_transport_untouched(self):
        for conflict in ("version", "selector", "backup"):
            with self.subTest(conflict=conflict), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                plugin = root / "node_modules/@cortexkit/opencode-antigravity-auth/dist/server.js"
                plugin.parent.mkdir(parents=True)
                write_version(plugin)
                plugin.write_bytes(PLUGIN_SOURCE.encode("utf-8"))
                self.assertTrue(patch_auth_plugin_transport(root))
                backup = plugin.with_suffix(".js.hub-route.bak")
                if conflict == "version":
                    write_version(plugin, "3.0.20")
                elif conflict == "selector":
                    plugin.write_bytes(plugin.read_bytes().replace(b"10880", b"12345"))
                else:
                    backup.write_bytes(b"corrupted")
                before = plugin.read_bytes()
                self.assertEqual(restore_auth_plugin_transport(root), {"restored": [], "skipped": [str(plugin.resolve())]})
                self.assertEqual(plugin.read_bytes(), before)
                self.assertTrue(backup.exists())


if __name__ == "__main__":
    unittest.main()
