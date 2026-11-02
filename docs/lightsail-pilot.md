# Moving KathaChepta to Lightsail: web pilot, then Android, then iPhone

This is the runbook for backlog item P6-08. One Lightsail VM takes over from the desktop and becomes the
live server. The pilot opens in three stages, and each stage starts only when the one before it meets its
exit criteria:

| Stage | Who uses it | Client | Needs from you |
|---|---|---|---|
| 1. Web pilot | Invited listeners, narrators, you as editor | `https://app.kathachepta.com` in any browser | AWS account, DNS for the domains |
| 2. Android pilot | Pilot testers on Android phones | APK from an EAS internal link (`pilot` profile) | Nothing new (the Expo login you already have) |
| 3. iPhone pilot | Pilot testers on iPhones | TestFlight | Apple Developer Program account (decision D4) |

**What stays on the desktop:** the GPU worker (LM Studio teasers and SDXL artwork). It pulls jobs from the
server over HTTPS, the same way it pulls from the local stack today. It runs only in the evening
(`KC_GPU_HOURS`, default 19:00-06:00 Central) so the PC is free for trading during the day; AI jobs queue up
in the meantime, and listeners don't notice apart from new reviews waiting for moderation. The desktop Docker
stack stays as the development environment, but after cutover it no longer holds live data.

## Defaults I chose (tell me if you want them changed)

| Topic | Default | Why |
|---|---|---|
| Instance | Lightsail Micro (`micro_3_1`), 1 GB RAM / 2 vCPU / 40 GB SSD, Mumbai (`ap-south-1`): $7/month (your choice, 2026-11-02) | Enough for a small pilot: 2 API workers and 1 media worker, 13 GB of media today, about 13 GB free. Deploys build on the server and take longer there, and the site is slow while they run. Move to the 4 GB plan ($24) when needed: see "Moving to a bigger plan" |
| Media | Stays on the VM disk, with daily automatic snapshots (about $0.05 per GB per month) | The bucket + CDN storage backend isn't built yet. It's worth building once media nears ~50 GB or listeners abroad notice slow starts |
| Domains | Web app at `app.kathachepta.com`, native apps call `api.kathachepta.com`; `kathachepta.com` and `www.` redirect to `app.` (temporary, until a landing page exists); `kadachepta.com`, `kathacheptha.com` and `kadacheptha.com` redirect permanently to `kathachepta.com`; `audibles.in` and `telugustories.org` redirect to `app.` (temporary). Each needs only its `@` record on the server's IP (`www` is a CNAME to `@`) | Decision D3 |
| Environments | One instance, which is production from the start. No staging yet | A pilot doesn't need two servers. `deploy.sh` rolls back on its own if a release fails its health check |
| Secrets | New ones made on the server (database password, media-link signing key, worker tokens) | Desktop secrets have lived on a development machine. Accounts, passwords and staff authenticator codes move with the database; only media links older than 6 hours stop working |
| Sign-up | Open: anyone can create a listener account with a username and password. The site isn't advertised | Ask me if you want an invite list during the pilot |
| Email | Off (`KC_EMAIL_ENABLED=false`, your choice, 2026-11-02): no sign-in codes, no notices, nothing is sent. A forgotten password is reset by you ("Forgotten passwords" below) | Turned on later with an email provider such as Zoho ("Turning email on" below) |
| Deploys | The server builds images from GitHub (the repo is public) and keeps the last two releases for rollback | GitHub Actions image builds and deploys can come after the pilot |

## Stage 1: web pilot

### Before you start (your part, about 1 hour plus waiting)

1. **AWS account** with billing set up. Everything below works from **AWS CloudShell** (the `>_` icon in the
   console, switched to the Mumbai region), so nothing has to be installed on the desktop.

   Or let Claude do the AWS parts from the desktop (the AWS connector). Give it a key of its own:
   - IAM > Policies > Create policy > JSON: paste [`infra/lightsail/iam-setup-policy.json`](../infra/lightsail/iam-setup-policy.json),
     name it `kathachepta-setup`.
   - IAM > Users > Create user `kathachepta-setup` (no console access), attach that policy, then
     Security credentials > Create access key > Command Line Interface.
   - On the desktop: `winget install Amazon.AWSCLI`, open a new terminal, run `aws configure` and type the key
     there (region `ap-south-1`). Never paste it into chat.

   The key works only in Mumbai. It can create and configure Lightsail resources and set up SES for
   `kathachepta.com`. It can't delete anything, touch IAM, or download SSH keys. Delete the access key once
   the pilot server is up: deploys use SSH, not AWS.
2. **Email: not needed for the pilot.** People sign up and sign in with a username and password, and the
   server sends nothing. The SES domain identity for `kathachepta.com` and its DKIM records exist already
   (2026-11-02, still in the SES sandbox), in case you pick SES later instead of Zoho.
