// Sends the current app code to installed review builds over the air (EAS Update), no new build needed.
// Uses the same EXPO_PUBLIC_* settings as the "preview" build profile in app/eas.json, because
// `eas update` doesn't read build profile env. Usage: npm run app:update -- "what changed"
import { spawnSync } from 'node:child_process';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

const appDir = fileURLToPath(new URL('../app/', import.meta.url));
const profile = JSON.parse(readFileSync(`${appDir}eas.json`, 'utf8')).build.preview;
const message = process.argv.slice(2).join(' ') || 'Review update';
const result = spawnSync('npx', ['--yes', 'eas-cli@latest', 'update', '--channel', profile.channel,
  '--platform', 'android', '--message', message, '--non-interactive'], {
  cwd: appDir, stdio: 'inherit', shell: process.platform === 'win32', env: { ...process.env, ...profile.env },
});
process.exit(result.status ?? 1);
