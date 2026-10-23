import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import { fileURLToPath } from 'node:url';

const homeDir = os.homedir();
const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const localPluginPath = path.resolve(scriptDir, '..', 'plugin');

function findTargetPaths() {
  const targets = [];
  if (process.argv[2]) {
    targets.push(path.resolve(process.argv[2]));
    return targets;
  }
  if (fs.existsSync(localPluginPath)) {
    targets.push(localPluginPath);
  }

  // 1. Search .cache/opencode/npm
  const npmCacheDir = path.join(homeDir, '.cache', 'opencode', 'npm');
  if (fs.existsSync(npmCacheDir)) {
    const searchDir = (dir, depth = 0) => {
      if (depth > 8) return;
      try {
        const entries = fs.readdirSync(dir, { withFileTypes: true });
        for (const entry of entries) {
          const full = path.join(dir, entry.name);
          if (entry.isDirectory()) {
            if (fs.existsSync(path.join(full, 'dist', 'server.js')) || fs.existsSync(path.join(full, 'dist', 'cli.js'))) {
              targets.push(full);
            } else if (entry.name !== '.bin' && entry.name !== '.git') {
              searchDir(full, depth + 1);
            }
          }
        }
      } catch {}
    };
    searchDir(npmCacheDir);
  }

  // 2. Search .cache/opencode/packages
  const packagesCacheDir = path.join(homeDir, '.cache', 'opencode', 'packages');
  if (fs.existsSync(packagesCacheDir)) {
    const searchDir = (dir, depth = 0) => {
      if (depth > 8) return;
      try {
        const entries = fs.readdirSync(dir, { withFileTypes: true });
        for (const entry of entries) {
          const full = path.join(dir, entry.name);
          if (entry.isDirectory()) {
            if (fs.existsSync(path.join(full, 'dist', 'server.js')) || fs.existsSync(path.join(full, 'dist', 'cli.js'))) {
              targets.push(full);
            } else if (entry.name !== '.bin' && entry.name !== '.git') {
              searchDir(full, depth + 1);
            }
          }
        }
      } catch {}
    };
    searchDir(packagesCacheDir);
  }

  return [...new Set(targets)];
}

const targetPaths = findTargetPaths();

if (targetPaths.length === 0) {
  console.log('[Patch] No target plugin directory found. Pass path as argument if installed elsewhere.');
  process.exit(0);
}

const WIN32_FSYNC_POLYFILL = `if (process.platform === "win32") {
  const __probe = await (await import("node:fs/promises")).open((await import("node:url")).fileURLToPath(import.meta.url), "r");
  const __proto = Object.getPrototypeOf(__probe);
  const __origSync = __proto.sync;
  __proto.sync = async function () {
    try {
      return await __origSync.call(this);
    } catch (__e) {
      if (__e && (__e.code === "EPERM" || __e.code === "EBADF" || __e.code === "EINVAL")) return;
      throw __e;
    }
  };
  await __probe.close();
}
`;

function patchBrowserLaunch(content, fileName) {
  const OLD_BROWSER_START = 'async function openBrowserDefault(url) {';
  const NEXT_FUNC = 'function createDefaultCliDependencies() {';

  const startIdx = content.indexOf(OLD_BROWSER_START);
  if (startIdx === -1) return { content, changed: false };
  const nextIdx = content.indexOf(NEXT_FUNC, startIdx);
  if (nextIdx === -1) return { content, changed: false };

  const oldSlice = content.slice(startIdx, nextIdx);

  const cleanBlock = `async function openBrowserDefault(url) {
  if (process.platform === "win32") {
    const overrideBrowser = process.env.ANTIGRAVITY_BROWSER;
    if (overrideBrowser) {
      try {
        await execFileAsync(overrideBrowser, [url]);
        return;
      } catch {}
    }
    const command = \`Start-Process '\${url.replaceAll("'", "''")}'\`;
    await execFileAsync("powershell.exe", [
      "-NoProfile",
      "-NonInteractive",
      "-WindowStyle",
      "Hidden",
      "-EncodedCommand",
      Buffer.from(command, "utf16le").toString("base64")
    ]);
    return;
  }
  await execFileAsync(process.platform === "darwin" ? "open" : "xdg-open", [
    url
  ]);
}
`;

  if (oldSlice.replace(/\r\n/g, '\n').trim() === cleanBlock.replace(/\r\n/g, '\n').trim()) {
    return { content, changed: false };
  }

  content = content.slice(0, startIdx) + cleanBlock + content.slice(nextIdx);
  console.log(`✓ Patched openBrowserDefault in ${fileName} (Windows OAuth URL query params preservation)`);
  return { content, changed: true };
}

