# Phase 0 review: foundation and replatform

Everything the prototype did now runs on the new stack on this desktop. This checklist is for your
sign-off. Start the stack with `npm start` (or `docker compose up -d --build`) and open
http://localhost:8080. Development accounts use the password `change-me`.

## Parity checklist

| # | Check | How | Automated test |
|---|---|---|---|
| 1 | Sign in as each role and land in the right place | `listener`/`parent` → listener app, `narrator` → narrator studio, `editor`/`admin` → editorial workspace | `test_auth.py` |
| 2 | Listener: published catalog, artwork, play, pause, seek anywhere | Sign in as `listener`, play the published story, drag the progress bar | `test_listener.py` (Range requests) |
| 3 | Listener: favorites and listening stats survive a reload and a server restart | Heart a story, play a bit, open the profile menu → Favorites / Listening stats; then `npm run stop && npm start` | `test_listener.py` |
| 4 | Narrator: upload, see audio quality feedback within about a minute | Sign in as `narrator`, upload a recording; the pipeline card shows "Checking audio quality…" then the result | `test_narrator.py` |
| 5 | Narrator: profile edit, replacement upload for a published story | Narrator studio | `test_narrator.py` |
| 6 | Editor: queues (transcripts, teasers, submissions, published, **seed catalog** with search) | Editorial workspace tabs | `test_editorial.py` |
| 7 | Editor: story detail with audio, quality panel, metadata, rights, transcript and teaser review | Open any story in "Seed catalog" | `test_editorial.py` |
| 8 | Editor: start transcription / teaser / artwork / audio reprocessing and watch status | Story detail → buttons; status updates every 3 s | `test_editorial.py`, `test_worker.py` |
| 9 | Editor: publish gate (metadata, approved transcript and teaser, rights) and narrator credit | Try publishing an incomplete story: the error lists exactly what's missing | `test_editorial.py` |
| 10 | Data migrated with identical IDs and checksums | Report: `data/media/reports/migration-*.json` | Verification in `migrate_sqlite.py` |

## New in Phase 0 (beyond parity)

- PostgreSQL with migrations; sessions survive restarts; mobile access/refresh tokens with reuse detection.
- Email one-time-code sign-in for listeners (codes visible at http://localhost:8025 in development).
- Staff two-factor authentication (optional locally, enforced in production).
- Job queue with retries, dead-lettering, priorities (people waiting beat bulk work), and pull-based workers.
- Audio pipeline: every story levelled to −16 LUFS, 64 kbps and 32 kbps (data-saver) mobile versions,
  waveform, and quality checks with plain-language tips.
- All 588 seed stories have an owner-attested rights record (KathaChepta), so they only need editorial review.
- Signed, expiring media links with seek support; no file is reachable without one.
- Nightly database backups, health and build diagnostics, request IDs, audit log, rate limits, CSRF protection.
- 40 API tests, 8 worker tests, CI workflow, Lightsail provisioning scripts (not run until Phase 6).

## Known gaps, stated plainly

- The web pages are the prototype UI adapted to the new API; they get replaced in Phases 1–2.
- Local LLM quality is not yet good enough to publish without editing (see `docs/benchmarks/`).
- Artwork still uses Pollinations (internet, unclear commercial terms). Local SDXL comes in Phase 2.
- Seed-catalog metadata is thin: many stories have "Telugu" as their genre and no age range or moral.
  Phase 2's automatic pipeline drafts these for every story.
- Only 5 stories have transcripts. Transcribing all 588 through Sarvam costs money, so it waits for your go-ahead.
- Media storage is the desktop disk. The Lightsail bucket backend is Phase 6.
- `legacy/` holds the retired prototype code until you sign off.
