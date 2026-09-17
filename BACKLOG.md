# KathaChepta Product Backlog

This backlog is the working source of truth for turning the current static prototype into a production-ready Telugu-first audio platform.

## Product north star

KathaChepta is a safe, Telugu-first listening home for folklore, fantasy, mythology, inspirational stories, and audiobooks. It should help children and families spend less time on screens through high-quality human narration, reliable playback, and culturally authentic discovery.

## Delivery principles

- Secure rights before publishing, transcribing, translating, previewing, or monetizing content.
- Preserve human narration as the core product differentiator.
- Prefer calm, intentional discovery over addictive short-form mechanics.
- Make child safety, accessibility, and low-bandwidth use first-class requirements.
- Treat generated metadata as a draft until a reviewer approves it.
- Never invent plot details, reveal endings, or misrepresent source material.

## Status legend

- `Now`: required for the first usable product
- `Next`: required for public launch quality
- `Later`: differentiating or scale feature
- `Blocked`: requires a product, legal, or vendor decision

## Epic 1 — Content and rights foundation

### Narrator role and credit workflow

Narrators own their submitted audio pipeline and can view previously published
recordings. Their submitted edits to published audio return the asset to
`needs-review`; the prior publication is not treated as approved content until
the new version passes editorial review. An editor/admin publish action awards
exactly one credit per approved audio asset through the `narrator_credits`
ledger. Credits are immutable publication events, not upload attempts.

**Local MVP implementation:** narrator accounts, `/narrator/`, multipart audio
uploads into the local audio store, queued transcription jobs, ownership
records, published-history data, and an idempotent credit ledger are in place.
The next editorial slice is to expose publish and edit-review actions in the
workspace UI and add narrator profile/payment reporting.

### BKL-001 — Define the canonical content model

**Status:** Now  
**Priority:** P0

Create schemas for:

- `Story`: title, alternate titles, synopsis, teaser, language, age range, genres, themes, mood, duration, cover art, source, status.
- `Book`: title, author/source, series, chapters, edition, language, cover art.
- `Chapter`: sequence, title, duration, audio asset, transcript, preview asset.
- `Narrator`: name, biography, portrait, language, pronunciation notes, rights status.
- `Collection`: editorial playlist, genre, festival, age, mood, or use case.
- `AudioAsset`: original file, normalized file, bitrate, duration, waveform, checksum, storage location.
- `Transcript`: language, text, timestamp segments, word timing status, model/version, review status.
- `Translation`: source transcript version, target language, text, review status.
- `Teaser`: short and long variants per language, generation source, prompt version, review status.
- `License`: rights holder, territory, start/end date, allowed uses, download/preview/streaming rights, takedown status.

**Acceptance criteria**

- Every published story can be traced to its audio, transcript, teaser, narrator, and license.
- Draft, review, approved, rejected, scheduled, published, and archived states are explicit.
- Required fields differ correctly for stories, books, chapters, and collections.

### BKL-002 — Build rights and provenance register

**Status:** Now  
**Priority:** P0

- Record rights for original story, adaptation, translation, audio recording, narrator performance, artwork, music, and sound effects.
- Record territory, platform, subscription, advertising, download, excerpt, and derivative-content permissions.
- Add expiry reminders and automatic unpublish behavior for expired rights.
- Add takedown workflow and audit history.
- Require rights approval before public publishing.

### BKL-003 — Define editorial and child-safety policy

**Status:** Now  
**Priority:** P0

- Define age bands and content ratings.
- Define treatment of violence, death, fear, religious content, and mature themes.
- Define prohibited metadata, clickbait, and misleading teaser language.
- Define generated-content review requirements.
- Prohibit open messaging and unrestricted child-facing comments in the initial release.

## Epic 2 — Audio ingestion and catalog automation

### BKL-010 — Build metadata ingestion CLI

**Status:** Now  
**Priority:** P0

Scan an input directory and create catalog drafts from audio files.

Requirements:

- Support MP3, M4A, AAC, WAV, and common audiobook formats.
- Extract title, album/book, artist, narrator, composer, genre, track number, year, comments, artwork, language, and custom tags.
- Normalize Unicode and whitespace.
- Preserve original tags and file checksum.
- Detect duplicate files by checksum and normalized title/album/track.
- Generate a stable asset ID.
- Produce actionable validation errors rather than silently dropping fields.
- Write an import report with created, updated, skipped, duplicate, and failed counts.

**Acceptance criteria**

- A directory can be reprocessed idempotently.
- Metadata is stored separately from the original file.
- Missing or conflicting metadata is surfaced for review.