3. **DNS access** for `kathachepta.com` and `kadachepta.com` at your registrar.
4. **Merge this branch to `main`.** The server deploys from GitHub `main`.

### Steps

1. **Create the server** (CloudShell):
   ```bash
   git clone https://github.com/juluriaj/kadachepta.git && cd kadachepta
   ALERT_EMAIL=<your email> bash infra/lightsail/provision.sh
   ```
   This creates the instance, a static IP, daily snapshots, the firewall (22, 80, 443) and email alarms
   (instance down, CPU credit running out). It prints the IP. The first boot installs Docker and clones the
   repo, which takes about 5 minutes. Confirm the alarm email AWS sends you. To allow SSH only from home, add
   `SSH_CIDR=<your IP>/32`.
2. **DNS, part 1:** `A` records for `app.kathachepta.com` and `api.kathachepta.com` pointing at the static IP,
   the 3 SES DKIM `CNAME` records, and `TXT _dmarc.kathachepta.com "v=DMARC1; p=none"`. Leave `kathachepta.com`,
   `kadachepta.com` and their `www` names alone for now: they serve the old WordPress site (Lightsail
   instance `kadachepta.com`, 13.233.18.234) until the swap in step 9. Until then Caddy logs failed
   certificate attempts for those four names and keeps retrying; that's expected.
   kathachepta.com's DNS is at Squarespace, which adds `.kathachepta.com` to every name itself: enter `app`,
   `api`, `_dmarc` and `<token>._domainkey`, not the full names. Caddy backs off after failed certificate
   attempts; once DNS is right, `bash infra/lightsail/compose.sh restart caddy` makes it try again at once.
   (2026-11-02: done, and kathachepta.com and `www` were moved to the new server the same day, ahead of step 9,
   because the WordPress site no longer worked.)
3. **SSH key on the desktop:** Lightsail console > Account > SSH keys > download the default key for Mumbai into
   `C:\Users\<you>\.ssh\` (or create the server with `KEY_PAIR=<a key you imported>`; the pilot server uses
   `kathachepta-desktop`, private key `C:\Users\julur\.ssh\kathachepta_lightsail`). Add two lines to the
   desktop `.env`:
   ```
   KC_SERVER_HOST=<static IP>
   KC_SERVER_SSH_KEY=C:\Users\<you>\.ssh\LightsailDefaultKey-ap-south-1.pem
   ```
   `npm run server -- status` checks the connection. It fails until the first boot has finished.
4. **Server settings:** `npm run server -- ssh`, then on the server:
   ```bash
   cd /srv/kathachepta && python3 scripts/setup_local.py --server app.kathachepta.com
   nano .env    # fill SARVAM_API_KEY (email stays off: KC_EMAIL_ENABLED=false)
   ```
   Keep the two `KC_GPU_API_*` lines it prints; you need them in step 7.
5. **First deploy** (empty database): `npm run server -- deploy`. The script builds the images (about 10
   minutes the first time), starts everything, and waits until the API reports the new build. It ends with
   `== Live: https://app.kathachepta.com` once DNS and the certificates are working. Caddy gets the
   certificates by itself; if they are slow, `npm run server -- logs caddy` shows why (usually DNS that hasn't
   spread yet).
6. **Copy the data:**
   - `npm run server -- sync` copies `data/media` (9.8 GB) and the seed recordings in `audio/` (3.2 GB). It
     can run while the desktop still serves, and it resumes if interrupted. Run it a day ahead.
   - `npm run server -- cutover` is the switch itself. It stops the desktop API and media workers, copies the
     media added since the last sync, dumps the desktop database, and replaces the server's database with it.
     The server's own database is saved first. It asks you to type `CUTOVER`. Stop the GPU worker first
     (`npm run worker:gpu:stop`).
7. **GPU worker:** add the two lines from step 4 to the desktop `.env`
   (`KC_GPU_API_URL=https://app.kathachepta.com`, `KC_GPU_API_TOKEN=...`), then run `npm run worker:gpu:stop`
   and `npm run worker:gpu:schedule`. The evening task (installed 2026-11-01) runs 19:00-06:00, or from sign-in
   if that's later; `schedule` restarts it at once if it's already evening, and `data\logs\gpu-schedule.log`
   shows the server it serves. Remove the lines (and repeat the two commands) to point it back at the desktop
   stack. Jobs queued on the desktop move with the database: the October 17 backup had 153 teaser jobs
   waiting, and the GPU worker picks them up from the server in the evening.
8. **Smoke test** before inviting anyone:
   - [ ] `https://app.kathachepta.com` opens
   - [ ] Create a listener account (username and password), sign out and back in; a story plays and seeking
         works
   - [ ] Studio: staff sign-in asks for the authenticator code (two-factor is enforced in production); the
         review queue matches the desktop
   - [ ] As a narrator, record and submit a short story: media processing, transcription and the teaser (GPU
         worker) all finish
   - [ ] `npm run server -- status` shows every container up and healthy, and enough free disk
