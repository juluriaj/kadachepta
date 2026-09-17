# KathaChepta AI and Persistence Decisions

## Current local-first baseline

During development, keep all persistent data on the local PC:

- `catalog/kadachepta.db`: SQLite catalog, workflow state, transcripts, teaser drafts, and audit records.
- `audio/`: original source files, treated as read-only inputs.
- `catalog/transcripts/`: raw and normalized transcript artifacts.
- `catalog/teasers/`: generated teaser drafts.
- `catalog/previews/`: optional audio excerpts.
- `catalog/import-report.json`: import diagnostics.

SQLite is the right temporary system of record for this single-PC phase. The
schema is intentionally designed so it can later be migrated to PostgreSQL.
Keep large audio and transcript artifacts as files, with checksums and paths in
SQLite. Do not commit generated database files, transcripts, or teaser drafts.

Ollama is the local generation adapter. The installed models should be
benchmarked rather than assumed to be Telugu specialists:

- `llama3.1:8b`: first practical teaser-generation baseline.
- `qwen3-coder:30b` and the Qwen coder models: not recommended as the primary
  Telugu editorial model; use them for code/tooling tasks instead.

The local teaser script is `scripts/ollama_teaser.py`. It requires an explicit
transcript and writes drafts as `needs-review`.

## Cloud migration boundary

At the final phase, migrate SQLite to PostgreSQL and local artifacts to an
S3-compatible object store. Preserve IDs, checksums, version numbers, and
review/audit history during migration.

## Earlier production-oriented options

### Telugu speech-to-text

Use a provider adapter with this future production order:

1. **Managed Telugu batch transcription:** Sarvam AI Saaras, if its current plan and data-processing terms meet the project's requirements.
2. **Managed fallback:** Google Cloud Speech-to-Text or Azure AI Speech with Telugu (`te-IN`) support.
3. **Self-hosted fallback:** `faster-whisper` with a multilingual large model, benchmarked on a representative Telugu sample before committing to production quality.

The application must not depend directly on one vendor. The adapter interface should accept an audio asset and return:

- language
- normalized transcript
- timestamped segments
- confidence, if supplied
- speaker labels, if supplied
- provider/model/version
- duration and cost
- request ID

The first implementation should run batch jobs, not synchronous web requests. Long audiobook chapters need resumable jobs, bounded retries, and clear permanent-failure states.

### Teaser and metadata generation

Use a structured-output capable multilingual LLM:

1. **Default:** a current small/fast model such as OpenAI GPT-4.1-mini or Google Gemini 2.5 Flash, selected after a Telugu quality benchmark.
2. **Higher-quality review/regeneration path:** a larger current model such as OpenAI GPT-4.1 or Google Gemini 2.5 Pro.
3. **Self-hosted option:** Qwen multilingual instruct models only after evaluating Telugu fluency, factuality, JSON reliability, and operating cost on the project's sample set.

The generation input should be the reviewed Telugu transcript plus trusted metadata. The model must return schema-validated JSON containing Telugu and English teasers, short descriptions, themes, mood, age suggestion, content warnings, confidence, and source transcript segments.

Do not allow generated text to publish automatically. Every draft needs a `needs-review` state and an editor approval event.

### English translation

Use the same multilingual LLM for the first draft, then compare it against:

- **Self-hosted:** AI4Bharat IndicTrans2
- **Managed:** Google Cloud Translation or Azure Translator with Telugu-English support

The source transcript version must be recorded. A transcript revision invalidates dependent translation and teaser drafts.

## Persistent storage

Use a split storage model:

### PostgreSQL

Use PostgreSQL as the system of record for:

- story, book, chapter, narrator, collection, and license metadata
- audio asset references and checksums
- transcript and teaser status
- version relationships
- reviewer decisions and audit events
- searchable short text
- job state, retries, provider request IDs, and costs

Use relational columns for fields used in filtering and reporting. Use JSONB for provider-specific response details and flexible segment payloads.

Recommended transcript shape:

```json
{
  "language": "te",
  "text": "...",
  "segments": [
    {
      "startMs": 0,
      "endMs": 4200,
      "text": "...",
      "confidence": 0.91
    }
  ],
  "provider": "sarvam",
  "model": "provider-model-version",
  "sourceAudioChecksum": "sha256",
  "status": "needs-review"
}
```

Recommended teaser draft fields:

- story/chapter ID
- source transcript version ID
- language
- short text
- long text
- themes
- mood
- age suggestion
- content warnings
- source segment IDs
- model/provider/prompt version
- generation timestamp
- review status
- reviewer and review timestamp
- rejection/regeneration reason

### Object storage

Use S3-compatible object storage such as Amazon S3, Cloudflare R2, Azure Blob Storage, or Google Cloud Storage for:

- original audio
- normalized/streaming audio renditions
- audio previews
- cover art
- raw provider transcripts
- exported subtitle files
- large transcript JSON files

Keep immutable objects addressed by checksum or versioned asset ID. Store only references, checksums, MIME types, sizes, and lifecycle status in PostgreSQL.

### Search

Start with PostgreSQL full-text search and trigram indexes. Add OpenSearch or Meilisearch only when catalog scale or typo-tolerant Telugu search requires it.

Add `pgvector` later for semantic discovery such as “calm stories about courage”; it is not required for the first catalog ingestion milestone.

## Recommended initial deployment

- PostgreSQL for application data and workflow state
- S3-compatible object storage for media and raw/large artifacts
- Redis or a PostgreSQL-backed queue for job dispatch, depending on operational simplicity
- A worker process for metadata, transcription, translation, and teaser jobs
- A provider adapter layer with secrets supplied through environment variables
- An admin review surface before anything is published

For the current 588-file, approximately 84-hour catalog, PostgreSQL plus object storage is more than sufficient. Do not introduce a document database or vector database before the product demonstrates a need.

## Evaluation benchmark before locking providers

Select 10–20 licensed representative files:

- short bedtime story
- long chapter
- mythology/proper names
- poetry or Sanskrit verses
- background music
- different narrators
- fast and slow speech
- incomplete metadata

Score each candidate on:

- Telugu word error rate
- proper-name accuracy
- timestamp alignment
- punctuation quality
- transcript correction effort
- teaser factuality
- spoiler rate
- Telugu naturalness
- English translation quality
- per-hour processing cost
- latency and failure/retry behavior

Choose providers from measured results, not model reputation alone.

## Decision summary

For the first production-oriented implementation, use:

```text
Audio files       -> S3-compatible object storage
Catalog/workflow  -> PostgreSQL
Job execution     -> Worker + queue
Telugu STT        -> Sarvam Saaras adapter, managed fallback
Teaser drafts     -> GPT-4.1-mini or Gemini 2.5 Flash adapter
Translation       -> Same LLM initially; benchmark IndicTrans2 later
Review             -> Human approval required
Search             -> PostgreSQL first
Embeddings         -> pgvector later
```

Model names and provider endpoints must remain configuration, not hard-coded application behavior, because availability, pricing, and quality change.