**Milestone A result:** Implemented in `scripts/ingest_catalog.py`; processed
588 MP3 files with zero parse errors and generated `catalog/catalog-draft.json`
plus `catalog/import-report.json`.

### BKL-011 — Normalize and validate audio

**Status:** Now  
**Priority:** P0

- Probe duration, sample rate, channels, codec, bitrate, loudness, and corruption.
- Normalize loudness for consistent playback.
- Generate streaming and download renditions.
- Preserve a high-quality source master.
- Generate waveform data for future player UI.
- Validate that normalized output remains synchronized and intelligible.

### BKL-012 — Create catalog review queue

**Status:** Now  
**Priority:** P0

Reviewers need to see:

- Original metadata and parsed metadata
- Audio preview
- Cover art
- Duplicate/conflict warnings
- Rights status
- Transcript status
- Teaser status
- Publish blockers

## Epic 3 — Telugu transcription pipeline

### BKL-020 — Select and abstract speech-to-text provider

**Status:** Now  
**Priority:** P0  
**Decision needed:** hosted Telugu provider versus self-hosted Whisper/faster-whisper

Provider adapter must support:

- Telugu transcription
- Long-form audio
- Timestamped segments
- Retryable jobs
- Cost and duration tracking
- Model/provider version tracking
- Provider failure and quota reporting

Start with a provider abstraction so catalog data does not depend on one vendor.

### BKL-021 — Transcribe audio asynchronously

**Status:** Now  
**Priority:** P0

Pipeline:

```text
uploaded → validated → queued → transcribing → transcript-draft → review
```

- Chunk long audio safely.
- Preserve chapter and segment boundaries.
- Reassemble transcript in original order.
- Store segment timestamps.
- Store confidence where available.
- Retry transient failures with bounded attempts.
- Move permanent failures to an explicit error state.

### BKL-022 — Telugu transcript cleanup and review

**Status:** Now  
**Priority:** P0

- Normalize punctuation and spacing without changing meaning.
- Preserve poetry, verses, names, and intentional pronunciation.
- Add glossary support for recurring mythological names and places.
- Allow side-by-side audio playback and transcript editing.
- Store reviewer, timestamp, and revision history.
- Never overwrite the raw provider transcript.

### BKL-023 — English translation workflow

**Status:** Next  
**Priority:** P1

- Generate an English draft from the reviewed Telugu transcript.
- Preserve names and cultural terms with configurable transliteration.
- Mark machine translation clearly.
- Provide reviewer editing and approval.
- Store source transcript version so translations can be invalidated when source text changes.

## Epic 4 — Audio-derived teaser generation

### BKL-030 — Define teaser formats

**Status:** Now  
**Priority:** P0

Generate and store:

- Telugu card teaser: 35–60 Telugu words.
- English card teaser: 35–60 English words.
- One-line short description for search/list cards.
- Longer detail-page synopsis.
- Non-spoiler themes and mood tags.
- Suggested age range for editorial approval.
- Optional content warnings.

### BKL-031 — Generate teaser only from trusted source material

**Status:** Now  
**Priority:** P0

Input precedence:

1. Reviewed Telugu transcript
2. Raw Telugu transcript, clearly marked as lower confidence
3. Rich audio metadata

Prompt constraints:

- Use only information in the supplied transcript and metadata.
- Do not invent names, events, morals, or settings.
- Do not reveal the ending or major twist.
- Do not make factual claims unsupported by the source.
- Use warm, family-safe, culturally respectful language.
- Avoid clickbait, fear amplification, and exaggerated promises.
- Return structured JSON, not free-form mixed output.

Expected response:

```json
{
  "teaserTe": "...",
  "teaserEn": "...",
  "shortTe": "...",
  "shortEn": "...",
  "themes": ["courage", "kindness"],
  "mood": ["calm", "inspiring"],
  "ageSuggestion": "8+",
  "contentWarnings": [],
  "confidence": 0.0,
  "sourceSegments": []
}
```

### BKL-032 — Add teaser generation job orchestration

**Status:** Now  
**Priority:** P0

States:

```text
not-started → queued → generating → generated → needs-review
→ approved → published
```

- Make jobs idempotent by audio checksum plus transcript version plus prompt version.
- Support batch generation and single-item regeneration.
- Record model, provider, prompt version, input transcript version, cost, and timestamps.
- Do not publish generated text automatically.
- Keep failed jobs visible with error details.

### BKL-033 — Build teaser review tools

**Status:** Now  
**Priority:** P0

Reviewer view must support:

