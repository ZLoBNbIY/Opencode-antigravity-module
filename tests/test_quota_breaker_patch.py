"""Offline tests for the Cloud Code user-response cooldown patch."""
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from test_cloudcode_route_patch import PLUGIN_SOURCE, node_executable, write_version
import cloudcode_route_patch as patcher


ROOT = Path(__file__).resolve().parent.parent

# Minimal executable copy of the application-level positions, not a transport
# hook. Warmups are separate sends and must never enter the breaker.
EXECUTOR_FIXTURE = '''function createRequestExecutor(deps) {
  const { transport, upstreamFetch, trackers } = deps;
  return async function execute(account, prepared, admission) {
    const abortSignal = null;
    const pushDebug = () => {};
    const toUrlString = String;
    const runThinkingWarmup = () => deps.warmup();
    const runCacheWarmupProbe = () => deps.probe();
    const sendProjectId = "fixture-project";
    let apiRequestCount = 0, physicalAttemptStarted = false;
          let tokenConsumed = false;
            let sendAdmission;
            sendAdmission = admission;
            const resolvedUrl = toUrlString(prepared.request);
''' + patcher.QUOTA_WARMUP + '''
            tokenConsumed = true;
            await deps.beforeSend();
''' + patcher.QUOTA_SEND + '''
            return response;
  };
}
function extractRateLimitBodyInfo(body) { return body; }
'''

# The main send fingerprint from both 3.1.13 bundles. Their real warmup and
# probe also call sendPhysical; keep those calls in the executable mock.
EXECUTOR_FIXTURE_V2 = (
    EXECUTOR_FIXTURE.replace(
        "    const runThinkingWarmup = () => deps.warmup();\n"
        "    const runCacheWarmupProbe = () => deps.probe();",
        """    const sendPhysical = (url, init, admission, model, kind) =>
      kind === "warmup" ? deps.warmup() : kind === "probe" ? deps.probe() : transport(url, init);
    const runThinkingWarmup = () => sendPhysical(null, null, null, null, "warmup");
    const runCacheWarmupProbe = () => sendPhysical(null, null, null, null, "probe");
    const model = prepared.effectiveModel;
    const kind = "primary";
    const retainMainTransportFailure = () => {};""",
    ).replace(patcher.QUOTA_SEND, '''            pushDebug(
              `dispatching request via ${prepared.headerStyle} transport`
            );
            physicalAttemptStarted = true;
            let response = await sendPhysical(
              toUrlString(prepared.request),
              prepared.init,
              sendAdmission,
              prepared.effectiveModel ?? model ?? "unknown",
              kind ?? "primary",
              retainMainTransportFailure
            );
            const receivedAtMs = Date.now();''')
    .replace("extractRateLimitBodyInfo(body) {", "extractRateLimitBodyInfo(body, status, headers) {")
)


