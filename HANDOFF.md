# KathaChepta Engineering Handoff

This document is the short operational guide for continuing work in another
model or session. The project is intentionally local-first and currently uses
Python's standard library, SQLite, and browser JavaScript.

## Runtime

Start the unified server:

```powershell
npm start
```

The server listens on `http://127.0.0.1:4173/`.

- `/` is the shared login screen and listener application.
- `/editor/` is protected for `editor` and `admin`.
- `/narrator/` is protected for `narrator`.
- `/api/session` returns `{ authenticated, username, role, permissions }`.

The current development accounts all use `change-me`:

| Username | Role | Main destination |
| --- | --- | --- |
| listener | listener | `/` listener app |
| parent | parent | `/` listener app |
| narrator | narrator | `/narrator/` |
| editor | editor | `/editor/` |
| admin | admin | `/editor/` |

Recreate or repair these accounts with:

```powershell
npm run users:demo
```

## Roles and permissions

Role authorization is enforced by `ROLE_PERMISSIONS` in
`scripts/editor_server.py`; frontend visibility is not security.

- `listener`: `catalog.read`
- `parent`: `catalog.read`, `library.manage`
- `narrator`: `catalog.read`, `narrator.upload`, `narrator.pipeline`,
  `narrator.history`
- `editor`: catalog, transcript review, teaser review, and
  `content.publish`
- `admin`: all editor permissions plus user, rights, and library management

Changing a role requires updating both the permission map and redirect logic
in `app.js`/`editor/editor.js`, then testing direct route access.

## Narrator workflow

1. Narrator signs in and is redirected to `/narrator/`.
2. `POST /api/narrator/upload` accepts a multipart field named `audio`.
   For a published replacement, include `parentAssetId` with the published
   asset ID.
3. The server stores the file under `audio/narrator/<username>/`.
4. A deterministic checksum-derived asset ID is created or reused.
5. A first upload starts as `draft`; a replacement upload starts as
   `needs-review` and receives `parent_asset_id` plus the next
   `version_number`.
6. A `narrator_assets` ownership row is created.
7. A `processing_jobs` transcription row is queued.
8. The editor sees the asset in `/api/queue?queue=narrator-submissions`.
9. The editor can reject it through `POST /api/narrator/review`.
10. Publishing uses `POST /api/content/publish`.
11. Publishing requires at least one approved transcript and one approved
    teaser for the same asset.
12. Publishing sets `audio_assets.status` to `published`, records
    `narrator_assets.published_at`, and inserts one row into
    `narrator_credits` using `INSERT OR IGNORE`.
13. The narrator workspace exposes `/api/narrator/assets` and native audio
    previews. A replacement form sends `parentAssetId`; the server creates a
    new version and leaves the current published parent untouched.
14. In the editor narrator-submission detail modal, `POST
    /api/narrator/process` can start `transcription` or `teaser` processing.
    Transcription uses `scripts/transcribe_sarvam.py` for the selected asset;
    teaser generation requires an approved transcript and uses
    `scripts/ollama_teaser.py`. Processing jobs are shown in the detail
    response and failed child processes are recorded as failed jobs.
15. The same detail modal displays transcription and teaser job states
    (`queued`, `running`, `needs-review`, `completed`, or `failed`) and polls
    every three seconds while a job is active. It refreshes the modal and
    editor queues when processing reaches a terminal state.
16. Rights are stored in `asset_rights`. Editors can configure the rights
    checklist from the narrator asset detail modal. Publishing requires an
    approved checklist, all five rights categories, and a non-expired license
    end date when one is provided.
    The listener catalog uses the published status and latest approved teaser
    as its visibility contract, so assets published before the rights gate was
    introduced remain discoverable instead of being silently hidden.
17. Editors can edit transcript and teaser text in the asset detail modal via
    `POST /api/narrator/content-edit`. Edits reset the item to `needs-review`;
    transcript edits also reset approved teasers for that asset so stale teaser
    copy cannot remain publishable.
18. Narrators provide structured metadata with every upload: title, multi-select
    genres, album, collection, episode number, language, audience/age range,
    mood, listening contexts, content warnings, moral/takeaway, source or
    adaptation, and search keywords. The editor asset detail view displays this
    metadata and publishing blocks missing title, genre, language, audience/age
    range, takeaway, or source/adaptation metadata. Existing databases migrate
    these fields automatically.
19. Metadata has its own review state: `not-reviewed`, `needs-changes`, or
    `approved`. Editors can correct metadata and approve/request changes from
    the narrator submission detail view. Publication requires approved metadata.
    Listener genre filters are generated from the published catalog rather than
    being limited to a hard-coded list.

The credit ledger is intentionally idempotent: one credit is awarded per
approved audio asset/version, not per upload attempt. When a replacement is
published, its parent version is moved to `archived`; the replacement becomes
the published version and receives its own credit. Until approval, the prior
published version remains untouched and playable.

## Important implementation files

- `scripts/editor_server.py`: HTTP server, sessions, RBAC, APIs, SQLite
  migrations, narrator upload and publication rules.
- `scripts/init_local_store.py`: initial catalog schema and idempotent catalog
  import into SQLite.
- `scripts/create_demo_users.py`: local role fixtures.
- `editor/index.html`, `editor/editor.js`, `editor/editor.css`: editor queues
  and review controls.
- `narrator/index.html`, `narrator/narrator.js`, `narrator/narrator.css`:
  narrator upload, pipeline summary, credits, and published history.
- `catalog/kadachepta.db`: local system of record; do not commit generated
  database files.
- `audio/`: original and local uploaded audio; treat source files as
  sensitive and do not commit new private recordings.

## Data model and state rules

Core tables are `audio_assets`, `transcripts`, `teaser_drafts`,
`processing_jobs`, `editor_users`, and `editorial_events`.

Narrator-specific tables:

- `narrator_assets(audio_asset_id, narrator_username, submitted_at,
  published_at, review_required)`
- `narrator_credits(narrator_username, audio_asset_id, awarded_at, reason)`

Relevant asset states currently include `draft`, `needs-review`, `rejected`,
and `published`. Transcript and teaser states are separate and must be
approved before publication.

Do not overwrite raw Sarvam transcripts. Transcript revisions should create a
new version and invalidate dependent teaser drafts. Keep audit events for
editorial decisions.

## Verification commands

```powershell
python -m py_compile scripts/editor_server.py scripts/init_local_store.py scripts/create_demo_users.py
node --check app.js
node --check editor/editor.js
node --check narrator/narrator.js
```

Manual smoke checks:

1. Visit `/` without a cookie and confirm the shared login is shown.
2. Log in as `listener`; confirm the listener app loads.
3. Log in as `narrator`; confirm `/narrator/` and upload form load.
4. Log in as `editor`; confirm the narrator submissions tab loads.
5. Confirm direct `/editor/` and `/narrator/` access redirects unauthorized
   roles to `/`.

## Known limitations and next work

- Narrator upload currently records duration as zero; metadata extraction and
  audio validation must run before publication.
- The editor queue can reject or publish narrator submissions, but it does not
  yet provide a full asset detail page, audio preview, or rights checklist.
- Publish currently requires approved transcript and teaser rows, but metadata
  and rights validation still need to be added.
- Replacement uploads are now versioned through `/api/narrator/upload` with
  `parentAssetId`. The legacy `submit-edit` endpoint only records an audit
  request and does not mutate published content.
- SQLite/local files are temporary. The planned migration target is
  PostgreSQL for workflow data and S3-compatible storage for media/artifacts.
- Do not run full-catalog transcription or teaser generation until the review
  UI, cost controls, and provider retry behavior are hardened.