9. **Swap kathachepta.com to the new app** (DNS, part 2), after the smoke test passes:
   - First import the WordPress users (next section). WordPress stays reachable over SSH by its IP after the
     swap, but it's simpler while the site is still up.
   - Snapshot the WordPress instance (Lightsail > `kadachepta.com` > Snapshots).
   - Change the `A` records of `kathachepta.com`, `www.kathachepta.com`, `kadachepta.com` and
     `www.kadachepta.com` to the new static IP. Leave the `MX` records of kadachepta.com alone: its email
     (Zoho) doesn't move. Within minutes Caddy has certificates for them; `kathachepta.com` then opens the app,
     and `kadachepta.com` forwards to `kathachepta.com`. Old WordPress links land on the app's home page.
   - A week later, if nothing is missing: delete the WordPress instance and release its static IP
     (`kadachepta_india`), which costs money once it's detached.
10. **Invite the pilot listeners** (web link). Watch `npm run server -- logs api` for the first days.

### Importing the WordPress users

Each WordPress user becomes a **listener** account with the same email and, where it fits the app's rules, the
same username. If the export includes WordPress's password hashes, people sign in with their **old WordPress
password** (with their username or their email), which is replaced by a stronger hash on their first sign-in.
Without hashes, or if they forget the password, they need a new one from you ("Forgotten passwords" below)
while email is off. The import **sends no email**, and it never changes an account that already exists here
(same email).

1. **Export the users from WordPress** with one of these (both include the password hashes):
   - **phpMyAdmin** (hosting control panel): open the WordPress database, table `wp_users` (the prefix can
     differ, e.g. `wpab_users`) > Export > Custom > Format **CSV**, tick **"Put columns names in the first
     row"**, then Go.
   - **WP-CLI** (SSH on the old host):
     `wp user list --fields=ID,user_login,user_email,user_pass,display_name,user_registered,roles --format=csv > wp_users.csv`

   Plugin exports work too, as long as they have an email column. The file holds emails and password hashes,
   so keep it out of email and chat, and delete it after the import.
2. **Copy it to the server and do a dry run** (after the cutover, so the accounts land in the live database):
   ```powershell
   scp -i <your .pem key> wp_users.csv ubuntu@<static IP>:/tmp/
   npm run server -- ssh
   ```
   then on the server:
   ```bash
   cd /srv/kathachepta
   bash infra/lightsail/compose.sh cp /tmp/wp_users.csv api:/tmp/wp_users.csv
   bash infra/lightsail/compose.sh exec api python -m app.cli import-wordpress /tmp/wp_users.csv
   ```
   The dry run saves nothing. It reports how many accounts it would create, how many keep their password,
   which rows have bad emails, and the email domains and sign-up years. Old WordPress sites often collect spam
   sign-ups, which show up as many accounts from one odd domain or a burst in one year. If you see that, tell
   me and I'll add a filter before you import.
3. **Import:** run the same command with `--apply`, then `rm /tmp/wp_users.csv`. Running it twice is harmless:
   accounts that already exist are skipped.

Before the move, the same commands work on the desktop instead: `docker compose cp wp_users.csv api:/tmp/` and
`docker compose exec api python -m app.cli import-wordpress /tmp/wp_users.csv`. The cutover then carries the
accounts to the server. When you invite these people, tell them they can sign in with the username or email
and the password they used on the old site, and that they can delete their account from the app if they don't
want it.

### Forgotten passwords

While email is off, nobody can reset their own password. When someone asks you, run on the server
(`npm run server -- ssh`, then `cd /srv/kathachepta`):

```bash
bash infra/lightsail/compose.sh exec api python -m app.cli set-password <their username or email>
```

It prints a new random password to pass on; they can change it in the app (Account > Change password), which
also signs them out on their other devices.

### Turning email on

When you have an email provider (Zoho Mail's SMTP, or SES once it's out of the sandbox), put its settings in
the server `.env` and deploy:

```
KC_EMAIL_ENABLED=true
KC_SMTP_HOST=smtp.zoho.com       # kadachepta.com mail is on zoho.com; SES: email-smtp.ap-south-1.amazonaws.com
KC_SMTP_PORT=587
KC_SMTP_USERNAME=...
KC_SMTP_PASSWORD=...
KC_SMTP_FROM=KathaChepta <no-reply@kathachepta.com>
```

The sign-in screen then offers email codes again, new email addresses need a code to confirm, and narrators
get email notices. Passwords keep working. Email addresses saved while email was off aren't confirmed.

### Exit criteria for stage 1 (about 2 weeks)

