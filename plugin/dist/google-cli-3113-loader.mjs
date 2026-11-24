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
  source = replaceOnce(source,
    "    const userInfo = userInfoResponse.ok ? await userInfoResponse.json() : {};\n    await admitExchange(options);\n    const refreshToken = tokenPayload.refresh_token;",
    `    const userInfo = userInfoResponse.ok ? await userInfoResponse.json() : {};
    if ((!userInfo.email || !userInfo.name) && typeof tokenPayload.id_token === "string") {
      try {
        const idParts = tokenPayload.id_token.split(".");
        if (idParts.length >= 2) {
          const claims = JSON.parse(Buffer.from(idParts[1], "base64url").toString("utf8")) || {};
          if (!userInfo.email && claims.email) userInfo.email = claims.email;
          if (!userInfo.name && claims.name) userInfo.name = claims.name;
        }
      } catch {}
    }
    await admitExchange(options);
    const refreshToken = tokenPayload.refresh_token;`);
  source += `
export {
  legacyAccountFile, loadCommonAuthStoreModules, readAccountStoreAdmission,
  createAccountRepositoryFactory, readOpenCodeAuthority, refreshAntigravityToken,
  parseOAuthErrorPayload, startRuntimeProcessHeartbeat, removeProcessHeartbeat,
  getStoragePath, accountFileForVault, assertLocalOpenCodeLogin,
  prepareCliLoginStore, commitLogins, parseRefreshParts,
  authorizeAntigravity, exchangeAntigravity, startOAuthListener, openBrowserDefault,
  checkAccountsQuotaStandalone, quotaSummary, refreshAccessToken, buildAuthFromAccount
};
`;
  return { ...loaded, source };
}
