import fs from 'node:fs';
import path from 'node:path';
import { createHash, randomUUID } from 'node:crypto';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const scriptPath = fileURLToPath(import.meta.url);
const bundledPath = path.resolve(path.dirname(scriptPath), '..', 'plugin');
const packageName = '@cortexkit/opencode-antigravity-auth';
const version = '3.0.0';
const pinnedPackage = `${packageName}@${version}`;

// The checkout already ships its compatibility changes. Never copy those
// bundles over an npm package or replay the old broad compatibility rewrites.
// This recipe only hardens the updater in the known 3.0.0 layouts.
const files = new Map([
  ['dist/index.js', ['schema', 'hook', 'checker', 'config']],
  ['dist/server.js', ['schema', 'hook', 'checker', 'config']],
  ['dist/src/plugin/config/schema.js', ['schema']],
  ['dist/src/hooks/auto-update-checker/index.js', ['hook']],
  ['dist/src/hooks/auto-update-checker/checker.js', ['checker']],
  ['dist/src/plugin/config/updater.js', ['config']],
]);

function occurrences(text, anchor) {
  if (anchor instanceof RegExp) {
    const regex = new RegExp(anchor.source, anchor.global ? anchor.flags : `${anchor.flags}g`);
    return Array.from(text.matchAll(regex), (match) => ({ value: match[0], offset: match.index }));
  }
  if (anchor.length === 0) throw new Error('empty patch anchor');
  const matches = [];
  for (let offset = text.indexOf(anchor); offset !== -1; offset = text.indexOf(anchor, offset + anchor.length)) {
    matches.push({ value: anchor, offset });
  }
  return matches;
}

export function applyAnchoredEdits(source, edits) {
  let content = source;
  const changed = [];
  for (const [label, before, after, expectedHash] of edits) {
    const old = occurrences(content, before);
    const applied = occurrences(content, after);
    if (old.length === 0 && applied.length === 1) continue;
    if (old.length === 1 && applied.length === 0) {
      const { value, offset } = old[0];
      if (expectedHash && createHash('sha256').update(value).digest('hex') !== expectedHash) {
        throw new Error(`${label}: original block differs from the verified anchor`);
      }
      content = content.slice(0, offset) + after + content.slice(offset + value.length);
      changed.push(label);
      continue;
    }
    const reason = old.length === 0 && applied.length === 0
      ? 'missing anchor'
      : 'ambiguous anchors';
    throw new Error(`${label}: ${reason} (original: ${old.length}, applied: ${applied.length})`);
  }
  return { content, changed };
}

const schemaEdits = [
  ['schema auto-update default', 'auto_update: z.boolean().default(true),', 'auto_update: z.boolean().default(false),'],
  ['fallback auto-update default', 'auto_update: true,', 'auto_update: false,'],
];

function hookEdits(modular) {
  const indent = modular ? '    ' : '  ';
  const quote = modular ? "'" : '"';
  const invocation = 'runBackgroundUpdateCheck(client, directory, autoUpdate).catch((err) => {';
  const background = 'async function runBackgroundUpdateCheck(client, directory, autoUpdate) {';
  const tailAnchor = /^[ \t]+if \(!autoUpdate\) \{\n[ \t]+await showUpdateAvailableToast\(client, latestVersion\);[\s\S]*?\n}\n(?=async function showUpdateAvailableToast)/m;
  const noCacheUpdate = `${indent}await showUpdateAvailableToast(client, latestVersion);\n}\n`;
  const oldToast = /^async function showAutoUpdatedToast\(client, oldVersion, newVersion\) \{[\s\S]*?\n}\n(?=async function showLocalDevToast)/m;
  return [
    ['hook auto-update default', 'showStartupToast = true, autoUpdate = true', 'showStartupToast = true, autoUpdate = false'],
    ['notification-only update path', tailAnchor, noCacheUpdate,
      modular ? '7257975af1155a80a82be794fadd0c12caa285d594e65560616fcc2781571367'
        : '6e01a1ccfb2a64ae426b9d4dd74afe1848abd826f143fb65d608be6582b0016b'],
    ['obsolete auto-updated toast', oldToast, '// Updates are installed explicitly through OpenCode.\n',
      modular ? '011e7966153313534c51379a27a6fbf69eb975d6e23fc90fe105e025d8bf4291'
        : '1ce7b9928e1f6979d94567797034e26904c3974fd225fdaefa70d1b8a2d4cf54'],
    ['opt-in background check', invocation, `if (!autoUpdate) return;\n${' '.repeat(modular ? 16 : 8)}runBackgroundUpdateCheck(client, directory).catch((err) => {`],
    ['background check signature', background, 'async function runBackgroundUpdateCheck(client, directory) {'],
    ['keep explicit pins quiet',
      `${indent}const cachedVersion = getCachedVersion();\n${indent}const currentVersion = cachedVersion ?? pluginInfo.pinnedVersion;`,
      `${indent}if (pluginInfo.isPinned) return;\n${indent}const currentVersion = getCachedVersion();`],
    ['describe missing installed version',
      `logAutoUpdate(${quote}No version found (cached or pinned)${quote});\n${indent}${indent}return;`,
      `logAutoUpdate(${quote}No installed version found${quote});\n${indent}${indent}return;`],
    ['show a manual update notice', 'available. Restart OpenCode to apply.',
      'available. Review it with the OpenCode plugin manager.'],
    ...(modular ? [
      ['remove unused cache invalidation import', "import { invalidatePackage } from './cache';\n", '// Background checks do not modify the OpenCode cache.\n'],
      ['remove unused pin updater import', 'getLocalDevVersion, updatePinnedVersion, }', 'getLocalDevVersion, }'],
      ['remove unused package name import', "import { PACKAGE_NAME } from './constants';\n", '// Plugin selection is handled by the checker.\n'],
    ] : []),
  ];
}

