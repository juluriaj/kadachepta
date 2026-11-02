// Sends the current app code to installed builds over the air (EAS Update), no new build needed.
// Uses the same EXPO_PUBLIC_* settings as the build profile in app/eas.json, because `eas update` doesn't read
// build profile env. Usage: npm run app:update -- "what changed"                (review builds: desktop server)
//                           npm run app:update -- --profile pilot "what changed"  (pilot builds: Lightsail)
import { spawnSync } from 'node:child_process';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

const appDir = fileURLToPath(new URL('../app/', import.meta.url));
const args = process.argv.slice(2);
const profileAt = args.indexOf('--profile');
const profileName = profileAt >= 0 ? args.splice(profileAt, 2)[1] : 'preview';
const profile = JSON.parse(readFileSync(`${appDir}eas.json`, 'utf8')).build[profileName];
if (!profile) {
  console.error(`No build profile "${profileName}" in app/eas.json.`);
  process.exit(1);
}
const message = args.join(' ') || 'Review update';
// Exports into app/dist-update: app/dist is the web app Caddy serves, and `eas update` would replace it.
// Windows runs npx through the shell, which would split the message into words: quote it there.
const shell = process.platform === 'win32';
const result = spawnSync('npx', ['--yes', 'eas-cli@latest', 'update', '--channel', profile.channel,
  '--platform', 'android', '--environment', profileName === 'production' ? 'production' : 'preview',
  '--input-dir', 'dist-update', '--message', shell ? `"${message.replace(/"/g, "'")}"` : message, '--non-interactive'], {
  cwd: appDir, stdio: 'inherit', shell, env: { ...process.env, ...profile.env },
});
process.exit(result.status ?? 1);
