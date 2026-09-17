# కథాచెప్టా MVP

Telugu-first listening experience for folklore, fantasy, epics, inspirational stories, and audiobooks.

## Run locally

```powershell
npm start
```

Open <http://localhost:4173>.

## Current MVP slice

- Telugu-first responsive discovery page
- Curated story catalog with age/mood-oriented categories
- Search and category filtering
- Continue listening entry point
- Persistent saved-story library using `localStorage`
- Story queue controls and previous/next navigation
- Audio player with progress seeking and background-friendly layout
- Sleep timer entry point
- Telugu/English captions entry point for the next catalog phase
- Parent/family profile visual foundation

Audio is intentionally represented as catalog metadata until licensed files are added. To enable a title, add a file under `audio/` and set its `audio` field in `app.js`.

## Milestone A: catalog ingestion

The local audio collection can be converted into a reviewable catalog draft:

```powershell
npm run catalog:ingest
```

This creates `catalog/catalog-draft.json` and `catalog/import-report.json`.
The importer reads embedded tags and media facts without changing the original
files. It does not transcribe or publish audio until a Telugu speech-to-text
provider and teaser-generation provider are configured.

Copy [pipeline-config.example.json](./pipeline-config.example.json) to a
private runtime configuration and set provider credentials through environment
variables. Do not commit credentials. The importer deliberately leaves every
record in `draft` status and marks transcription as `not-configured` until
those adapters are implemented and approved.

Local secrets belong in `config/secrets.local.json`, which is ignored by Git;
use `config/secrets.example.json` as the template. The Sarvam key previously
shared in chat should be revoked and rotated before use.

## Local-first persistence and Ollama

For the current development phase, initialize the local SQLite store:

```powershell
npm run store:init
```

The database is written to `catalog/kadachepta.db`. Keep source audio in
`audio/` and generated artifacts under `catalog/`. The local teaser adapter
uses Ollama and requires a reviewed transcript:

```powershell
python scripts/ollama_teaser.py `
  --transcript catalog/transcripts/example.te.txt `
  --title "Example story" `
  --output catalog/teasers/example.json
```

The installed `llama3.1:8b` model is the first local teaser-generation
candidate. The Qwen coder models are not recommended for Telugu editorial
generation. Local Ollama drafts always start as `needs-review`.

## Local editorial workspace

Start the unified application server:

```powershell
npm start
```

Open the listener at <http://127.0.0.1:4173/> and the protected editorial
workspace at <http://127.0.0.1:4173/editor/>.

For local role testing, create the demo accounts once:

```powershell
npm run users:demo
```

The demo accounts all use `change-me` as the password:

| Username | Role |
| --- | --- |
| `listener` | Listener |
| `parent` | Parent |
| `editor` | Editor |
| `admin` | Admin |
| `narrator` | Narrator |

Narrators use `/narrator/` to submit audio, monitor their processing pipeline,
and review published recordings. Uploads start as drafts and queue
transcription. Only an editor or admin can publish an asset; publication
awards one immutable credit to its narrator. A submitted edit to a published
asset returns it to review and does not award a second credit.
The development login is `editor` / `change-me` unless
`KADACHEPTA_EDITOR_PASSWORD` was set before the database was initialized.
Both routes now use the same server, session, SQLite store, and RBAC API. The
workspace provides dashboard counts, transcript and teaser queues, audited
approve/reject actions, and local session cookies.

## Sarvam transcription benchmark

Install the SDK once:

```powershell
python -m pip install sarvamai
```

Run a bounded three-file benchmark:

```powershell
npm run transcribe:benchmark
```

The batch uses Saaras v4, stores raw timestamped results under
`catalog/transcripts/`, and records reviewed-pending transcript versions in
SQLite. Increase the limit only after checking accuracy and cost.

After reviewing a generated teaser, approve it explicitly:

```powershell
npm run teaser:review -- --asset-id 0145188debb92d27 `
  --decision approved `
  --reviewer local-editor `
  --notes "Teaser reviewed."
```

## Implementation roadmap

The detailed prioritized backlog, including the audio metadata, Telugu transcription, teaser-generation, editorial review, rights, and launch work, is maintained in [BACKLOG.md](./BACKLOG.md).
Recommended model and persistence choices are documented in [ARCHITECTURE.md](./ARCHITECTURE.md).
The implementation handoff, role contracts, state rules, verification commands,
and known limitations are documented in [HANDOFF.md](./HANDOFF.md).

### Phase 0 — Product foundation

1. Confirm brand, audience, content rights, and initial catalog.
2. Create the content model: story, book, chapter, narrator, transcript, translation, collection, and license.
3. Define safety, age-rating, moderation, and rights-review rules.

### Phase 1 — MVP listening loop

1. Replace the static catalog with a backend content API.
2. Add authentication and family profiles with parent PIN controls.
3. Upload and stream licensed audio with chapters, resume position, quality selection, and offline downloads.
4. Add playlists, favorites, listening history, and continue-listening synchronization.
5. Add reviewed Telugu transcripts and English translations for a launch collection.
6. Add bedtime mode, sleep timer, autoplay settings, and low-bandwidth support.

### Phase 2 — Catalog and trust

1. Build an editorial/content-management dashboard.
2. Add narrator profiles, curated collections, ratings, and safe parent reviews.
3. Add analytics for completion, retention, search gaps, and family usage.
4. Add license tracking, territory availability, takedown workflows, and revenue-share records.

### Phase 3 — Differentiation

1. Telugu learning mode with synchronized word highlighting.
2. Festival, diaspora, school, and family collections.
3. Shared listening sessions and private family sharing.
4. Search by theme and natural language.
5. Carefully reviewed AI assistance for transcripts, translation drafts, and catalog search.

## Non-negotiables before public launch

- Secure rights for every story, adaptation, recording, translation, illustration, music track, and sound effect.
- Human review for Telugu transcripts, English translations, names, poetry, and Sanskrit verses.
- Child-safe defaults: no open messaging, no unrestricted comments, parent controls, and minimal notifications.
- Accessible player controls, readable Telugu UI, screen-reader labels, and offline support.
