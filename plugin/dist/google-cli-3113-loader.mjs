import { createHash } from "node:crypto";

// Exact reviewed @cortexkit/opencode-antigravity-auth CLI bytes. If npm
// publishes different bytes under the same version, do not execute them.
const CLI_SHA256 = "6e4b0fa37c3a9de34100c92bda18347f49f1bb071dacf10007f91d64c243b946";
let target;

export function initialize({ cliUrl }) {
  target = cliUrl;
}

export async function resolve(specifier, context, nextResolve) {
  const resolved = await nextResolve(specifier, context);
  if (specifier === target && resolved.url !== target)
    throw new Error("Google CLI path changed during import");
  return resolved;
}

function replaceOnce(source, before, after) {
  if (!source.includes(before) || source.indexOf(before) !== source.lastIndexOf(before))
    throw new Error("Unsupported Google CLI profile");
  return source.replace(before, after);
}

export async function load(url, context, nextLoad) {
  const loaded = await nextLoad(url, context);
  if (url !== target) return loaded;
  if (loaded.format !== "module" || !loaded.source)
    throw new Error("Unsupported Google CLI format");
  const bytes = Buffer.from(loaded.source);
  if (createHash("sha256").update(bytes).digest("hex") !== CLI_SHA256)
    throw new Error("Unsupported Google CLI digest");
  let source = bytes.toString("utf8");
  source = replaceOnce(source,
    "async function refreshAntigravityToken(refreshToken) {",
    "async function refreshAntigravityToken(refreshToken, fetchImpl) {");
  // Scope the fetch hook to the exact OAuth helper; no global fetch mutation.
  source = replaceOnce(source,
    '  });\n  if (!response.ok) {\n    const errorText3 = await response.text().catch(() => "");\n    throw new Error(`Antigravity token refresh failed',
    '  }, { fetchImpl });\n  if (!response.ok) {\n    const errorText3 = await response.text().catch(() => "");\n    throw new Error(`Antigravity token refresh failed');
  source += `
export {
  legacyAccountFile, loadCommonAuthStoreModules, readAccountStoreAdmission,
  createAccountRepositoryFactory, readOpenCodeAuthority, refreshAntigravityToken,
  parseOAuthErrorPayload, startRuntimeProcessHeartbeat, removeProcessHeartbeat
};
`;
  return { ...loaded, source };
}
