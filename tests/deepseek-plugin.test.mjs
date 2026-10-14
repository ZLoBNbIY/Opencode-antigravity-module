import assert from "node:assert/strict";
import { execFile } from "node:child_process";
import { mkdtemp, writeFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import test from "node:test";
import { promisify } from "node:util";
import { createPlugin, channelReader, decryptWindows, validateChannel } from "../deepseek-plugin/index.js";
const channel = { purpose: "deepseek-web-channel", origin: "http://127.0.0.1:51234", key: "a".repeat(64) };

async function hook(read = async () => channel) {
  let fn;
  await createPlugin(read).setup({ options: { channelFile: "test" }, session: { hook: async (name, callback, scope) => {
    assert.equal(name, "http.request"); assert.deepEqual(scope, { providerID: "deepseek-web" }); fn = callback;
  } } });
  return fn;
}

test("web requests use current loopback channel, not paid API or web-site token", async () => {
  const fn = await hook();
  const event = { request: new Request("http://127.0.0.1:1/v1/chat/completions", { method: "POST", body: "{}", headers: { "x-api-key": "old", cookie: "private" } }) };
  await fn(event);
  assert.equal(event.request.url, channel.origin + "/v1/chat/completions");
  assert.equal(event.request.headers.get("authorization"), "Bearer " + channel.key);
  assert.equal(event.request.headers.get("cookie"), null);
  assert.equal(event.request.headers.get("x-api-key"), null);
  assert.equal(event.request.redirect, "error");
  assert.equal(await event.request.text(), "{}");
});

test("paid API and foreign endpoints are rejected before reading the channel", async () => {
  let reads = 0;
  const fn = await hook(async () => { reads++; return channel; });
  for (const url of ["https://api.deepseek.com/anthropic/v1/messages", "https://platform.deepseek.com", "http://evil.test/v1/chat/completions"]) {
    await assert.rejects(() => fn({ request: new Request(url) }));
  }
  assert.equal(reads, 0);
});

test("channel descriptors cannot redirect local credentials to a remote server", () => {
  assert.equal(validateChannel(channel).origin, channel.origin);
  for (const origin of ["https://api.deepseek.com", "http://localhost:1234", "http://127.0.0.1:1234/path", "http://127.0.0.1:1234/?secret=1"]) {
    assert.throws(() => validateChannel({ ...channel, origin }));
  }
});

test("disconnect while unlocking DPAPI prevents reuse of an old channel", async () => {
  const directory = await mkdtemp(join(tmpdir(), "deepseek-web-"));
  const file = join(directory, "channel.json");
  try {
    const read = channelReader({ platform: "win32", decrypt: async () => {
      await rm(file); return JSON.stringify(channel);
    } });
    await writeFile(file, JSON.stringify({ version: 3, protection: "dpapi-current-user", payload: "AA==" }));
    await assert.rejects(() => read(file));
  } finally { await rm(directory, { recursive: true, force: true }); }
});

test("Python and Node interoperate with real Windows DPAPI", { skip: process.platform !== "win32" }, async () => {
  const script = "import sys,json; sys.path.insert(0,sys.argv[1]); from deepseek_storage import protect_channel; print(json.dumps(protect_channel({'purpose':'deepseek-web-channel','origin':'http://127.0.0.1:51234','key':'a'*64})))";
  const { stdout } = await promisify(execFile)(process.env.PYTHON || "python", ["-c", script, resolve("gui-manager")]);
  const record = JSON.parse(stdout);
  assert.doesNotMatch(stdout, /aaaaaaaaaaaaaaaaaaaaaaaa/);
  const plain = JSON.parse(await decryptWindows(record.payload));
  assert.equal(validateChannel(plain).key, channel.key);
});
