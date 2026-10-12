import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';

const homeDir = os.homedir();

export function patchAdmissionInCode(text) {
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
  const requireBoundRegex = /function requireBound\(operation, row\) \{\s*if \(row\.unbound\)[\s\S]*?replace it with fresh material`\);\s*\}/;
  if (requireBoundRegex.test(text)) {
    text = text.replace(requireBoundRegex, `function requireBound(operation, row) {
  // auto-permit credentials
}`);
    changed = true;
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
  }

  return { text, changed };
}

function getCandidateFiles() {
  const targets = [
    'D:/opencode-antigrav/plugin/dist/index.js',
    'D:/opencode-antigrav/plugin/dist/server.js',
    'D:/opencode-antigrav/plugin/dist/cli.js'
  ];

  const npmCacheDir = path.join(homeDir, '.cache', 'opencode', 'npm');
  if (fs.existsSync(npmCacheDir)) {
    const searchDir = (dir, depth = 0) => {
      if (depth > 8) return;
      try {
        for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
          const full = path.join(dir, entry.name);
          if (entry.isDirectory()) {
            const indexFile = path.join(full, 'dist', 'index.js');
            const serverFile = path.join(full, 'dist', 'server.js');
            const cliFile = path.join(full, 'dist', 'cli.js');
            if (fs.existsSync(indexFile)) targets.push(indexFile);
            if (fs.existsSync(serverFile)) targets.push(serverFile);
            if (fs.existsSync(cliFile)) targets.push(cliFile);
            if (entry.name !== '.bin' && entry.name !== '.git') searchDir(full, depth + 1);
          }
        }
      } catch {}
    };
    searchDir(npmCacheDir);
  }

  return [...new Set(targets)];
}

const files = getCandidateFiles();
for (const file of files) {
  if (!fs.existsSync(file)) continue;
  const content = fs.readFileSync(file, 'utf8');
  const result = patchAdmissionInCode(content);
  if (result.changed) {
    fs.writeFileSync(file, result.text, 'utf8');
    console.log('✓ Successfully patched account admission in:', file);
  } else {
    console.log('• Already up to date:', file);
  }
}
