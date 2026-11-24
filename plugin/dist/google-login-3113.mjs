// Hub login/quota entrypoint for the exact cached 3.1.13 CLI.
// Uses the SHA-256 verified loader without modifying the cached CLI on disk
// and commits logins non-destructively (preserving existing accounts).
import { execFile } from "node:child_process";
import { realpathSync } from "node:fs";
import { realpath } from "node:fs/promises";
import * as nodeModule from "node:module";
import { resolve } from "node:path";
import { pathToFileURL } from "node:url";
import { promisify } from "node:util";

const execFileAsync = promisify(execFile);

export async function openBrowserSafe(url, options = {}) {
  const parsed = new URL(url);
  if (parsed.protocol !== "https:" && parsed.protocol !== "http:") {
    throw new Error(`Refusing to open non-HTTP URL: ${parsed.protocol}`);
  }
  const platform = options.platform ?? process.platform;
  const runExecFile = options.execFileAsync ?? execFileAsync;
  const overrideBrowser = options.overrideBrowser ?? process.env.ANTIGRAVITY_BROWSER;
  if (platform === "win32") {
    if (overrideBrowser) {
      try {
        await runExecFile(overrideBrowser, [url]);
        return;
      } catch {}
    }
    const command = `Start-Process '${url.replaceAll("'", "''")}'`;
    await runExecFile("powershell.exe", [
      "-NoProfile",
      "-NonInteractive",
      "-WindowStyle",
      "Hidden",
      "-EncodedCommand",
      Buffer.from(command, "utf16le").toString("base64")
    ], { windowsHide: true });
    return;
  }
  await runExecFile(platform === "darwin" ? "open" : "xdg-open", [url]);
}

async function loadCli3113(cliFile) {
  if (typeof nodeModule.register !== "function") {
    throw new Error("Node module.register is unavailable");
  }
  const cliUrl = pathToFileURL(await realpath(cliFile)).href;
  nodeModule.register("./google-cli-3113-loader.mjs", {
    parentURL: import.meta.url,
    data: { cliUrl }
  });
  return await import(cliUrl);
}

function buildCredentialMetadata(existingMeta, result, parts, now) {
  return {
    ...(existingMeta && typeof existingMeta === "object" ? existingMeta : {}),
    addedAt: existingMeta?.addedAt ?? now,
    lastUsed: now,
    enabled: true,
    ...(result.email !== void 0 ? { email: result.email } : {}),
    ...(result.label !== void 0 ? { label: result.label } : {}),
    ...(parts.projectId !== void 0 ? { projectId: parts.projectId } : {}),
    ...(parts.managedProjectId !== void 0 ? { managedProjectId: parts.managedProjectId } : {})
  };
}

