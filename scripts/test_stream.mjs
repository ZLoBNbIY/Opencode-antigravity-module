import path from 'node:path';
import os from 'node:os';
import fs from 'node:fs';
import { pathToFileURL } from 'node:url';

const homeDir = os.homedir();
const authFile = path.join(homeDir, '.local', 'share', 'opencode', 'auth.json');

function getPluginCandidates() {
  if (process.env.OPENCODE_ANTIGRAVITY_PLUGIN) {
    return [path.resolve(process.env.OPENCODE_ANTIGRAVITY_PLUGIN)];
  }
  const candidates = [];
  const localPlugin = path.resolve(import.meta.dirname, '..', 'plugin', 'dist', 'index.js');
  if (fs.existsSync(localPlugin)) candidates.push(localPlugin);

  // Search npm cache
  const npmCacheDir = path.join(homeDir, '.cache', 'opencode', 'npm');
  if (fs.existsSync(npmCacheDir)) {
    const searchDir = (dir, depth = 0) => {
      if (depth > 8) return;
      try {
        for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
          const full = path.join(dir, entry.name);
          if (entry.isDirectory()) {
            const indexFile = path.join(full, 'dist', 'index.js');
            if (fs.existsSync(indexFile)) {
              candidates.push(indexFile);
            } else if (entry.name !== '.bin' && entry.name !== '.git') {
              searchDir(full, depth + 1);
            }
          }
        }
      } catch {}
    };
    searchDir(npmCacheDir);
  }

  return [...new Set(candidates)];
}

async function main() {
  if (!fs.existsSync(authFile)) {
    console.error(`[Error] Auth file not found at: ${authFile}. Please login first.`);
    process.exit(1);
  }

  const pluginCandidates = getPluginCandidates();
  if (pluginCandidates.length === 0) {
    throw new Error('No local or cached Antigravity plugin bundle was found');
  }
  let AntigravityCLIOAuthPlugin;
  let importError;
  for (const pluginDist of pluginCandidates) {
    try {
      ({ AntigravityCLIOAuthPlugin } = await import(pathToFileURL(pluginDist).href));
      break;
    } catch (error) {
      importError = error;
    }
  }
  if (!AntigravityCLIOAuthPlugin) {
    throw new Error(`Could not load plugin bundle: ${importError?.message || 'unknown import error'}`);
  }

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

  console.log('\n--- Streaming diagnostics (thinking text is not printed) ---');
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let totalChunks = 0;
  let buffer = '';
  let eventCount = 0;
  let candidateEvents = 0;
  const candidateShapes = new Set();
  let finishReason = null;
  let responseText = '';

  while (true) {
    let timeoutId;
    let next;
    try {
      next = await Promise.race([
        reader.read(),
        new Promise((_, reject) => {
          timeoutId = setTimeout(() => reject(new Error('Timed out waiting for stream completion after 90 seconds')), 90000);
        })
      ]);
    } catch (error) {
      await reader.cancel('stream diagnostic timeout');
      throw error;
    } finally {
      clearTimeout(timeoutId);
    }
    const { done, value } = next;
    if (done) break;
    totalChunks++;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split('\n');
    buffer = lines.pop() || '';
    for (const line of lines) {
      if (!line.startsWith('data:')) continue;
      const json = line.slice(5).trim();
      if (!json || json === '[DONE]') continue;
      try {
        const event = JSON.parse(json);
        eventCount++;
        if (Array.isArray(event.candidates)) {
          candidateEvents++;
          candidateShapes.add('top-level');
          const candidate = event.candidates[0];
          finishReason = candidate?.finishReason || finishReason;
          const parts = candidate?.content?.parts;
          if (Array.isArray(parts)) {
            for (const part of parts) {
              if (part.thought !== true && typeof part.text === 'string') responseText += part.text;
            }
          }
        } else if (event.response && Array.isArray(event.response.candidates)) {
          candidateEvents++;
          candidateShapes.add('response-wrapped');
          const candidate = event.response.candidates[0];
          finishReason = candidate?.finishReason || finishReason;
          const parts = candidate?.content?.parts;
          if (Array.isArray(parts)) {
            for (const part of parts) {
              if (part.thought !== true && typeof part.text === 'string') responseText += part.text;
            }
          }
        }
      } catch {
        // Ignore non-JSON SSE data events; the plugin's transform handles them too.
      }
    }
  }

  buffer += decoder.decode();

  console.log(`✓ Stream completed. chunks=${totalChunks}, events=${eventCount}, candidateEvents=${candidateEvents}, shape=${[...candidateShapes].join(',') || 'unknown'}, finishReason=${finishReason || 'not reported'}`);
  console.log(`Model text: ${responseText.trim() || '(no text returned)'}`);
  await plugin.dispose?.();
}

main().catch(err => {
  console.error('Stream test failed:', err);
  process.exit(1);
});