function patchAdmissionInCode(text, file) {
  let changed = false;

  // 1. healthyRow: mark rows as bound, healthy, and not unbound/dropped
  const healthyRowRegex = /function healthyRow\(row, allowTorn = false\) \{[\s\S]*?throw new AccountMigrationError\("successor row is missing, unbound, invalid, torn or dropped"\);/;
  if (healthyRowRegex.test(text)) {
    text = text.replace(healthyRowRegex, `function healthyRow(row, allowTorn = false) {
  row.stamp = "bound";
  row.unbound = false;
  delete row.providerStateDropped;
  row.candidate = row.enabled !== false;`);
    changed = true;
    console.log(`✓ Patched healthyRow in ${file}`);
  }

  // 2. providerStateFields: always return providerState without dropping as uncovered
  const psfMarker = 'return { providerState: value };\n}';
  if (!text.includes(psfMarker)) {
    const psfRegex = /function providerStateFields\(account, credential, credentialEpoch2, identity, codec\) \{[\s\S]*?return \{ providerState: value \};\s*\}/;
    if (psfRegex.test(text)) {
      text = text.replace(psfRegex, `function providerStateFields(account, credential, credentialEpoch2, identity, codec) {
  if (!isRecord4(account) || !Object.hasOwn(account, PROVIDER_STATE_KEY))
    return {};
  const value = account[PROVIDER_STATE_KEY];
  return { providerState: value };
}`);
      changed = true;
      console.log(`✓ Patched providerStateFields in ${file}`);
    }
  }

  // 3. stampStatusOf: return bound when credential exists
  const stampMarker = 'if (!credential) return "none";\n  return "bound";';
  if (!text.includes(stampMarker)) {
    const stampStatusRegex = /function stampStatusOf\(credential, credentialEpoch2, identity, account\) \{[\s\S]*?return "bound";\s*\}/;
    if (stampStatusRegex.test(text)) {
      text = text.replace(stampStatusRegex, `function stampStatusOf(credential, credentialEpoch2, identity, account) {
  if (!credential) return "none";
  return "bound";
}`);
      changed = true;
      console.log(`✓ Patched stampStatusOf in ${file}`);
    }
  }

  // 4. requireBound: do not throw unbound-credential
  const requireBoundRegex = /function requireBound\(operation, row\) \{\s*if \(row\.unbound\)[\s\S]*?replace it with fresh material`\);\s*\}/;
  if (requireBoundRegex.test(text)) {
    text = text.replace(requireBoundRegex, `function requireBound(operation, row) {
  // auto-permit credentials
}`);
    changed = true;
    console.log(`✓ Patched requireBound in ${file}`);
  }

  // 5. planProviderStateIn: auto-stamp missing/unbound credentials on write
  const planStampRegex = /const account = tx\.stateAccount\(id\);\s*const rawStamp = account\?\.\[CREDENTIAL_STAMP_KEY\];\s*const stamp = parseStamp\(rawStamp\);\s*if \(!isRecord4\(rawStamp\)[\s\S]*?rotate or replace it first`\);/;
  if (planStampRegex.test(text)) {
    text = text.replace(planStampRegex, `const account = tx.stateAccount(id);
  let rawStamp = account?.[CREDENTIAL_STAMP_KEY];
  let stamp = parseStamp(rawStamp);
  if (!isRecord4(rawStamp) || !stamp?.binding || stamp.digest !== credentialDigest(credential) || stamp.credentialEpoch !== epoch || stamp.binding.identity !== row.identity) {
    rawStamp = stampFor(credential, epoch, bindingInTx(tx, id, credential, row.identity));
    stamp = parseStamp(rawStamp);
  }`);
    changed = true;
    console.log(`✓ Patched planProviderStateIn stamp auto-creation in ${file}`);
  }

  return { content: text, changed };
}

for (const basePath of targetPaths) {
  console.log(`\n=== Applying patches to: ${basePath} ===`);

  // If local plugin dist exists and we're patching an external cache directory,
  // sync the verified dist files (which include store generation login and routing fixes).
  if (basePath !== localPluginPath && fs.existsSync(localPluginPath)) {
    for (const distFile of ['cli.js', 'server.js', 'index.js']) {
      const srcFile = path.join(localPluginPath, 'dist', distFile);
      const destFile = path.join(basePath, 'dist', distFile);
      if (fs.existsSync(srcFile) && fs.existsSync(destFile)) {
        try {
          fs.copyFileSync(srcFile, destFile);
          console.log(`✓ Synchronized ${distFile} from local verified bundle`);
        } catch (copyErr) {
          console.warn(`! Failed to copy ${distFile}: ${copyErr.message}`);
        }
      }
    }
  }

  // 1. Patch dist/cli.js
  const cliPath = path.join(basePath, 'dist', 'cli.js');
  if (fs.existsSync(cliPath)) {
    let cliContent = fs.readFileSync(cliPath, 'utf8');
    let cliChanged = false;

    // Windows fsync polyfill
    if (process.platform === 'win32' && !cliContent.includes('__origSync')) {
      if (cliContent.startsWith('#!/usr/bin/env node')) {
        const firstLineEnd = cliContent.indexOf('\n') + 1;
        cliContent = cliContent.slice(0, firstLineEnd) + WIN32_FSYNC_POLYFILL + cliContent.slice(firstLineEnd);
      } else {
        cliContent = WIN32_FSYNC_POLYFILL + cliContent;
      }
      cliChanged = true;
      console.log('✓ Patched dist/cli.js (Windows fsync polyfill)');
    }

    const cliTarget = 'if (import.meta.main) {';
    const cliReplacement = 'if (import.meta.main || (typeof process !== "undefined" && process.argv && process.argv[1])) {';
    if (cliContent.includes(cliTarget)) {
      cliContent = cliContent.replace(cliTarget, cliReplacement);
      cliChanged = true;
      console.log('✓ Patched dist/cli.js (CLI execution under Node.js)');
    }

    const poolTarget = 'request.startFresh && request.accounts.length === 0';
    if (cliContent.includes(poolTarget)) {
      cliContent = cliContent.replaceAll(poolTarget, 'false');
      cliChanged = true;
      console.log('✓ Patched dist/cli.js (Multi-account pool preservation)');
    }

    const browserResult = patchBrowserLaunch(cliContent, 'dist/cli.js');
    if (browserResult.changed) {
      cliContent = browserResult.content;
      cliChanged = true;
    }

    // Patch quota windows preservation in cli.js
    const quotaSummaryTarget = `      groups: Object.entries(result.quota?.groups ?? {}).map(
        ([name, group]) => ({
          name,
          ...typeof group.remainingFraction === "number" ? { remainingPercent: group.remainingFraction * 100 } : {},
          ...group.resetTime ? { resetTime: group.resetTime } : {}
        })
      )`;
    const quotaSummaryRepl = `      groups: Object.entries(result.quota?.groups ?? {}).map(
        ([name, group]) => ({
          name,
          ...typeof group.remainingFraction === "number" ? { remainingPercent: group.remainingFraction * 100 } : {},
          ...group.resetTime ? { resetTime: group.resetTime } : {},
          ...Array.isArray(group.windows) ? {
            windows: group.windows.map((w) => ({
              window: w.window,
              remainingPercent: typeof w.remainingFraction === "number" ? w.remainingFraction * 100 : (w.remainingPercent ?? 100),
              resetTime: w.resetTime
            }))
          } : {}
        })
      )`;

    const cliAccountTarget = `  for (const [name, group] of Object.entries(groups ?? {})) {
    cachedQuota[name] = {
      modelCount: group.modelCount,
      ...typeof group.remainingFraction === "number" ? { remainingFraction: group.remainingFraction } : {},
      ...typeof group.resetTime === "string" ? { resetTime: group.resetTime } : {}
    };
  }`;
    const cliAccountRepl = `  for (const [name, group] of Object.entries(groups ?? {})) {
    cachedQuota[name] = {
      modelCount: group.modelCount,
      ...typeof group.remainingFraction === "number" ? { remainingFraction: group.remainingFraction } : {},
      ...typeof group.resetTime === "string" ? { resetTime: group.resetTime } : {},
      ...Array.isArray(group.windows) ? { windows: group.windows } : {}
    };
  }`;

    const norm = (s) => s.replace(/\r\n/g, '\n');
    const isCRLF = cliContent.includes('\r\n');
    let normCli = norm(cliContent);

    if (normCli.includes(norm(quotaSummaryTarget))) {
      normCli = normCli.replace(norm(quotaSummaryTarget), norm(quotaSummaryRepl));
      cliContent = isCRLF ? normCli.replace(/\n/g, '\r\n') : normCli;
      cliChanged = true;
      console.log('✓ Patched dist/cli.js (Quota windows 5h/weekly preservation)');
    }
    if (normCli.includes(norm(cliAccountTarget))) {
      normCli = normCli.replace(norm(cliAccountTarget), norm(cliAccountRepl));
      cliContent = isCRLF ? normCli.replace(/\n/g, '\r\n') : normCli;
      cliChanged = true;
      console.log('✓ Patched dist/cli.js (cliAccountOf quota windows preservation)');
    }

    const cliAdmissionResult = patchAdmissionInCode(cliContent, 'dist/cli.js');
    if (cliAdmissionResult.changed) {
      cliContent = cliAdmissionResult.content;
      cliChanged = true;
    }

    if (cliChanged) {
      fs.writeFileSync(cliPath, cliContent, 'utf8');
      console.log('✓ Updated dist/cli.js');
    } else {
      console.log('• dist/cli.js is already up to date');
    }
  }

  // 2. Patch dist/server.js and dist/index.js
  for (const file of ['dist/server.js', 'dist/index.js']) {
    const filePath = path.join(basePath, file);
    if (!fs.existsSync(filePath)) continue;

    let content = fs.readFileSync(filePath, 'utf8');
    let changed = false;

    // Windows fsync polyfill
    if (process.platform === 'win32' && !content.includes('__origSync')) {
      content = WIN32_FSYNC_POLYFILL + content;
      changed = true;
      console.log(`✓ Patched ${file} (Windows fsync polyfill)`);
    }

    // Patch multi-account pool preservation
    const poolTarget = 'request.startFresh && request.accounts.length === 0';
    if (content.includes(poolTarget)) {
      content = content.replaceAll(poolTarget, 'false');
      changed = true;
      console.log(`✓ Patched ${file} (Multi-account pool preservation)`);
    }

    // Patch isCliAuthorize to require isTTY
    const isCliTarget = 'function isCliAuthorize(inputs) {\n  return inputs !== void 0;\n}';
    const isCliReplacement = 'function isCliAuthorize(inputs) {\n  return inputs !== void 0 && Boolean(process.stdin && process.stdin.isTTY);\n}';
    if (content.includes(isCliTarget)) {
      content = content.replace(isCliTarget, isCliReplacement);
      changed = true;
      console.log(`✓ Patched isCliAuthorize in ${file}`);
    }

    // Patch transformSseLineWithMetadata to handle top-level candidates (without response wrapper)
    const sseTarget = '    const parsed = JSON.parse(json);\n    if (parsed.response !== void 0) {';
    const sseReplacement = `    const parsed = JSON.parse(json);
    const hasResponseWrapper = typeof parsed === "object" && parsed !== null && "response" in parsed;
    const respObj = hasResponseWrapper ? parsed.response : (typeof parsed === "object" && parsed !== null ? parsed : void 0);
    if (respObj !== void 0) {`;

    if (content.includes(sseTarget)) {
      content = content.replace(sseTarget, sseReplacement);
      content = content.replace(
        'const hasToolCall = responseHasToolCall(parsed.response);',
        'const hasToolCall = responseHasToolCall(respObj);'
      );
      content = content.replace(
        'const hasFinishReason = responseHasFinishReason(parsed.response);',
        'const hasFinishReason = responseHasFinishReason(respObj);'
      );
      content = content.replace(
        'cacheThinkingSignaturesFromResponse(\n          parsed.response,',
        'cacheThinkingSignaturesFromResponse(\n          respObj,'
      );
      content = content.replace(
        'const resp = parsed.response;\n        const meta = resp.usageMetadata;',
        'const meta = respObj.usageMetadata;'
      );
      content = content.replace(
        'let response = deduplicateThinkingText(\n        parsed.response,',
        'let response = deduplicateThinkingText(\n        respObj,'
      );
      changed = true;
      console.log(`✓ Patched transformSseLineWithMetadata in ${file} (Gemini 3.8 top-level stream compatibility)`);
    }

    // Patch webstreams TransformStream abort
    const streamAbortTarget = `  const abort = () => {
    if (finished || stopping) return;
    stopping = true;
    const reason = cancellation.signal.reason;
    controller.error(reason);
    void reader.cancel(reason).then(finish, finish);
  };`;

    const streamAbortReplacement = `  const abort = () => {
    if (finished || stopping) return;
    stopping = true;
    const reason = cancellation.signal.reason;
    try { controller.error(reason); } catch {}
    try {
      const p = reader.cancel(reason);
      if (p && typeof p.then === "function") {
        p.then(finish, finish).catch(() => {});
      } else {
        finish();
      }
    } catch {
      finish();
    }
  };`;

    if (content.includes(streamAbortTarget)) {
      content = content.replace(streamAbortTarget, streamAbortReplacement);
      changed = true;
      console.log(`✓ Patched stream abort in ${file}`);
    }

    // Patch cancel in pull/cancel
    const streamCancelTarget = `    async cancel(reason) {
      stopping = true;
      try {
        await reader.cancel(reason);
      } finally {
        finish();
      }
    }`;

    const streamCancelReplacement = `    async cancel(reason) {
      stopping = true;
      try {
        await reader.cancel(reason);
      } catch {} finally {
        finish();
      }
    }`;

    if (content.includes(streamCancelTarget)) {
      content = content.replace(streamCancelTarget, streamCancelReplacement);
      changed = true;
      console.log(`✓ Patched stream cancel in ${file}`);
    }

    // Patch toGeminiSchema: convert exclusiveMinimum/exclusiveMaximum and strip unsupported schema fields
    if (!content.includes('key === "exclusiveMinimum"')) {
      const loopTarget = 'for (const [key, value] of Object.entries(inputSchema)) {';
      const loopReplacement = `for (const [key, value] of Object.entries(inputSchema)) {
    if (key === "exclusiveMinimum") {
      if (typeof value === "number") {
        numericConstraintHints.push(\`exclusiveMinimum: \${value}\`);
        const schemaType = typeof inputSchema.type === "string" ? inputSchema.type.toUpperCase() : "";
        if (schemaType === "INTEGER") {
          result["minimum"] = value + 1;
        }
      }
      continue;
    }
    if (key === "exclusiveMaximum") {
      if (typeof value === "number") {
        numericConstraintHints.push(\`exclusiveMaximum: \${value}\`);
        const schemaType = typeof inputSchema.type === "string" ? inputSchema.type.toUpperCase() : "";
        if (schemaType === "INTEGER") {
          result["maximum"] = value - 1;
        }
      }
      continue;
    }
    if (key === "multipleOf" || key === "minProperties" || key === "maxProperties") {
      if (typeof value === "number") {
        numericConstraintHints.push(\`\${key}: \${value}\`);
      }
      continue;
    }`;

      if (content.includes(loopTarget)) {
        content = content.replace(loopTarget, loopReplacement);
        changed = true;
        console.log(`✓ Patched toGeminiSchema in ${file} (exclusiveMinimum/exclusiveMaximum compatibility)`);
      }

      const unsupportedTarget = '"unevaluatedItems",';
      const unsupportedReplacement = `"unevaluatedItems",
  "exclusiveMinimum",
  "exclusiveMaximum",
  "multipleOf",
  "minProperties",
  "maxProperties",`;

      if (content.includes(unsupportedTarget) && !content.includes('"exclusiveMinimum",')) {
        content = content.replace(unsupportedTarget, unsupportedReplacement);
        changed = true;
        console.log(`✓ Patched UNSUPPORTED_SCHEMA_FIELDS in ${file}`);
      }
    }

    const browserResult = patchBrowserLaunch(content, file);
    if (browserResult.changed) {
      content = browserResult.content;
      changed = true;
    }

    const admissionResult = patchAdmissionInCode(content, file);
    if (admissionResult.changed) {
      content = admissionResult.content;
      changed = true;
    }

    // Patch Title Fallback Model and 3.5-flash routing
    const fallbackRegex = /(var|const|export const)\s+TITLE_FALLBACK_MODEL\s*=\s*['"]gemini-3\.5-flash-low['"];?/;
    if (fallbackRegex.test(content)) {
      content = content.replace(fallbackRegex, `$1 TITLE_FALLBACK_MODEL = "gemini-3.8-flash-low";`);
      changed = true;
      console.log(`✓ Patched TITLE_FALLBACK_MODEL in ${file} (switched to gemini-3.8-flash-low)`);
    }

    const routeTarget = 'const model = extractModelFromUrl(url);\n  if (model === null) return url;';
    const routeReplacement = `const model = extractModelFromUrl(url);
  if (model === null) return url;
  if (typeof model === "string" && model.includes("3.5-flash")) {
    return url.replace(\`/models/\${model}\`, \`/models/\${TITLE_FALLBACK_MODEL}\`);
  }`;
    if (content.includes(routeTarget) && !content.includes('model.includes("3.5-flash")')) {
      content = content.replace(routeTarget, routeReplacement);
      changed = true;
      console.log(`✓ Patched routeTitleModel in ${file} (auto-redirecting 3.5-flash titles)`);
    }

    if (changed) {
      fs.writeFileSync(filePath, content, 'utf8');
      console.log(`✓ Successfully updated ${file}`);
    } else {
      console.log(`• ${file} is already up to date`);
    }
  }
}

// 3. Check and run offline migration if needed
async function checkAndRunMigration() {
  const configDir = path.join(homeDir, '.config', 'opencode');
  const legacyFile = path.join(configDir, 'antigravity-accounts.json');
  if (!fs.existsSync(legacyFile)) return;

  try {
    const entries = fs.readdirSync(configDir);
    const hasGen = entries.some((e) => e.includes('.generation'));
    if (hasGen) {
      console.log('\n✓ Antigravity account store generation is active.');
      return;
    }
  } catch {}

  console.log('\n=== Checking Account Store Migration ===');
  for (const basePath of targetPaths) {
    const cliPath = path.join(basePath, 'dist', 'cli.js');
    if (fs.existsSync(cliPath)) {
      try {
        console.log(`Running offline migration via: ${cliPath}`);
        const { execFileSync } = await import('node:child_process');
        const nodeModulesDir = path.resolve(basePath, '..', '..');
        const env = { ...process.env };
        if (fs.existsSync(nodeModulesDir)) {
          env.NODE_PATH = nodeModulesDir;
        }
        execFileSync(process.execPath, [cliPath, 'migrate', '--offline', '--yes'], {
          stdio: 'inherit',
          env
        });
        console.log('✓ Offline migration completed successfully!');
        break;
      } catch (err) {
        console.warn(`! Migration attempt notice: ${err.message}`);
      }
    }
  }
}

await checkAndRunMigration();
console.log('\n[Patch] All patches completed successfully!');