function checkerEdits(modular) {
  const prefix = modular ? 'export ' : '';
  const indent = modular ? '    ' : '  ';
  const removePinWriter = /^(?:export )?function updatePinnedVersion\(configPath, oldEntry, newVersion\) \{(?=[\s\S]*?\.writeFileSync\(configPath, updatedContent,)[\s\S]*?\n}\n(?=(?:export )?async function getLatestVersion)/m;
  const entryLoop = /const plugins = config\.plugin \?\? \[\];\n([ \t]+)for \(const entry of plugins\) \{/;
  const entryIndent = modular ? '            ' : '      ';
  // The V2 shape is `plugins` with string or object entries. Prefer it when
  // present; continue to recognize repositories using the legacy `plugin` key.
  const entries = `const plugins = config.plugins ?? config.plugin ?? [];
${entryIndent}for (const item of plugins) {
${entryIndent}${indent}const entry = typeof item === "string" ? item : item?.package;
${entryIndent}${indent}if (typeof entry !== "string") continue;`;
  return [
    ['disable config pin writes', removePinWriter, `${prefix}function updatePinnedVersion(configPath, oldEntry, newVersion) {\n${indent}// The user's package selection is never updated automatically.\n${indent}return false;\n}\n`,
      modular ? '93f7a713608fc290dbd86cc3be2c224cf2663c4d9c0d8dfeb3d14b533173b746'
        : 'bd7363c82ac8b5f13262882aee99ae8cc0d76d0fdb4bcffb18ec99547955aab7'],
    ['read local plugin entries', new RegExp(`${entryLoop.source}\\n[ \\t]+if \\(entry.startsWith\\(`), `${entries}\n${entryIndent}${indent}if (entry.startsWith(`],
    ['read npm plugin entries', new RegExp(`${entryLoop.source}\\n[ \\t]+if \\(entry === PACKAGE_NAME\\) \\{`), `${entries}\n${entryIndent}${indent}if (entry === PACKAGE_NAME) {`],
  ];
}

function configEdits(modular) {
  const quote = modular ? "'" : '"';
  const indent = modular ? '        ' : '    ';
  const oldPluginList = modular
    ? /        \/\/ Ensure plugin array exists and contains our plugin\n        if \(!Array\.isArray\(config\.plugin\)\) \{\n            config\.plugin = \[\];\n        \}\n        \/\/ Check if plugin is already in the list \(any version\)\n        const hasPlugin = config\.plugin\.some\(\(p\) => p\.includes\('opencode-antigravity-auth'\)\);\n        if \(!hasPlugin\) \{\n            config\.plugin\.push\(PLUGIN_NAME\);\n        \}/
    : /    if \(!Array\.isArray\(config\.plugin\)\) \{\n      config\.plugin = \[\];\n    \}\n    const hasPlugin = config\.plugin\.some\(\n      \(p\) => p\.includes\("opencode-antigravity-auth"\)\n    \);\n    if \(!hasPlugin\) \{\n      config\.plugin\.push\(PLUGIN_NAME\);\n    \}/;
  const bodyIndent = modular ? '            ' : '      ';
  const defaultsIndent = modular ? '                ' : '        ';
  const block = `${indent}const pluginKey = Object.hasOwn(config, "plugins") || !Object.hasOwn(config, "plugin") ? "plugins" : "plugin";
${indent}const hasPlugin = [config.plugins, config.plugin].some((entries) =>
${bodyIndent}Array.isArray(entries) && entries.some((item) => {
${bodyIndent}  const entry = typeof item === "string" ? item : item?.package;
${bodyIndent}  return typeof entry === "string" && entry.includes("opencode-antigravity-auth");
${bodyIndent}})
${indent});
${indent}if (!hasPlugin) {
${bodyIndent}if (!Object.hasOwn(config, pluginKey)) config[pluginKey] = [];
${bodyIndent}if (!Array.isArray(config[pluginKey])) throw new Error(\`Expected an array for \${pluginKey}\`);
${bodyIndent}config[pluginKey].push(PLUGIN_NAME);
${indent}}`;
  return [
    ['default package pin', `PLUGIN_NAME = ${quote}${packageName}@latest${quote};`, `PLUGIN_NAME = ${quote}${pinnedPackage}${quote};`],
    ['new config plugin field', `$schema: SCHEMA_URL,\n${defaultsIndent}plugin: [],`,
      `$schema: SCHEMA_URL,\n${defaultsIndent}plugins: [],`],
    ['preserve existing package entries', oldPluginList, block],
  ];
}

function requireDirectory(file) {
  if (!fs.lstatSync(file).isDirectory()) throw new Error(`${file}: expected a real directory`);
}

function readRegularFile(file) {
  const stat = fs.lstatSync(file);
  if (!stat.isFile()) throw new Error(`${file}: expected a regular file (not a symlink)`);
  return { bytes: fs.readFileSync(file), mode: stat.mode & 0o777 };
}

function readRecipeFile(base, file) {
  const parts = file.split('/');
  let dir = base;
  for (const part of parts.slice(0, -1)) {
    dir = path.join(dir, part);
    requireDirectory(dir);
  }
  const target = path.join(dir, parts.at(-1));
  return { target, ...readRegularFile(target) };
}

function planPatch(base) {
  requireDirectory(base);
  const manifest = path.join(base, 'package.json');
  let pkg;
  try {
    pkg = JSON.parse(readRegularFile(manifest).bytes.toString('utf8').replace(/^\uFEFF/, ''));
  } catch (error) {
    throw new Error(`cannot read package manifest ${manifest}: ${error.message}`);
  }
  if (pkg?.name !== packageName || pkg?.version !== version || pkg?.type !== 'module') {
    throw new Error(`unsupported package (${pkg?.name ?? 'unknown'}@${pkg?.version ?? 'unknown'}); expected ${pinnedPackage} (ESM)`);
  }
  const recipes = { schema: () => schemaEdits, hook: hookEdits, checker: checkerEdits, config: configEdits };
  return Array.from(files, ([file, roles]) => {
    try {
      const original = readRecipeFile(base, file);
      const source = original.bytes.toString('utf8');
      if (!Buffer.from(source).equals(original.bytes)) throw new Error('invalid UTF-8');
      const crlf = source.includes('\r\n');
      if (crlf && source.replaceAll('\r\n', '').includes('\n')) throw new Error('mixed line endings');
      const modular = file.startsWith('dist/src/');
      const edits = roles.flatMap((role) => recipes[role](modular));
      const { content, changed } = applyAnchoredEdits(source.replaceAll('\r\n', '\n'), edits);
      const syntax = spawnSync(process.execPath, ['--input-type=module', '--check'], { input: content, encoding: 'utf8' });
      if (syntax.error) throw syntax.error;
      if (syntax.status !== 0) throw new Error(`JavaScript failed syntax check (${syntax.signal ?? syntax.status})`);
      return { file, ...original, content: crlf ? content.replaceAll('\n', '\r\n') : content, changed };
    } catch (error) {
      throw new Error(`${file}: ${error.message}`);
    }
  });
}

function writePlan(base, plan) {
  const staged = new Map();
  try {
    for (const item of plan.filter(({ changed }) => changed.length)) {
      const temp = path.join(path.dirname(item.target), `.patch-${randomUUID()}.tmp`);
      const fd = fs.openSync(temp, 'wx', item.mode);
      staged.set(item, temp);
      try {
        fs.writeFileSync(fd, item.content, 'utf8');
        fs.fchmodSync(fd, item.mode);
        fs.fsyncSync(fd);
      } finally {
        fs.closeSync(fd);
      }
    }
    for (const [item] of staged) assertUnchanged(base, item);
    for (const [item, temp] of staged) {
      assertUnchanged(base, item);
      try {
        fs.renameSync(temp, item.target);
      } catch (error) {
        throw new Error(`${item.file}: could not replace file: ${error.message}`);
      }
      staged.delete(item);
      console.log(`[Patch] Updated ${item.file}`);
    }
  } finally {
    for (const temp of staged.values()) {
      try {
        fs.unlinkSync(temp);
      } catch (error) {
        console.error(`[Patch] Cannot clean up ${temp}: ${error.message}`);
      }
    }
  }
}

function assertUnchanged(base, item) {
  const current = readRecipeFile(base, item.file);
  if (current.mode !== item.mode || !current.bytes.equals(item.bytes)) {
    throw new Error(`${item.file}: target changed after preflight`);
  }
}

function main(args) {
  const check = args.includes('--check');
  const positional = args.filter((arg) => arg !== '--check');
  if (positional.length > 1 || positional.some((arg) => arg.startsWith('-'))) {
    throw new Error('usage: node scripts/patch_plugin.mjs [--check] [plugin-directory]');
  }
  const base = positional.length ? path.resolve(positional[0]) : bundledPath;
  const plan = planPatch(base);
  if (!check) writePlan(base, plan);
  for (const { file, changed } of plan) {
    if (!changed.length) console.log(`[Patch] Already applied: ${file}`);
    else if (check) console.log(`[Patch] Would update ${file}: ${changed.join(', ')}`);
  }
}

if (process.argv[1] && path.resolve(process.argv[1]) === scriptPath) {
  try {
    main(process.argv.slice(2));
  } catch (error) {
    console.error(`[Patch] Error: ${error.message}`);
    process.exitCode = 1;
  }
}