class QuotaBreakerPatchTests(unittest.TestCase):
    def test_idempotent_with_crlf_and_refuses_unknown_or_partial_layout(self):
        source = (PLUGIN_SOURCE + EXECUTOR_FIXTURE).replace("\n", "\r\n")
        edited = patcher._plan_quota_breaker(source)
        self.assertIsNotNone(edited)
        self.assertNotIn("\n", edited.replace("\r\n", ""))
        self.assertEqual(patcher._plan_quota_breaker(edited), edited)
        self.assertIsNone(patcher._plan_quota_breaker(source.replace("apiRequestCount++;", "count++;")))
        self.assertIsNone(patcher._plan_quota_breaker(source + source))
        self.assertIsNone(patcher._plan_quota_breaker(edited.replace("await hubQuotaBreaker.observe", "void hubQuotaBreaker.observe")))
        v2 = PLUGIN_SOURCE + EXECUTOR_FIXTURE_V2
        updated_v2 = patcher._plan_quota_breaker(v2)
        self.assertIsNotNone(updated_v2)
        self.assertEqual(patcher._plan_quota_breaker(updated_v2), updated_v2)
        self.assertIsNone(patcher._plan_quota_breaker(v2.replace("const receivedAtMs", "const receivedAt")))
        self.assertIsNone(patcher._plan_quota_breaker(updated_v2.replace(
            "observe(hubQuotaKey, response, receivedAtMs);", "observe(hubQuotaKey, response);")))

    def test_installed_copy_fixture_reports_unsupported_separately(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dist = root / "node_modules" / patcher.PLUGIN_NAME / "dist"
            dist.mkdir(parents=True)
            index, server = dist / "index.js", dist / "server.js"
            original = PLUGIN_SOURCE + EXECUTOR_FIXTURE
            index.write_text(original, encoding="utf-8")
            server.write_text(PLUGIN_SOURCE, encoding="utf-8")
            write_version(index)
            result = patcher.patch_quota_breaker(root)
            self.assertFalse(result["ok"])
            self.assertEqual(result["changed"], [str(index)])
            self.assertEqual(result["unsupported"], [str(server)])
            self.assertEqual(index.with_suffix(".js.hub-quota-breaker.bak").read_text(encoding="utf-8"), original)
            self.assertEqual(server.read_text(encoding="utf-8"), PLUGIN_SOURCE)
            self.assertEqual(patcher.patch_quota_breaker(root)["already"], [str(index)])

    @unittest.skipUnless(node_executable(), "Node is needed to check patched JavaScript")
    def test_vendored_30_layouts_parse_without_modifying_dist(self):
        with tempfile.TemporaryDirectory() as directory:
            for name in ("index.js", "server.js"):
                with self.subTest(name=name):
                    original = patcher._read_text_exact(ROOT / "plugin" / "dist" / name)
                    updated = patcher._plan_quota_breaker(original)
                    self.assertIsNotNone(updated)
                    temp = Path(directory) / name.replace(".js", ".mjs")
                    temp.write_bytes(updated.encode("utf-8"))
                    result = subprocess.run([node_executable(), "--check", str(temp)],
                                            capture_output=True, text=True, timeout=15)
                    self.assertEqual(result.returncode, 0, result.stderr)

    @unittest.skipUnless(os.environ.get("HUB_TEST_AGY_3113_DIST") and shutil.which("node"),
                         "Set HUB_TEST_AGY_3113_DIST to the 3.1.13 dist directory for the offline bundle check")
    def test_real_3113_self_heal_on_temp_copies_only(self):
        source = Path(os.environ["HUB_TEST_AGY_3113_DIST"])
        names = ("server.js", "index.js")
        snapshots = {name: (source / name).read_bytes() for name in names}
        originals = snapshots.copy()
        for name, content in snapshots.items():
            installed = content.decode("utf-8")
            if patcher._plan_quota_breaker(installed) == installed:
                # Accept an already patched installation as input only if its
                # read-only backup reproduces exactly those installed bytes.
                backup = (source / (name + ".hub-quota-breaker.bak")).read_bytes()
                self.assertTrue(patcher._plan_quota_breaker(backup.decode("utf-8")) == installed, name)
                originals[name] = backup
        package_json = (source.parent / "package.json").read_bytes()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dist = root / "node_modules" / patcher.PLUGIN_NAME / "dist"
            dist.mkdir(parents=True)
            (dist.parent / "package.json").write_bytes(package_json)
            self.assertEqual(patcher._package_version(dist.parent), "3.1.13")
            for name, content in originals.items():
                (dist / name).write_bytes(content)
            self.assertEqual(patcher.verify_plugin_health(root)["quota_breaker"]["pending"], 2)
            result = patcher.self_heal_plugin(root, state_path=root / "state.json")
            self.assertTrue(result["ok"], result)
            self.assertTrue(result["syntax_checked"], result)
            self.assertEqual(result["quota_breaker"],
                             {"state": "active", "pending": 0, "active": 2, "unsupported": []})
            for name, original in originals.items():
                changed = dist / name
                self.assertIn(patcher.QUOTA_OBSERVE_V2.strip(), changed.read_text(encoding="utf-8"))
                self.assertEqual(changed.with_suffix(".js.hub-quota-breaker.bak").read_bytes(), original)
            self.assertEqual(patcher.self_heal_plugin(root, state_path=root / "state.json")["state"],
                             "already_healthy")
        for name, snapshot in snapshots.items():
            self.assertTrue((source / name).read_bytes() == snapshot, name)

    def run_js(self, body, source=patcher.QUOTA_BREAKER_JS):
        node = node_executable()
        if not node:
            self.skipTest("Node is needed to execute mocked Responses")
        script = "const assert = require('node:assert/strict');\n" + source + "\n(async () => {\n" + body + """
})().catch(error => { console.error(error); process.exitCode = 1; });
"""
        result = subprocess.run([node, "-"], input=script, capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_only_real_quota_responses_open_and_success_resets_pair_strikes(self):
        self.run_js(r'''
const breaker = createHubQuotaBreaker();
const url = "https://cloudcode-pa.googleapis.com/v1internal:generateContent";
const key = (email, effectiveModel) => breaker.key({ email }, null, { effectiveModel }, url);
const a = key("account-a", "gemini-a"), b = key("account-b", "gemini-a"), c = key("account-a", "gemini-b");
const aClone = key(" ACCOUNT-A ", "gemini-a");
const observe = (k, now, status, body, headers) =>
  breaker.observe(k, new Response(JSON.stringify(body ?? {}), { status, headers }), now);
for (const now of [10, 20, 30]) {
  await observe(a, now, 409, { error: { status: "ABORTED", message: "quota exhausted" } }, { "Retry-After": "3600" });
  await observe(a, now, 503, { error: { status: "RESOURCE_EXHAUSTED" } });
  await observe(a, now, 429, {}, { "x-antigravity-synthetic": "true", "Retry-After": "3600" });
}
assert.equal(breaker.blocked(a, 35), null);
await observe(a, 40, 429);
await observe(a, 50, 429);
await observe(aClone, 60, 200);
await observe(a, 70, 409, { error: { details: [
  { "@type": "type.googleapis.com/google.rpc.ErrorInfo", reason: "QUOTA_EXHAUSTED" }
] } });
await observe(a, 80, 429);
assert.equal(breaker.blocked(a, 90), null);
await observe(a, 60_071, 429);  // First strike is now outside the sliding window.
assert.equal(breaker.blocked(a, 60_071), null);
await observe(a, 60_080, 429);  // The left boundary of the window is inclusive.
const blocked = breaker.blocked(aClone, 60_080);
assert.equal(blocked.status, 412);
assert.equal(blocked.headers.get("Retry-After"), "900");
assert.equal(breaker.blocked(b, 60_080), null);
assert.equal(breaker.blocked(c, 60_080), null);
await observe(a, 60_081, 200);  // An in-flight success doesn't shorten cooldown.
assert.ok(breaker.blocked(a, 960_079));
assert.equal(breaker.blocked(a, 960_080), null);
''')

    def test_explicit_deadlines_preserve_longest_and_do_not_consume_response(self):
        self.run_js(r'''
const breaker = createHubQuotaBreaker();
const url = "https://daily-cloudcode-pa.googleapis.com/v1internal:streamGenerateContent?alt=sse";
const key = breaker.key({ rowRef: { id: "row-a" } }, null, { effectiveModel: "gemini" }, url);
const now = Date.parse("2026-01-01T00:00:00Z");
const body = JSON.stringify({ error: { status: "RESOURCE_EXHAUSTED", details: [
  { "@type": "type.googleapis.com/google.rpc.QuotaFailure", metadata: { resetAt: "2026-01-01T02:00:00Z" } }
] } });
const first = new Response(body, { status: 409, headers: { "Retry-After": "30" } });
await breaker.observe(key, first, now);
assert.equal(await first.text(), body);
assert.equal(breaker.blocked(key, now).headers.get("Retry-After"), "7200");
const second = new Response("not JSON", { status: 429, headers: { "Retry-After": "Thu, 01 Jan 2026 03:00:00 GMT" } });
await breaker.observe(key, second, now + 1000);
await breaker.observe(key, new Response(null, { status: 429, headers: { "Retry-After": "30" } }), now + 2000);
await breaker.observe(key, new Response(null, { status: 204 }), now + 3000);
assert.equal(breaker.blocked(key, now + 3000).headers.get("Retry-After"), "10797");
assert.equal(breaker.blocked(key, now + 10_800_000), null);
''')

    def test_out_of_order_error_body_cannot_revive_strikes_after_success(self):
        self.run_js(r'''
const breaker = createHubQuotaBreaker();
const key = { id: "acct", model: "model" };
let controller;
const body = new ReadableStream({start(ctrl) { controller = ctrl; }});
const pending = breaker.observe(key, new Response(body, {status: 429}), 10);
await breaker.observe(key, new Response(null, {status: 200}), 20);
controller.close();
await pending;
await breaker.observe(key, new Response(null, {status: 429}), 30);
await breaker.observe(key, new Response(null, {status: 429}), 40);
assert.equal(breaker.blocked(key, 40), null);
''')

    def test_three_structured_quota_conflicts_apply_fifteen_minute_floor(self):
        self.run_js(r'''
const breaker = createHubQuotaBreaker();
const key = { id: "acct", model: "model" };
for (const now of [0, 1000, 2000]) {
  const response = new Response(JSON.stringify({error: {errors: [{reason: "dailyLimitExceeded"}]}}),
    {status: 409, headers: {"Retry-After": "1"}});
  await breaker.observe(key, response, now);
}
assert.equal(breaker.blocked(key, 2000).headers.get("Retry-After"), "900");
''')

    def test_patched_executor_preserves_real_responses_and_never_counts_probes(self):
        script = r'''
let clock = 1000, sends = 0, probes = 0, refunds = 0, status = 200;
let beforeSend = async () => {};
Date.now = () => clock;
const send = () => {
  sends++;
  return new Response("upstream payload", {status});
};
const probe = () => {
  probes++;
  return new Response(null, {status: 429});
};
const execute = createRequestExecutor({
  transport: send, upstreamFetch: send, warmup: probe, probe, beforeSend: () => beforeSend(),
  trackers: {token: {refund: () => refunds++}}
});
const p = {effectiveModel: "gemini", headerStyle: "antigravity",
  request: "https://cloudcode-pa.googleapis.com/v1internal:generateContent"};
const a = {email: "a"}, b = {email: "b"};
for (let i = 0; i < 4; ++i) assert.equal((await execute(a, p)).status, 200);
status = 429;
for (let i = 0; i < 2; ++i) assert.equal((await execute(a, p)).status, 429);
// Another response opens the breaker while this attempt is between warmup and dispatch.
beforeSend = async () => {
  beforeSend = async () => {};
  const third = await execute(a, {...p, headerStyle: "gemini-cli"});
  assert.equal(third.status, 429);
  assert.equal(await third.text(), "upstream payload");
};
assert.equal((await execute(a, p)).status, 412);
assert.equal(refunds, 1);
assert.equal((await execute(a, p)).status, 412);
assert.equal(sends, 7);
assert.equal(probes, 16);
assert.equal((await execute(b, p)).status, 429);
clock += 15 * 60_000;
status = 200;
assert.equal((await execute(a, p)).status, 200);
'''
        for profile, fixture in (("3.0", EXECUTOR_FIXTURE), ("3.1", EXECUTOR_FIXTURE_V2)):
            with self.subTest(profile=profile):
                edited = patcher._plan_quota_breaker(PLUGIN_SOURCE + fixture)
                self.assertIsNotNone(edited)
                self.run_js(script, edited[edited.index(patcher.QUOTA_BREAKER_MARKER):])


if __name__ == "__main__":
    unittest.main()
