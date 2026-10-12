import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';

const homeDir = os.homedir();
const localPluginPath = path.resolve(import.meta.dirname, '..', 'plugin');

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

for (const basePath of targetPaths) {
  console.log(`\n=== Applying patches to: ${basePath} ===`);

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
