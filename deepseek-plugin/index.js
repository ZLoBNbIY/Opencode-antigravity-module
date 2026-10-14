// OpenCode V2 -> authenticated channel inside Hub -> installed browser web chat.
// No DeepSeek Platform credential or paid inference endpoint is used here.
import { execFile } from "node:child_process";
import { readFile, stat } from "node:fs/promises";
import { join } from "node:path";

export const PROVIDER_ID = "deepseek-web";

export function decryptWindows(ciphertext) {
  const script = [
    "$ErrorActionPreference = 'Stop'", "Add-Type -AssemblyName System.Security",
    "$cipher = [Convert]::FromBase64String([Console]::In.ReadToEnd())",
    "$plain = [Security.Cryptography.ProtectedData]::Unprotect($cipher, $null, [Security.Cryptography.DataProtectionScope]::CurrentUser)",
    "[Console]::OutputEncoding = [Text.Encoding]::UTF8", "[Console]::Out.Write([Text.Encoding]::UTF8.GetString($plain))",
    "[Array]::Clear($plain, 0, $plain.Length)",
  ].join("; ");
  return new Promise((resolve, reject) => {
    const executable = join(process.env.SystemRoot || "C:\\Windows", "System32", "WindowsPowerShell", "v1.0", "powershell.exe");
    const child = execFile(executable, ["-NoLogo", "-NoProfile", "-NonInteractive", "-EncodedCommand", Buffer.from(script, "utf16le").toString("base64")],
      { windowsHide: true, timeout: 10000, maxBuffer: 65536, encoding: "utf8" },
      (error, stdout) => error ? reject(new Error("Cannot unlock the Hub channel for this Windows user")) : resolve(stdout.replace(/^\uFEFF/, "")));
    child.stdin?.on("error", () => {});
    child.stdin?.end(ciphertext);
  });
}

export function validateChannel(value) {
  let origin;
  try { origin = new URL(value.origin); } catch { throw new Error("Invalid Hub channel"); }
  if (value.purpose !== "deepseek-web-channel" || origin.protocol !== "http:" || origin.hostname !== "127.0.0.1"
    || !origin.port || origin.username || origin.password || origin.search || origin.hash || origin.pathname !== "/"
    || !/^[a-f0-9]{64}$/.test(value.key)) throw new Error("DeepSeek Web can only use the local Hub channel");
  return { origin: origin.origin, key: value.key };
}

export function channelReader({ platform = process.platform, decrypt = decryptWindows } = {}) {
  let lastCipher, cached;
  return async (path) => {
    let record;
    try {
      const info = await stat(path);
      if (info.size > 65536 || (platform !== "win32" && (info.mode & 0o077))) throw new Error();
      record = JSON.parse(await readFile(path, "utf8"));
      if (record.version !== 3 || !record.payload) throw new Error();
    } catch {
      lastCipher = cached = undefined;
      throw new Error("Open Antigravity Hub and connect your chat.deepseek.com session");
    }
    let value;
    if (platform === "win32" && record.protection === "dpapi-current-user") {
      if (typeof record.payload !== "string") throw new Error("Invalid protected Hub channel");
      if (record.payload !== lastCipher) {
        lastCipher = record.payload;
        cached = decrypt(record.payload).then((text) => JSON.parse(text));
      }
      try { value = await cached; } catch { lastCipher = cached = undefined; throw new Error("Cannot unlock the Hub channel"); }
    } else if (platform !== "win32" && record.protection === "private-file") {
      value = record.payload;
    } else throw new Error("Windows requires a DPAPI-protected Hub channel");
    // Disconnect/restart while DPAPI was unlocking must not use the old channel.
    let latest;
    try { latest = JSON.parse(await readFile(path, "utf8")); } catch { latest = null; }
    if (JSON.stringify(latest) !== JSON.stringify(record)) throw new Error("Hub connection changed; retry the request");
    return validateChannel(value);
  };
}

export function createPlugin(readChannel = channelReader()) {
  return {
    id: "antigravity-hub.deepseek-web",
    async setup(ctx) {
      const path = ctx.options?.channelFile;
      if (typeof path !== "string" || !path) throw new Error("Hub channel is not configured");
      await ctx.session.hook("http.request", async (event) => {
        const original = new URL(event.request.url);
        if (original.protocol !== "http:" || original.hostname !== "127.0.0.1" || original.username || original.password
          || original.pathname !== "/v1/chat/completions") throw new Error("DeepSeek Web must not call a paid or remote API endpoint");
        const channel = await readChannel(path);
        const body = await event.request.arrayBuffer();
        if (body.byteLength > 4 * 1024 * 1024) throw new Error("DeepSeek Web request is too large");
        const headers = new Headers(event.request.headers);
        for (const name of ["authorization", "x-api-key", "api-key", "cookie", "content-length"]) headers.delete(name);
        headers.set("authorization", "Bearer " + channel.key);
        event.request = new Request(channel.origin + "/v1/chat/completions", {
          method: "POST", headers, body, signal: event.request.signal, redirect: "error",
        });
      }, { providerID: PROVIDER_ID });
    },
  };
}
export default createPlugin();
