# KathaChepta Engineering Handoff

Operational guide for continuing work in another session. Read [ARCHITECTURE.md](ARCHITECTURE.md) for the
design and [BACKLOG.md](BACKLOG.md) for the phase plan. Current state: **Phase 0 complete, awaiting review.**

## Runtime

`docker compose up -d --build` runs everything on the desktop (the hosting environment until Phase 6):

| Service | Purpose |
|---|---|
| `postgres` | PostgreSQL 16 + pgvector. Host port 127.0.0.1:5433 for tests and admin tools only |
| `api` | FastAPI (Uvicorn, 2 processes). Runs `alembic upgrade head` on start |
| `worker-media` (×`KC_MEDIA_WORKERS`) | Pulls `media.process` and `transcription` jobs |
| `caddy` | Reverse proxy on :8080 (LAN-reachable). TLS on Lightsail in Phase 6 |
| `mailpit` | Catches development email (sign-in codes) at http://localhost:8025 |
| `backup` | `pg_dump` at start and daily at 02:30 UTC into `data/backups/`, kept 14 days |
| GPU worker (not in Docker) | `scripts/run_gpu_worker.ps1`: pulls `teaser` (LM Studio) and `artwork` jobs |

Secrets live in `.env` (created by `scripts/setup_local.py`, never committed). `/api/health` reports the
running build, process ID, and supported processing actions; every response carries
`X-KathaChepta-Server` and `X-Request-Id` headers.

## Accounts and roles

`ROLE_PERMISSIONS` in `api/app/security.py` is the only authority; the UI hides what the API forbids.

| Role | Permissions |
|---|---|
| listener | catalog.read |
| parent | catalog.read, library.manage |
| narrator | catalog.read, narrator.upload, narrator.pipeline, narrator.history |
| editor | catalog.read, transcript.review, teaser.review, content.publish, rights.manage, metadata.review |
| admin | editor permissions + users.manage, library.manage, jobs.manage |

Sign-in methods:
- Username or email + password (argon2; prototype PBKDF2 hashes are upgraded on first login).
- Email one-time code: `POST /api/auth/otp/request` then `/api/auth/otp/verify` (creates a listener account).
- Mobile: add `"client": "mobile"` to either login to receive a 15-minute access token and a 60-day
  refresh token. `POST /api/auth/refresh` rotates; reusing an old refresh token ends the whole session family.
- Staff two-factor (TOTP): `/api/auth/totp/setup` and `/api/auth/totp/verify`. Required in production
  (`KC_STAFF_MFA_REQUIRED=true`); optional locally. Until verified, staff sessions have no permissions.

Operator CLI: `docker compose exec api python -m app.cli create-user|set-password|set-role|reset-mfa|create-worker|seed-demo`.

## Jobs and workers

- Job types: `media.process` (capability `media`), `transcription` (`stt`), `teaser` (`llm`), `artwork` (`image`).
- Workers authenticate with `Authorization: Worker <token>`, lease jobs (`POST /api/worker/lease`), send
  heartbeats, upload output files, and report `complete` or `fail`. The API validates and applies results;
  workers never touch the database.
- Failures retry with exponential back-off (30 s × 2^attempt) up to `max_attempts`, then become `dead`.
  An expired lease (worker crashed) is picked up again automatically.
- Admin view: `GET /api/admin/jobs`; retry a dead job: `POST /api/admin/jobs/{id}/retry`;
  queue audio processing for everything unprocessed: `POST /api/admin/backfill`.
- Uploads trigger `media.process` automatically. Transcription, teasers, and artwork are still started by an
  editor in Phase 0; Phase 2 chains them automatically.

## Media

- Storage keys: `legacy/…` (prototype audio, read-only mount of `audio/`), `originals/<asset>/…`
  (narrator uploads), `renditions/<asset>/v<n>/standard.m4a|datasaver.m4a`, `artworks/<asset>/…`,
  `transcripts/<asset>/…`, `reports/…`.
- Clients only receive signed `/media/<key>?e=&s=` URLs (HMAC with `KC_SECRET_KEY`, 6-hour expiry) that
  support HTTP Range requests.
- Audio processing normalizes to −16 LUFS / −1.5 dBTP, writes a 64 kbps and a 32 kbps mono AAC version, a
  200-point waveform, and QC checks (quiet, clipping, background sound, long pauses, too short, low sample
  rate) with plain-language tips shown to narrators.

## Engineering rules learned the hard way

- **Never run blocking database calls inside `async def` endpoints.** It deadlocked the API during the
  first media backfill (one request held a row lock while awaiting its body; another blocked the event loop
  waiting for that lock). Async endpoints read the body, then call a sync function via `run_in_threadpool`.
- Keep request transactions short; don't hold locks on shared rows (for example `workers`) across I/O.
- Language tags are BCP 47 (`te-IN`); normalize with `services.assets.normalize_language`.

## Tests

`npm test` (or `docker compose --profile test run --rm api-test`) runs ruff and pytest against a separate
`kathachepta_test` database, migrated from scratch each run. Worker unit tests live in `worker/tests`.
CI (`.github/workflows/ci.yml`) runs the same plus image builds.

## Known limitations (tracked in BACKLOG.md)

- The web pages are the prototype UI adapted to the new API; Phase 1 and Phase 2 replace them.
- The Lightsail bucket storage backend (`KC_STORAGE_BACKEND=s3`) is not implemented yet (Phase 6).
- Artwork still uses Pollinations; the local SDXL provider is Phase 2.
- Rate limiting is per API process (in memory), fine for one VM.
