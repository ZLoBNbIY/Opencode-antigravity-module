// Offline process-boundary fixture: exercise the shipped CLI dispatcher.
import { runCli } from '../../plugin/dist/cli.js';

process.exitCode = await runCli(process.argv.slice(2), {
  stdout: process.stdout,
  stderr: process.stderr,
  accountStore: {
    legacyPath: () => 'unused',
    read: async () => ({ kind: 'store', accounts: [{ email: 'test@example.com' }] }),
  },
  refreshHealthToken: async () => ({
    accessToken: 'fresh-from-node', expires: Date.now() + 3600000, projectId: 'fresh-project',
  }),
});