- No lost recordings or listening history. Nightly backups appear in `data/backups` on the server.
- A **restore drill** passes: create an instance from last night's snapshot, run
  `bash infra/lightsail/restore.sh data/backups/<latest>.dump --yes` on it, and check that stories play. Then
  delete the drill instance.
- A deploy of a new commit and a rollback have both been done for real.
- Pilot feedback on the web app has been triaged into the backlog.

## Stage 2: Android pilot

The `pilot` build profile (`app/eas.json`) is an installable APK that talks to `https://api.kathachepta.com`.
It allows no plain HTTP and has no server picker, unlike the desktop review build.

1. `npm run app:apk:pilot` (EAS cloud build, about 15 minutes). Share the install link EAS prints with the
   testers. Android asks them to allow installing from the browser.
2. JavaScript-only fixes reach installed pilot phones without a new build:
   `npm run app:update -- --profile pilot "what changed"`.
3. Check on real phones: sign-in, background playback with the screen off, downloads for offline listening,
   drive mode, and recording and uploading on mobile data.

**Exit criteria:** testers use it for a week without crashes or stuck uploads, and background playback
survives screen-off and switching apps. After that, the Play Store listing (P6-03) needs a Google Play
developer account (decision D4).

## Stage 3: iPhone pilot

Installing on real iPhones needs an **Apple Developer Program** membership ($99/year). An organization
account needs a D-U-N-S number, which can take a few weeks, so start it during stage 1. Then:

1. Create the app in App Store Connect with bundle ID `com.kathachepta.app` (already set in `app/app.json`).
2. `cd app && npx eas-cli@latest build -p ios --profile production`, then
   `npx eas-cli@latest submit -p ios`. EAS builds in the cloud, so no Mac is needed, and it handles the
   signing certificates.
3. Add testers in TestFlight. Internal testers (your team, up to 100) don't need Apple's review. External
   testers need a short beta review first.
4. Before the beta review: an iPhone-specific microphone permission text, a privacy policy URL, and the
   children's-app answers (P6-02, P6-03).

**Exit criteria:** the TestFlight beta review passes and testers confirm playback, downloads and recording
work. Then App Store submission (Phase 6).

## Day-to-day operations

| Task | Command (from the desktop) |
|---|---|
| Deploy `main` / a branch or commit | `npm run server -- deploy` / `npm run server -- deploy <ref>` |
| Status, disk, memory | `npm run server -- status` |
| Logs | `npm run server -- logs api` (also `worker-media`, `caddy`, `postgres`, `backup`) |
| Operator CLI (users, roles, MFA reset) | `npm run server -- ssh`, then `bash infra/lightsail/compose.sh exec api python -m app.cli ...` |
| Restore a backup | on the server: `bash infra/lightsail/restore.sh data/backups/<file>.dump --yes` |

- **Deploys** back up the database first (`kathachepta-predeploy-*.dump`). If the API doesn't come up on the
  new build within 3 minutes, `deploy.sh` prints the API log and switches back to the previous release.
  It does not undo database migrations; for those, restore the pre-deploy dump.
- **Backups:** `pg_dump` at start and daily at 02:30 UTC, kept 14 days, plus daily snapshots of the whole
  instance at 02:30 IST (kept 7 days by Lightsail).
- **Server files:** `/srv/kathachepta` is a clean git checkout. Don't edit files there, because deploys refuse
  to run over local edits. `.env`, `data/` and `audio/` are not in git.

### Moving to a bigger plan

Time to move off the $7 plan when `npm run server -- status` shows swap in steady use or the disk over 80%,
or when deploys take more than about 20 minutes. It takes about 15 minutes of downtime, and nothing is rebuilt:

1. Stop writes: on the server, `bash infra/lightsail/compose.sh stop api worker-media`.
2. Lightsail console > the instance > Snapshots > Create snapshot. When it's done, use "Create new instance"
   on the snapshot and pick the 4 GB plan (`medium_3_1`, $24).
3. Stop the old instance, then move the static IP to the new one (Networking > the static IP > Detach, then
   Attach). DNS stays as it is.
4. On the new instance, set `KC_API_WORKERS=3` and `KC_MEDIA_WORKERS=2` in `.env`, then
   `bash infra/lightsail/compose.sh up -d`.
5. Delete the old instance a few days later. Steps 3 and 5 are yours, because the setup key can't detach or
   delete anything.

## After the pilot (tracked in BACKLOG.md P6-05 and P6-08)

- Bucket + CDN storage backend for media (`KC_STORAGE_BACKEND=s3`), and off-site copies of the nightly dumps.
- GitHub Actions: build images in CI and deploy over SSH after the tests pass.
- A staging instance for testing releases before production.
- WAL archiving for point-in-time recovery, an external uptime check, and a status page.