- Play the relevant audio segment while reading the generated teaser.
- View source transcript excerpts used for each claim.
- Edit Telugu and English independently.
- Approve, reject, regenerate, or send back for transcript correction.
- Compare previous versions.
- Record reviewer and reason.

### BKL-034 — Generate optional audio previews

**Status:** Next  
**Priority:** P1

Start with safe excerpt extraction:

- Generate 20–45 second candidates.
- Avoid beginning/end spoilers where possible.
- Avoid silence, ads, credits, and chapter transitions.
- Let editors choose and trim the final excerpt.
- Store preview start/end and source asset version.

Later evaluate narrated promotional teasers using a licensed human or synthetic Telugu voice. Do not clone a narrator without explicit rights.

## Epic 5 — Listening MVP

### BKL-040 — Replace static catalog with API

**Status:** Now  
**Priority:** P0

- Add pagination, search, filters, category browsing, and featured collections.
- Return approved metadata and teasers only.
- Support availability by territory and rights window.
- Support catalog versioning and cache invalidation.

### BKL-041 — Implement authentication and profiles

**Status:** Now  
**Priority:** P0

- Email/phone/social sign-in decision.
- Adult account with multiple child profiles.
- Parent PIN for settings and content controls.
- Profile age band, language preference, and interests.
- Safe defaults for child accounts.

### BKL-042 — Implement reliable audio player

**Status:** Now  
**Priority:** P0

- Background playback.
- Lock-screen and car controls.
- Resume position across devices.
- Previous/next chapter.
- Playback speed.
- Sleep timer and fade-out.
- Volume normalization.
- Queue and autoplay preference.
- Network failure recovery.
- Playback analytics without collecting unnecessary child data.

### BKL-043 — Implement library and playlists

**Status:** Now  
**Priority:** P0

- Favorites.
- Continue listening.
- Listening history.
- User-created playlists.
- Curated editorial collections.
- Download individual chapters or whole books.
- Offline state and storage management.

### BKL-044 — Implement Telugu/English captions

**Status:** Next  
**Priority:** P1

- Timestamped Telugu captions.
- Reviewed English translation captions.
- Side-by-side and single-language modes.
- Synchronized segment highlighting.
- Font size, contrast, and reduced-motion settings.
- Search within transcript.
- Clearly identify unreviewed text.

## Epic 6 — Discovery and family experience

### BKL-050 — Build catalog discovery

**Status:** Now  
**Priority:** P0

Filters and sections:

- Age
- Genre
- Source/epic
- Narrator
- Duration
- Mood
- Festival/occasion
- Language
- New, popular, and editor-curated

### BKL-051 — Add bedtime mode

**Status:** Now  
**Priority:** P0

- Low-light UI.
- One-tap bedtime queue.
- Sleep timer.
- Optional autoplay to next chapter.
- Gentle completion behavior.
- Hide unnecessary controls after inactivity.

### BKL-052 — Add family controls and dashboard

**Status:** Next  
**Priority:** P1

- Content rating filters.
- Explicit-content exclusion.
- Disable autoplay.
- Wi-Fi-only downloads.
- Listening history summaries.
- Parent-managed recommendations.
- Avoid ranking children publicly or encouraging unhealthy streak behavior.

### BKL-053 — Add narrator and cultural context pages

**Status:** Next  
**Priority:** P1

- Narrator profile and catalog.
- Author/source information.
- Adaptation and translation credits.
- Cultural notes for diaspora listeners.
- Festival and school collections.

## Epic 7 — Operations, analytics, and monetization

### BKL-060 — Build editorial/admin dashboard

**Status:** Next  
**Priority:** P1

- Content import and validation.
- Transcript review.
- Translation review.
- Teaser review.
- Rights management.
- Publish scheduling.
- Bulk actions with audit log.

**Initial local implementation:** `scripts/editor_server.py` and `editor/`
provide editor login, dashboard counts, transcript/teaser queues, and audited
approve/reject actions against the SQLite store. Transcript editing, timestamp
audio review, metadata editing, rights checklists, and publish validation remain
next slices.

### BKL-061 — Add privacy-conscious analytics

**Status:** Next  
**Priority:** P1

Measure:

- Catalog search terms and zero-result searches.
- Story starts, completion, abandonment, and resume.
- Teaser impressions and play conversion.
- Playlist creation.
- Download success/failure.
- Transcript/caption usage.
- Family retention.

Avoid collecting precise child behavioral profiles unless necessary and lawfully consented.

### BKL-062 — Define pricing and subscriptions

**Status:** Blocked  
**Priority:** P1

Evaluate:

