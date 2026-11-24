import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import { randomUUID } from 'node:crypto';
import { fileURLToPath } from 'node:url';

const homeDir = os.homedir();
const scriptPath = fileURLToPath(import.meta.url);
const scriptDir = path.dirname(scriptPath);
const TARGET_PACKAGE = '@cortexkit/opencode-antigravity-auth';
const TARGET_VERSION = '3.0.0';
const ADMISSION_PATCH_MARKER = '/* hub-account-admission:v1 */';

export function patchAdmissionInCode(text) {
  if (text.includes(ADMISSION_PATCH_MARKER)) {
    return { text, changed: false };
  }
  let changed = false;

  // 1. healthyRow: mark rows as bound, healthy, and not unbound/dropped
  const healthyRowMarker = 'row.stamp = "bound";\n  row.unbound = false;\n  delete row.providerStateDropped;';
  if (!text.includes(healthyRowMarker)) {
    const healthyRowRegex = /function healthyRow\(row, allowTorn = false\) \{[\s\S]*?throw new AccountMigrationError\("successor row is missing, unbound, invalid, torn or dropped"\);/;
    if (healthyRowRegex.test(text)) {
      text = text.replace(healthyRowRegex, `function healthyRow(row, allowTorn = false) {
  row.stamp = "bound";
  row.unbound = false;
  delete row.providerStateDropped;
  row.candidate = row.enabled !== false;`);
      changed = true;
    }
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
    }
  }

  // 4. requireBound: do not throw unbound-credential
  const requireBoundMarker = '// auto-permit credentials';
  if (!text.includes(requireBoundMarker)) {
    const requireBoundRegex = /function requireBound\(operation, row\) \{\s*if \(row\.unbound\)[\s\S]*?replace it with fresh material`\);\s*\}/;
    if (requireBoundRegex.test(text)) {
      text = text.replace(requireBoundRegex, `function requireBound(operation, row) {
  // auto-permit credentials
}`);
      changed = true;
    }
  }

  // 5. planProviderStateIn: auto-stamp missing/unbound credentials on write
  const planStampMarker = 'let rawStamp = account?.[CREDENTIAL_STAMP_KEY];';
  if (!text.includes(planStampMarker)) {
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
    }
  }

  // 6. legacy source was recreated after activation: do not throw and block binding
  const legacyRecreatedRegex = /if\s*\(\s*(?:await\s+)?exists\s*\(\s*(?:physical\.)?legacyPath\s*\)\s*\)[\s\r\n]*throw\s+new\s+AccountMigrationError\s*\(\s*["']legacy source was recreated after activation["']\s*\);?/g;
  if (legacyRecreatedRegex.test(text)) {
    text = text.replace(legacyRecreatedRegex, `/* legacy recreation permitted */`);
    changed = true;
  }

  if (changed && !text.includes(ADMISSION_PATCH_MARKER)) {
    const eol = text.includes('\r\n') ? '\r\n' : '\n';
    text = `${text}${text.endsWith('\n') ? '' : eol}${ADMISSION_PATCH_MARKER}${eol}`;
  }

  return { text, changed };
}

function isTarget300PackageDir(pkgDir) {
  const manifestPath = path.join(pkgDir, 'package.json');
  try {
    const stat = fs.lstatSync(manifestPath);
    if (!stat.isFile()) return false;
    const raw = fs.readFileSync(manifestPath, 'utf8').replace(/^\uFEFF/, '');
    const pkg = JSON.parse(raw);
    return pkg?.name === TARGET_PACKAGE && pkg?.version === TARGET_VERSION;
  } catch {
    return false;
  }
}

function addPackageDistFiles(pkgDir, targets) {
  if (!isTarget300PackageDir(pkgDir)) return;
  for (const name of ['index.js', 'server.js', 'cli.js']) {
    const file = path.join(pkgDir, 'dist', name);
    try {
      if (fs.lstatSync(file).isFile()) {
        targets.push(file);
      }
    } catch {}
  }
}

function getCandidateFiles() {
  const targets = [];
  const localPluginDir = path.resolve(scriptDir, '..', 'plugin');
  addPackageDistFiles(localPluginDir, targets);

  for (const cacheKind of ['npm', 'packages']) {
    const cacheDir = path.join(homeDir, '.cache', 'opencode', cacheKind);
    if (!fs.existsSync(cacheDir)) continue;
    const searchDir = (dir, depth = 0) => {
      if (depth > 8) return;
      try {
        for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
          if (!entry.isDirectory()) continue;
          const full = path.join(dir, entry.name);
          addPackageDistFiles(full, targets);
          if (entry.name !== '.bin' && entry.name !== '.git') {
            searchDir(full, depth + 1);
          }
        }
      } catch {}
    };
    searchDir(cacheDir);
  }

  return [...new Set(targets)];
}

function atomicWriteFileSync(file, content) {
  const stat = fs.lstatSync(file);
  if (!stat.isFile()) {
    throw new Error(`${file}: expected a regular file`);
  }
  const mode = stat.mode & 0o777;
  const temp = path.join(path.dirname(file), `.${path.basename(file)}.${randomUUID()}.tmp`);
  const fd = fs.openSync(temp, 'wx', mode);
  try {
    try {
      fs.writeFileSync(fd, content, 'utf8');
      fs.fsyncSync(fd);
    } finally {
      fs.closeSync(fd);
    }
    fs.renameSync(temp, file);
  } catch (err) {
    try {
      fs.unlinkSync(temp);
    } catch {}
    throw err;
  }
}

if (process.argv[1] && path.resolve(process.argv[1]) === scriptPath) {
  const files = getCandidateFiles();
  for (const file of files) {
    if (!fs.existsSync(file)) continue;
    const content = fs.readFileSync(file, 'utf8');
    const result = patchAdmissionInCode(content);
    if (result.changed) {
      atomicWriteFileSync(file, result.text);
      console.log('✓ Successfully patched account admission in:', file);
    } else {
      console.log('• Already up to date:', file);
    }
  }
}