async function runLogin(cli) {
  const legacyPath = resolve(cli.getStoragePath());
  const quiet = { debug() {}, info() {}, warn() {}, error() {} };
  await cli.assertLocalOpenCodeLogin(resolve(cli.accountFileForVault()));
  await cli.startRuntimeProcessHeartbeat(quiet);
  let repository;
  try {
    try {
      repository = await cli.prepareCliLoginStore(legacyPath);
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      if (/migrat/i.test(msg)) {
        await cli.createDefaultAccountStoreOperations().migrate(legacyPath);
        repository = await cli.prepareCliLoginStore(legacyPath);
      } else {
        throw err;
      }
    }
    const result = await cli.performOAuthLogin(
      {
        projectId: void 0,
        noBrowser: false,
        isHeadless: false,
        refreshAccountIndex: void 0,
        accounts: [],
        startFresh: false
      },
      {
        authorize: cli.authorizeAntigravity,
        exchange: cli.exchangeAntigravity,
        startListener: () => cli.startOAuthListener({ timeoutMs: 120_000 }),
        openBrowser: openBrowserSafe,
        upsert: async (oauthResult) => {
          const read = await repository.read();
          const parts = cli.parseRefreshParts(oauthResult.refresh);
          if (!parts.refreshToken) {
            throw new Error("Login returned no usable refresh token; no account was saved.");
          }
          const now = Date.now();
          const existingRow = read.status === "ready" ? read.rows.find((r) => {
            if (typeof oauthResult.email === "string" && oauthResult.email.length > 0 &&
                r.metadata?.status === "present" && r.metadata.metadata?.email === oauthResult.email) {
              return true;
            }
            return r.credential?.refreshToken === parts.refreshToken;
          }) : void 0;
          if (existingRow) {
            const existingMeta = existingRow.metadata?.status === "present" ? existingRow.metadata.metadata : void 0;
            await repository.replaceCredential(existingRow.ref, {
              refreshToken: parts.refreshToken,
              metadata: buildCredentialMetadata(existingMeta, oauthResult, parts, now),
              disabled: "enable"
            });
            return;
          }
          const [login] = await cli.commitLogins(repository, [oauthResult], { now: () => now });
          if (login?.status === "refused" && login.rowId !== void 0 && read.status === "ready") {
            const matched = read.rows.find((r) => r.id === login.rowId);
            if (matched) {
              const existingMeta = matched.metadata?.status === "present" ? matched.metadata.metadata : void 0;
              await repository.replaceCredential(matched.ref, {
                refreshToken: parts.refreshToken,
                metadata: buildCredentialMetadata(existingMeta, oauthResult, parts, now),
                disabled: "enable"
              });
              return;
            }
          }
          if (login?.status !== "committed") {
            throw new Error(login?.message || "Failed to save Google account to 3.1.13 store");
          }
        }
      }
    );
    process.stdout.write(`Authenticated ${result.email ?? "Antigravity account"}\n`);
  } finally {
    await repository?.dispose().catch(() => {});
    await cli.removeProcessHeartbeat(quiet).catch(() => {});
  }
}

export function formatQuotaResult(result, fallbackIndex, fallbackEmail, quotaSummary) {
  const summary = quotaSummary([result])?.accounts?.[0] ?? {};
  const rawGroups = result?.quota?.groups && typeof result.quota.groups === "object"
    ? result.quota.groups
    : null;
  const groups = [];
  if (rawGroups) {
    for (const [name, g] of Object.entries(rawGroups)) {
      if (!g || typeof g !== "object") continue;
      const frac = typeof g.remainingFraction === "number" ? g.remainingFraction : null;
      const windows = Array.isArray(g.windows)
        ? g.windows
            .filter((w) => w && typeof w === "object")
            .map((w) => ({
              window: w.window ?? "",
              remainingPercent: typeof w.remainingFraction === "number"
                ? Math.round(w.remainingFraction * 1000) / 10
                : null,
              resetTime: w.resetTime ?? null,
            }))
        : [];
      groups.push({
        name,
        remainingPercent: frac !== null ? Math.round(frac * 1000) / 10 : null,
        resetTime: g.resetTime ?? null,
        windows,
      });
    }
  }
  return {
    ...summary,
    index: fallbackIndex,
    email: result?.email ?? summary.email ?? fallbackEmail ?? `Account ${fallbackIndex}`,
    status: result?.status ?? summary.status ?? "unknown",
    ...(result?.error ? { error: result.error } : {}),
    groups: groups.length > 0 ? groups : (Array.isArray(summary.groups) ? summary.groups : []),
  };
}

export function buildQuotaAccounts(rawAccounts) {
  return rawAccounts.map((acc) => {
    if (!acc || typeof acc !== "object") return acc;
    const managedProjectId = acc.managedProjectId || acc.projectId || "rising-fact-p41fc";
    const projectId = acc.projectId || "rising-fact-p41fc";
    return acc.managedProjectId ? acc : { ...acc, projectId, managedProjectId };
  });
}

