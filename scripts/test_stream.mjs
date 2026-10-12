import path from 'node:path';
import os from 'node:os';
import fs from 'node:fs';

const homeDir = os.homedir();
const pluginDist = path.resolve(import.meta.dirname, '..', 'plugin', 'dist', 'index.js');
const authFile = path.join(homeDir, '.local', 'share', 'opencode', 'auth.json');

async function main() {
  if (!fs.existsSync(authFile)) {
    console.error(`[Error] Auth file not found at: ${authFile}. Please login first.`);
    process.exit(1);
  }

  const { AntigravityCLIOAuthPlugin } = await import(`file://${pluginDist.replace(/\\/g, '/')}`);

  const fakeClient = {
    tui: { showToast: async (args) => console.log('[Toast]', args?.body?.message || args) },
    auth: { set: async (args) => console.log('[Auth.set]', args) }
  };

  const plugin = await AntigravityCLIOAuthPlugin({
    client: fakeClient,
    directory: homeDir
  });

  const authData = JSON.parse(fs.readFileSync(authFile, 'utf8'));
  const getAuth = async () => authData.google;

  console.log('Testing authentication loader...');
  const loaderResult = await plugin.auth.loader(getAuth, { models: {} });

  const model = process.argv[2] || 'antigravity-gemini-3.8-flash';
  console.log(`Sending streaming prompt to model: ${model}...`);

  const url = `https://generativelanguage.googleapis.com/v1beta/models/${model}:streamGenerateContent?alt=sse`;
  const body = JSON.stringify({
    contents: [
      {
        role: 'user',
        parts: [{ text: 'Привет! Ответь одним кратким предложением: ты работаешь?' }]
      }
    ],
    generationConfig: {
      thinkingConfig: {
        thinkingBudget: -1,
        includeThoughts: true
      }
    }
  });

  const res = await loaderResult.fetch(url, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body
  });

  console.log(`Response HTTP Status: ${res.status} ${res.statusText}`);
  if (!res.ok) {
    const errText = await res.text();
    console.error('Response error body:', errText);
    process.exit(1);
  }

  console.log('\n--- Streaming response ---');
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let totalChunks = 0;

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    totalChunks++;
    const chunk = decoder.decode(value);
    process.stdout.write(chunk);
  }

  console.log(`\n\n✓ Stream completed successfully! Total chunks: ${totalChunks}`);
  await plugin.dispose?.();
}

main().catch(err => {
  console.error('Stream test failed:', err);
  process.exit(1);
});
