"""Regression tests for plugin 3.1.x bundles and update-drift protection."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "gui-manager"))
sys.path.insert(0, str(ROOT / "tests"))

import cloudcode_route_patch as patcher
import hub_paths
import opencode_config


V2_PROXY = '''function getHttpsProxy(url) {
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

V2_GEMINI = '''function getTieredAntigravityModel(routes, tier) {
  return tier ? routes.byTier[tier] ?? routes.defaultModel : routes.defaultModel;
}
function getGeminiHydrogenAntigravityModel(tier) {
  return getTieredAntigravityModel({
    defaultModel: "gemini-4-hydrogen-high",
    byTier: {
      low: "gemini-4-hydrogen-low",
      medium: "gemini-4-hydrogen-medium",
      high: "gemini-4-hydrogen-high",
      xhigh: "gemini-4-hydrogen-xhigh"
    }
  }, tier);
}
function getGeminiNeonAntigravityModel(tier) {
  return getTieredAntigravityModel({
    defaultModel: "gemini-4-neon-high",
    byTier: {
      low: "gemini-4-neon-low",
      medium: "gemini-4-neon-medium",
      high: "gemini-4-neon-high",
      xhigh: "gemini-4-neon-xhigh"
    }
  }, tier);
}
function getGeminiCarbonAntigravityModel(tier) {
  return getTieredAntigravityModel({
    defaultModel: "gemini-4-carbon-medium",
    byTier: {
      low: "gemini-4-carbon-low",
      medium: "gemini-4-carbon-medium",
      high: "gemini-4-carbon-high"
    }
  }, tier);
}
function getGeminiArgonAntigravityModel(tier) {
  return getTieredAntigravityModel({
    defaultModel: "gemini-4-argon-medium",
    byTier: {
      low: "gemini-4-argon-low",
      medium: "gemini-4-argon-medium",
      high: "gemini-4-argon-high"
    }
  }, tier);
}
'''

V2_SOURCE = (V2_PROXY + "\n" + V2_GEMINI + "\n" + patcher.PROMPT_FIX_BLOCK
             + "function sanitizeRequestPayloadForAntigravity(payload) {\n"
             + patcher.PROMPT_FIX_CALL_ANCHOR + "\n        " + patcher.PROMPT_FIX_CALL + "\n"
             + "  return payload;\n}\n"
             + "const shouldRetryEndpoint = response.status === 404 || response.status >= 500;\n")


def write_bundle(root: Path, name: str, source: str) -> Path:
    target = root / "node_modules" / "@cortexkit" / "opencode-antigravity-auth" / "dist" / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(source, encoding="utf-8")
    (target.parent.parent / "package.json").write_text(
        json.dumps({"name": patcher.PLUGIN_NAME, "version": "3.1.13"}), encoding="utf-8")
    return target


class PluginV2LayoutTests(unittest.TestCase):
    def test_self_heal_brings_v2_bundle_to_patched_state(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            server = write_bundle(root, "server.js", V2_SOURCE)
            index = write_bundle(root, "index.js", V2_SOURCE)
            self.assertFalse(patcher.verify_plugin_health(root)["ok"])

            result = patcher.self_heal_plugin(root)

            self.assertEqual(result["state"], "healed", result)
            self.assertTrue(result["ok"])
            health = patcher.verify_plugin_health(root)
            self.assertTrue(health["ok"], health)
            self.assertEqual(patcher.get_prompt_sanitizer_status(root, full=True)["state"], "patched")
            for path in (server, index):
                text = path.read_text(encoding="utf-8")
                self.assertIn(patcher.FORCED_GOOGLE_ROUTE_V2, text)
                self.assertIn(patcher.RETRY_404_V2_FIXED, text)
                self.assertIn(patcher.GEMINI4_FIX_MARKER_V2, text)
                self.assertIn('getDynamicWireModel("antigravity-gemini-4-neon")', text)
            self.assertEqual(patcher.self_heal_plugin(root)["state"], "already_healthy")

    def test_unknown_layout_reports_unsupported_instead_of_silent_pending(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_bundle(root, "server.js", "function totallyDifferent() { return 1; }\n")
            result = patcher.self_heal_plugin(root)
            self.assertEqual(result["state"], "unsupported")
            self.assertFalse(result["ok"])
            self.assertIn("server.js", " ".join(result["reasons"]))


class UpdateGuardTests(unittest.TestCase):
    def test_guard_adds_auto_update_false_to_both_copies(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            central, mirror = root / "central.json", root / "mirror.json"
            central.write_bytes(b'{"setting":true}')
            mirror.write_bytes(b'{\r\n  "setting": true\r\n}\r\n')
            result = hub_paths.ensure_auto_update_disabled([central, mirror])
            self.assertTrue(result["ok"])
            for path in (central, mirror):
                data = json.loads(path.read_text(encoding="utf-8"))
                self.assertIs(data["auto_update"], False)
            self.assertEqual(hub_paths.ensure_auto_update_disabled([central, mirror])["updated"], [])

    def test_guard_replaces_true_without_reserializing(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text('// keep me\n{\n  "auto_update": true,\n  "x": 1\n}\n', encoding="utf-8")
            hub_paths.ensure_auto_update_disabled([path])
            text = path.read_text(encoding="utf-8")
            self.assertIn("// keep me", text)
            self.assertIn('"auto_update": false', text)

    def test_pin_rewrites_latest_without_touching_other_plugins(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "opencode.json"
            path.write_text(json.dumps({
                "plugins": ["@cortexkit/opencode-antigravity-auth@latest", "./local"]
            }, indent=2), encoding="utf-8")
            changed, message = opencode_config.ensure_plugin_pin("3.0.0", path)
            self.assertTrue(changed, message)
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(data["plugins"],
                             ["@cortexkit/opencode-antigravity-auth@3.0.0", "./local"])


if __name__ == "__main__":
    unittest.main()