- Free curated catalog.
- Individual premium plan.
- Family plan with multiple profiles.
- Individual audiobook purchases.
- School/library/institution plans.

Avoid aggressive advertising in child-facing experiences.

### BKL-063 — Add rights-aware monetization

**Status:** Later  
**Priority:** P2

- Revenue-share ledger for rights holders and narrators.
- Territory-aware pricing.
- Download and preview entitlement checks.
- Subscription access audit.

## Epic 8 — Platform quality and scale

### BKL-070 — Accessibility

**Status:** Next  
**Priority:** P1

- Screen-reader labels.
- Keyboard navigation.
- High contrast.
- Large text.
- Reduced motion.
- Captions/transcripts.
- Clear focus states.
- Simple controls for older users.

### BKL-071 — Low-bandwidth and offline reliability

**Status:** Next  
**Priority:** P1

- Audio quality selection.
- Wi-Fi-only setting.
- Resumable downloads.
- Storage quota and cleanup.
- Offline playback without repeated authentication.
- Sync progress when connection returns.

### BKL-072 — Security and privacy

**Status:** Now  
**Priority:** P0

- Secure signed media URLs.
- Authorization on every profile and download action.
- Encrypt sensitive data at rest and in transit.
- Parent-protected child settings.
- Minimize child data collection.
- Account deletion and data export.
- Audit admin actions.

### BKL-073 — Testing and release gates

**Status:** Now  
**Priority:** P0

- Unit tests for metadata parsing and normalization.
- Golden-file tests for teaser JSON validation.
- Pipeline retry and idempotency tests.
- Transcript/teaser approval state tests.
- Player tests for resume, seeking, and offline transitions.
- Accessibility smoke tests.
- Browser/mobile responsive smoke tests.
- Load tests for catalog search and audio authorization.

## Suggested implementation order

### Local development storage decision

For the current phase, use SQLite and local folders:

- `catalog/kadachepta.db` for structured records and workflow state.
- `catalog/transcripts/` for transcript files.
- `catalog/teasers/` for generated drafts.
- `catalog/previews/` for optional audio previews.
- `audio/` as read-only source input.

Use Ollama locally for teaser generation, beginning with `llama3.1:8b`.
Transcription remains a separate provider/model decision because Ollama is
not itself a speech-to-text runtime. The final phase migrates the same schema
and versioned artifacts to PostgreSQL plus S3-compatible storage.

### Milestone A — Catalog proof of concept

Deliver BKL-001, BKL-002, BKL-010, BKL-011, BKL-020, BKL-030, and BKL-032 using a local batch processor and a small licensed sample.

**Exit criteria:** ten audio files become reviewed catalog drafts with extracted metadata, Telugu transcripts, and generated teaser drafts.

### Milestone B — Editorial quality loop

Deliver BKL-022, BKL-023, BKL-033, BKL-034, and BKL-060.

**Exit criteria:** an editor can review audio, transcript, source evidence, teaser, translation, and rights status, then publish approved content.

### Milestone C — Real listening MVP

Deliver BKL-040 through BKL-044, BKL-050, BKL-051, and BKL-070.

**Exit criteria:** a family can discover, play, resume, save, queue, caption, and download approved content.

### Milestone D — Public beta readiness

Deliver BKL-052, BKL-061, BKL-071, BKL-072, and BKL-073. Resolve BKL-062 before charging users.

**Exit criteria:** child-safe defaults, rights enforcement, privacy controls, reliable offline behavior, and observable quality metrics.

## Open decisions to resolve

1. Benchmark and select the first Telugu speech-to-text adapter; the recommended starting candidate is Sarvam Saaras, with Google/Azure managed fallbacks and faster-whisper as a self-hosted benchmark.
2. Benchmark and select a structured multilingual teaser model; start with GPT-4.1-mini or Gemini 2.5 Flash and reserve a larger model for difficult regeneration/review cases.
3. Use PostgreSQL as the catalog/workflow system of record and S3-compatible object storage for audio and large immutable artifacts.
4. Which authentication method should the MVP support?
5. What initial age bands and content-rating taxonomy should be used?
6. Which content and narrator licenses are already available?
7. Which subscription or purchase model is preferred?
8. What human review capacity is available per week?

## Initial sample dataset requirements

Before building the batch pipeline, collect 10–20 representative files:

- Short bedtime story
- Long audiobook chapter
- Ramayana or Mahabharata story
- Chandamama story
- Story with poetry or Sanskrit verses
- Story with background music
- Different narrators
- Different audio formats
- At least one file with incomplete metadata
- At least one file with rich custom tags and cover art

The sample must be licensed for processing and testing.
