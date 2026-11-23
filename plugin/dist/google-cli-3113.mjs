// Hub entrypoint for the exact cached 3.1.13 CLI. Never writes its code to
// disk and never invokes the regular CLI entrypoint or store migrations.
import { realpath } from "node:fs/promises";
import * as nodeModule from "node:module";
import { pathToFileURL } from "node:url";
import { DueRefreshError, parseDueRefreshArgs, readRetryAfter, refreshDueStore } from "./google-due-store.mjs";

async function refresh(cliFile, account) {
  if (typeof nodeModule.register !== "function") return { status: "unavailable" };
  const cliUrl = pathToFileURL(await realpath(cliFile)).href;
  nodeModule.register("./google-cli-3113-loader.mjs", {
    parentURL: import.meta.url, data: { cliUrl }
  });
  const cli = await import(cliUrl);
  const now = Date.now;
  const anchor = cli.legacyAccountFile();
  const authorized = async () => await cli.readOpenCodeAuthority() === "local";
  const quiet = { debug() {}, info() {}, warn() {}, error() {} };
  if (!await authorized()) return { status: "unavailable" };

  // The native heartbeat prevents a concurrent offline relocation while an
  // OAuth request is in flight; listing alone needs no heartbeat.
  try {
    if (account && !(await cli.startRuntimeProcessHeartbeat(quiet)).path)
      return { status: "unavailable" };
    return await refreshDueStore(account, {
      now,
      open: async () => {
        const modules = await cli.loadCommonAuthStoreModules();
        const admission = await cli.readAccountStoreAdmission(anchor, modules, now);
        if (admission.status !== "active") return null;
        const generation = admission.receipt.id;
        return {
          generation,
          authorized,
          stillActive: async () => (await cli.readAccountStoreAdmission(anchor, modules, now, generation)).status === "active",
          createRepository: (exchange) => cli.createAccountRepositoryFactory(modules)({ paths: admission.paths, now, exchange })
        };
      },
      exchange: (refreshToken) => cli.refreshAntigravityToken(refreshToken, async (...args) => {
        const response = await fetch(...args);
        if (response.ok) return response;
        if (response.status === 429) {
          void response.body?.cancel().catch(() => {});
          throw new DueRefreshError("rate_limited", readRetryAfter(response.headers.get("retry-after")));
        }
        const body = await response.text().catch(() => "");
        const status = cli.parseOAuthErrorPayload(body).code === "invalid_grant" ? "invalid_grant" : "failed";
        throw new DueRefreshError(status);
      })
    });
  } finally {
    if (account) await cli.removeProcessHeartbeat(quiet);
  }
}

const [cliFile, ...args] = process.argv.slice(2);
const request = parseDueRefreshArgs(args);
let result = { status: "unavailable" };
if (cliFile && request) {
  try {
    result = await refresh(cliFile, request.account);
  } catch {
    // Import, profile and repository errors must never reach stderr.
  }
}
process.stdout.write(`${JSON.stringify(result)}\n`);
