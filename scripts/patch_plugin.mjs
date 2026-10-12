import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';

// Target search locations
const homeDir = os.homedir();
const defaultCachePath = path.join(
  homeDir,
  '.cache',
  'opencode',
  'packages',
  '@cortexkit',
  'opencode-antigravity-auth@latest',
  'node_modules',
  '@cortexkit',
  'opencode-antigravity-auth'
);

const localPluginPath = path.resolve(import.meta.dirname, '..', 'plugin');

const targetPaths = [];
if (process.argv[2]) {
  targetPaths.push(path.resolve(process.argv[2]));
} else {
  if (fs.existsSync(localPluginPath)) targetPaths.push(localPluginPath);
  if (fs.existsSync(defaultCachePath)) targetPaths.push(defaultCachePath);
}

if (targetPaths.length === 0) {
  console.log('[Patch] No target plugin directory found. Pass path as argument if installed elsewhere.');
  process.exit(0);
}

for (const basePath of targetPaths) {
  console.log(`\n=== Applying patches to: ${basePath} ===`);

  // 1. Patch dist/cli.js
  const cliPath = path.join(basePath, 'dist', 'cli.js');
  if (fs.existsSync(cliPath)) {
    let cliContent = fs.readFileSync(cliPath, 'utf8');
    let cliChanged = false;
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
      content = content.replace(
        'return {\n        line: `data: ${JSON.stringify(transformed)}`,\n        hasToolCall,\n        hasFinishReason\n      };',
        'return {\n        line: `data: ${JSON.stringify(transformed)}`,\n        hasToolCall,\n        hasFinishReason\n      };'
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
console.log('\n[Patch] All patches completed successfully!');