async function runQuota(cli) {
  const legacyPath = resolve(cli.getStoragePath());
  const source = await cli.createDefaultAccountStoreOperations().read(legacyPath);
  if (source.kind === "unavailable") {
    throw new Error(`Accounts are unavailable: ${source.reason}`);
  }
  const rawAccounts = Array.isArray(source.accounts) ? source.accounts : [];
  // Avoid 3.1.13 ensureProjectContext's 10x5s onboardManagedProject polling loop
  // on accounts without a cached managedProjectId during interactive quota checks.
  const quotaAccounts = buildQuotaAccounts(rawAccounts);
  const quiet = { debug() {}, info() {}, warn() {}, error() {} };
  await cli.startRuntimeProcessHeartbeat(quiet);
  try {
    const results = await cli.checkAccountsQuotaStandalone(quotaAccounts, { refresh: true });
    const formatted = results.map((result, idx) =>
      formatQuotaResult(result, idx + 1, quotaAccounts[idx]?.email, cli.quotaSummary));
    process.stdout.write(`${JSON.stringify({ accounts: formatted })}\n`);
  } finally {
    await cli.removeProcessHeartbeat(quiet).catch(() => {});
  }
}

async function runHealthToken(cli, argv) {
  const emailFlagIndex = argv.indexOf("--email");
  const email = emailFlagIndex >= 0 ? String(argv[emailFlagIndex + 1] ?? "").trim() : "";
  if (!email) {
    throw new Error("health-token requires --email <address>");
  }
  const legacyPath = resolve(cli.getStoragePath());
  const source = await cli.createDefaultAccountStoreOperations().read(legacyPath);
  if (source.kind === "unavailable") {
    throw new Error(`Accounts are unavailable: ${source.reason}`);
  }
  const accounts = Array.isArray(source.accounts) ? source.accounts : [];
  const normalized = email.toLowerCase();
  const matches = accounts.filter(
    (acc) => typeof acc?.email === "string" && acc.email.trim().toLowerCase() === normalized,
  );
  if (matches.length !== 1) {
    throw new Error(`Google account lookup failed for ${email}`);
  }
  const account = matches[0];
  if (account.enabled === false) {
    throw new Error(`Google account is disabled: ${email}`);
  }
  const quiet = { debug() {}, info() {}, warn() {}, error() {} };
  await cli.startRuntimeProcessHeartbeat(quiet);
  try {
    const auth = cli.buildAuthFromAccount(account);
    const refreshed = await cli.refreshAccessToken(auth);
    const expires = Number(refreshed?.expires);
    const accessToken = typeof refreshed?.access === "string" ? refreshed.access : "";
    if (!accessToken || !Number.isFinite(expires) || expires <= Date.now()) {
      throw new Error(`Google token refresh failed for ${email}`);
    }
    const parts = cli.parseRefreshParts(refreshed.refresh ?? auth.refresh ?? "");
    process.stdout.write(`${JSON.stringify({
      email: account.email,
      accessToken,
      expires,
      projectId: parts.projectId || account.projectId || "",
    })}\n`);
  } finally {
    await cli.removeProcessHeartbeat(quiet).catch(() => {});
  }
}

const [cliFile, mode, ...restArgs] = process.argv.slice(2);
let isMain = false;
try {
  isMain = Boolean(process.argv[1]) && import.meta.url === pathToFileURL(realpathSync(process.argv[1])).href;
} catch {}
if (isMain) {
  const isQuotaMode = mode === "--quota" || mode === "quota";
  const isHealthTokenMode = mode === "health-token";
  if (!cliFile || (mode !== "--login" && !isQuotaMode && !isHealthTokenMode)) {
    process.stderr.write("Usage: google-login-3113.mjs <cli.js> <--login|--quota|health-token --email <email>>\n");
    process.exit(1);
  }

  try {
    const cli = await loadCli3113(cliFile);
    if (mode === "--login") {
      await runLogin(cli);
    } else if (isQuotaMode) {
      await runQuota(cli);
    } else {
      await runHealthToken(cli, restArgs);
    }
  } catch (err) {
    process.stderr.write(`${err instanceof Error ? err.message : String(err)}\n`);
    process.exit(1);
  }
}
