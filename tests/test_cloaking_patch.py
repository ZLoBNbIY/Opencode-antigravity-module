"""Offline tests for the narrow Antigravity request-cloaking layer."""
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(ROOT / "gui-manager"))

from test_cloudcode_route_patch import PLUGIN_SOURCE, node_executable, write_version
from test_quota_breaker_patch import EXECUTOR_FIXTURE, EXECUTOR_FIXTURE_V2
import cloudcode_route_patch as patcher


def plan(base: str, optin: bool) -> str:
    with patch.dict(os.environ, {patcher.CLOAKING_ENV: "1" if optin else "0"}):
        return patcher._plan_cloaking(base)


def quota_patched(base: str) -> str:
    with patch.dict(os.environ, {patcher.CLOAKING_ENV: "0"}):
        return patcher._plan_quota_breaker(base)


BASE_V30 = quota_patched(PLUGIN_SOURCE + EXECUTOR_FIXTURE)
BASE_V31 = quota_patched(PLUGIN_SOURCE + EXECUTOR_FIXTURE_V2)


class CloakingPlannerTests(unittest.TestCase):
    def test_strict_idempotence_for_both_profiles_and_both_flags(self):
        for name, base in (("3.0", BASE_V30), ("3.1", BASE_V31)):
            for optin in (False, True):
                with self.subTest(profile=name, optin=optin):
                    edited = plan(base, optin)
                    self.assertIsNotNone(edited)
                    self.assertEqual(edited.count(patcher.CLOAKING_MARKER), 1)
                    self.assertEqual(edited.count(patcher.CLOAKING_END_MARKER), 1)
                    self.assertEqual(plan(edited, optin), edited)
                    crlf = edited.replace("\n", "\r\n")
                    self.assertEqual(plan(crlf, optin), crlf)
                    self.assertIsNone(plan(edited.replace(patcher.CLOAKING_END_MARKER, ""), optin))
                    self.assertIsNone(plan(base + base, optin))
                    # Base patches stay exactly as they were.
                    self.assertEqual(patcher._plan_quota_breaker(edited), edited)
                    self.assertIsNotNone(patcher._route_edits(edited))

    def test_flag_change_is_a_visible_transition_not_a_silent_noop(self):
        off = plan(BASE_V31, False)
        on = plan(BASE_V31, True)
        self.assertNotEqual(off, on)
        self.assertEqual(plan(on, False), off)
        self.assertEqual(plan(off, True), on)

    def test_optin_ua_edits_are_preflighted(self):
        base = (BASE_V31 + "\nfunction getGeminiNeonAntigravityModel(tier) {}\n"
                + "\n".join(before for before, _ in patcher.CLOAKING_UA_V2_EDITS))
        on = plan(base, True)
        self.assertIn('AGY_CLIENT_KIND = "hub";', on)
        self.assertNotIn('auth_method=${authMethod}', on)
        self.assertNotIn('AGY_CLI_VERSION = "1.5.8";', on)
        self.assertEqual(plan(on, True), on)
        self.assertEqual(plan(on, False), plan(base, False))

    def test_unknown_layout_is_unsupported_even_when_base_is_ok(self):
        with patch.dict(os.environ, {patcher.CLOAKING_ENV: "0"}):
            self.assertIsNone(patcher._plan_cloaking("function unrelated() {}\n"))
        # Bare exhaustion inside the breaker must not be applied without it.
        broken = BASE_V30.replace("function createHubQuotaBreaker() {", "function oldBreaker() {")
        self.assertIsNone(plan(broken, False))

    def test_installed_copies_report_unsupported_separately(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            dist = root / "node_modules" / patcher.PLUGIN_NAME / "dist"
            dist.mkdir(parents=True)
            index, server = dist / "index.js", dist / "server.js"
            original = BASE_V30
            index.write_text(original, encoding="utf-8")
            server.write_text(PLUGIN_SOURCE, encoding="utf-8")
            write_version(index)
            with patch.dict(os.environ, {patcher.CLOAKING_ENV: "0"}):
                reasons_before = patcher.verify_plugin_health(root)["reasons"]
                result = patcher.patch_cloaking(root)
                self.assertFalse(result["ok"])
                self.assertEqual(result["changed"], [str(index)])
                self.assertEqual(result["unsupported"], [str(server)])
                self.assertEqual(index.with_suffix(".js.hub-cloaking.bak").read_text(encoding="utf-8"), original)
                self.assertEqual(server.read_text(encoding="utf-8"), PLUGIN_SOURCE)
                self.assertEqual(patcher.patch_cloaking(root)["already"], [str(index)])
                health = patcher.verify_plugin_health(root)
                self.assertEqual(health["cloaking"]["active"], 1)
                self.assertEqual(health["cloaking"]["unsupported"], [str(server)])
                self.assertEqual(health["reasons"], reasons_before)  # base features unchanged

    @unittest.skipUnless(node_executable(), "Node is needed to check patched JavaScript")
    def test_vendored_30_bundle_on_temp_copy(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            dist = root / "node_modules" / patcher.PLUGIN_NAME / "dist"
            dist.mkdir(parents=True)
            for name in ("server.js", "index.js"):
                shutil.copyfile(ROOT / "plugin" / "dist" / name, dist / name)
            write_version(dist / "server.js")
            with patch.dict(os.environ, {patcher.CLOAKING_ENV: "0"}):
                self.assertTrue(patcher.patch_quota_breaker(root)["ok"] or
                                patcher.patch_quota_breaker(root)["already"])
                result = patcher.patch_cloaking(root)
                self.assertTrue(result["ok"], result)
                self.assertTrue(result["syntax_checked"] if "syntax_checked" in result else True)
                for name in ("server.js", "index.js"):
                    content = (dist / name).read_bytes()
                    self.assertIn(patcher.CLOAKING_MARKER.encode(), content)
                    temp = Path(directory) / name.replace(".js", ".mjs")
                    temp.write_bytes(content)
                    check = subprocess.run([node_executable(), "--check", str(temp)],
                                           capture_output=True, text=True, timeout=20)
                    self.assertEqual(check.returncode, 0, check.stderr)
                self.assertEqual(patcher.patch_cloaking(root)["already"],
                                 [str(dist / "server.js"), str(dist / "index.js")])
                health = patcher.verify_plugin_health(root)
                self.assertTrue(health["ok"])
                self.assertEqual(health["cloaking"]["active"], 2)
                healed = patcher.self_heal_plugin(root, state_path=root / "state.json")
                self.assertEqual(healed["state"], "already_healthy")
                self.assertEqual(healed["cloaking"]["state"], "active")

    @unittest.skipUnless(os.environ.get("HUB_TEST_AGY_3113_DIST") and node_executable(),
                         "Set HUB_TEST_AGY_3113_DIST to a 3.1.13 dist directory for the offline check")
    def test_real_3113_self_heal_on_temp_copies_only(self):
        source = Path(os.environ["HUB_TEST_AGY_3113_DIST"])
        names = ("server.js", "index.js")
        snapshots = {name: (source / name).read_bytes() for name in names}
        originals = snapshots.copy()
        for name, content in snapshots.items():
            installed = content.decode("utf-8")
            if patcher.CLOAKING_MARKER in installed:
                # An already patched installation is acceptable only when its
                # read-only backup reproduces exactly those installed bytes.
                backup = (source / (name + patcher.CLOAKING_BACKUP_SUFFIX)).read_bytes().decode("utf-8")
                self.assertEqual(patcher._plan_cloaking(backup), installed, name)
                originals[name] = backup.encode("utf-8")
        package_json = (source.parent / "package.json").read_bytes()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dist = root / "node_modules" / patcher.PLUGIN_NAME / "dist"
            dist.mkdir(parents=True)
            (dist.parent / "package.json").write_bytes(package_json)
            self.assertEqual(patcher._package_version(dist.parent), "3.1.13")
            for name, content in originals.items():
                (dist / name).write_bytes(content)
            with patch.dict(os.environ, {patcher.CLOAKING_ENV: "0"}):
                patcher.patch_quota_breaker(root)
                result = patcher.patch_cloaking(root)
                self.assertTrue(result["ok"], result)
                for name in names:
                    content = (dist / name).read_bytes()
                    self.assertIn(patcher.CLOAKING_MARKER.encode(), content)
                    temp = Path(directory) / name.replace(".js", ".mjs")
                    temp.write_bytes(content)
                    check = subprocess.run([node_executable(), "--check", str(temp)],
                                           capture_output=True, text=True, timeout=20)
                    self.assertEqual(check.returncode, 0, check.stderr)
                health = patcher.verify_plugin_health(root)
                self.assertEqual(health["cloaking"]["active"], 2)
                self.assertEqual(patcher.patch_cloaking(root)["already"],
                                 [str(dist / name) for name in names])
        for name, snapshot in snapshots.items():
            self.assertEqual((source / name).read_bytes(), snapshot, name)


MOCK_RUNTIME = r'''
var logged = [];
var originalLog = console.log;
console.log = function () { logged.push([].slice.call(arguments)); };
var ANTIGRAVITY_BLOCKED_SYSTEM_INSTRUCTION_PATTERNS = [
  [/tools\.opencode\.([A-Za-z0-9_]+)/gi, 'tools["agent"]["$1"]'],
  [/tools\["agent"\]\["([A-Za-z0-9_]+)"\]/g, 'tools.$1'],
  [/\bOpenCode\b/g, 'the coding agent'],
  [/\bopencode\b/g, 'coding agent'],
  [/Code Mode/g, 'tool catalog'],
  [/code mode/g, 'tool catalog']
];
function sanitizeAntigravitySystemInstruction(payload) {
  if (!payload || typeof payload !== 'object' || !payload.systemInstruction) return;
  var instruction = payload.systemInstruction;
  var sanitize = (text) => {
    for (const [pattern, replacement] of ANTIGRAVITY_BLOCKED_SYSTEM_INSTRUCTION_PATTERNS)
      text = text.replace(pattern, replacement);
    return text;
  };
  if (typeof instruction === 'string') { payload.systemInstruction = sanitize(instruction); return; }
  for (const part of instruction.parts || []) if (part && typeof part.text === 'string') part.text = sanitize(part.text);
}
var breakerObserves = 0;
function createHubQuotaBreaker() {
  return { observe: async function (key, response, now) { breakerObserves += 1; } };
}
function buildAgyCliHeaderPairs() {
  return [["X-Goog-Api-Client", "google-cloud-sdk"], ["Client-Metadata", "{}"], ["Content-Type", "application/json"]];
}
function prepareAgyWireRequest(wire, request) { return wire.prepare(request); }
function createRequestExecutor(deps) { return deps; }
'''


class CloakingRuntimeTests(unittest.TestCase):
    def run_js(self, body: str, optin: bool) -> None:
        node = node_executable()
        if not node:
            self.skipTest("Node is needed to execute the mocked cloaking layer")
        eol = "\n"
        block = patcher._cloaking_block(eol, optin)
        script = (MOCK_RUNTIME + block + "\n(async () => {\n" + body + """
console.log = originalLog;
})().catch(error => { console.error(error); process.exitCode = 1; });
""")
        result = subprocess.run([node, "-"], input=script, capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_default_rewrites_bare_exhaustion_and_headers(self):
        self.run_js(r'''
const assert = require('node:assert/strict');
assert.equal(ANTIGRAVITY_BLOCKED_SYSTEM_INSTRUCTION_PATTERNS.length, 17);
const payload = { systemInstruction: { parts: [{ text: [
  "You are a Claude agent, built on Anthropic's Claude Agent SDK.",
  "x-anthropic-billing-header: cc_version=2.1.1; cch=abcde;",
  "You are Hermes Agent, built by Nous Research. Be direct: answer.",
  "<!-- End Hermes runtime environment -->",
  "# Google model operational directives",
  "If a tool, install, or network call fails and blocks the real path we stop.",
  "When the user asks you to build, run, or verify something, the deliverable is a working artifact.",
  "For help with Hermes Agent itself, read the docs.",
  "Mid-turn, the user can steer you: Hermes delivers their message.",
  "You are a personal assistant running inside OpenClaw.",
  "Use tools.opencode.session_move carefully. OpenCode tools remain."
].join("\n") }] } };
sanitizeAntigravitySystemInstruction(payload);
const text = payload.systemInstruction.parts[0].text;
assert.ok(!text.includes("Claude Agent SDK"));
assert.ok(!text.includes("x-anthropic-billing-header"));
assert.ok(!text.includes("Hermes"));
assert.ok(!text.includes("OpenClaw"));
assert.ok(text.includes("You are a personal assistant running inside Antigravity."));
assert.ok(text.includes("tools.session_move"));
assert.ok(text.includes("the coding agent"));
assert.deepEqual(buildAgyCliHeaderPairs("https://daily-cloudcode-pa.googleapis.com/v1internal:streamGenerateContent?alt=sse"),
                 [["Content-Type", "application/json"]]);
assert.equal(buildAgyCliHeaderPairs("https://cloudcode-pa.googleapis.com/v1internal:loadCodeAssist").length, 3);
const bare = () => new Response(JSON.stringify({error: {status: "RESOURCE_EXHAUSTED",
  message: "Resource has been exhausted (e.g. check quota)."}}), {status: 429});
for (let i = 0; i < 3; i += 1) await createHubQuotaBreaker().observe({}, bare(), i);
assert.equal(breakerObserves, 0);
const real = new Response(JSON.stringify({error: {status: "RESOURCE_EXHAUSTED",
  message: "Individual quota reached. Resets in 1h.", details: [{retryDelay: "60s"}]}}), {status: 429});
await createHubQuotaBreaker().observe({}, real, 4);
assert.equal(breakerObserves, 1);
const realText = await real.text();
assert.ok(realText.includes("Individual quota reached"));
assert.equal(logged.length, 0);
''', False)

    def test_optin_default_system_request_type_and_single_retry(self):
        self.run_js(r'''
const assert = require('node:assert/strict');
const payload = { systemInstruction: { parts: [{ text: "User instructions." }] } };
sanitizeAntigravitySystemInstruction(payload);
sanitizeAntigravitySystemInstruction(payload);
assert.equal(payload.systemInstruction.parts.length, 2);
assert.ok(payload.systemInstruction.parts[0].text.startsWith("You are Antigravity Agent"));
const title = { systemInstruction: { parts: [{ text: "You are a conversation title generator." }] } };
sanitizeAntigravitySystemInstruction(title);
assert.equal(title.systemInstruction.parts.length, 1);
const native = { systemInstruction: { parts: [{ text: "You are Antigravity Agent already." }] } };
sanitizeAntigravitySystemInstruction(native);
assert.equal(native.systemInstruction.parts.length, 1);
const init = { body: JSON.stringify({requestType: "agent", request: {contents: []}}) };
const prepared = prepareAgyWireRequest({ prepare: (value) => ({ init: value }) }, init);
assert.ok(!("requestType" in JSON.parse(prepared.init.body)));
const checkpoint = { body: JSON.stringify({requestType: "checkpoint", request: {contents: []}}) };
const kept = prepareAgyWireRequest({ prepare: (value) => ({ init: value }) }, checkpoint);
assert.equal(JSON.parse(kept.init.body).requestType, "checkpoint");
let sends = 0;
const bare = () => new Response(JSON.stringify({error: {status: "RESOURCE_EXHAUSTED",
  message: "Resource has been exhausted (e.g. check quota)."}}), {status: 429});
const executor = createRequestExecutor({ transport: async (url, init) => {
  sends += 1;
  return sends % 2 === 1 ? bare() : new Response("{}", {status: 200});
} });
const body = JSON.stringify({request: {systemInstruction: {parts: [{text: "You are an agent."}]},
  contents: [{role: "user", parts: [{text: "hi"}]}]}});
const first = await executor.transport("https://example.test", {body});
assert.equal(first.status, 200);
assert.equal(sends, 2);
const second = await executor.transport("https://example.test", {body});
assert.equal(second.status, 429);
assert.equal(sends, 3);
assert.equal(logged.length, 0);
''', True)


if __name__ == "__main__":
    unittest.main()
