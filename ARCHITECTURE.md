# KathaChepta Platform Architecture

Target architecture for a store-published, multilingual listening platform
hosted on a single AWS Lightsail VM. The delivery plan is in
[BACKLOG.md](./BACKLOG.md).

Last reviewed: 2026-09-23.

## Shape of the system

```
 Listener + narrator app              Studio (editors, admins)
 Expo / React Native                  React + Vite web app
 iOS · Android · Web                  desktop web
          │                                   │
          └──────────── HTTPS ────────────────┘
                          │
        ┌─────────────────▼──────────────────────────┐
        │ Lightsail VM (Ubuntu, Docker Compose)      │
        │                                            │
        │  Caddy ── TLS, reverse proxy, rate limits  │
        │   │                                        │
        │  api ─── FastAPI (REST + OpenAPI)          │
        │   │                                        │
        │  worker ─ jobs: media, payments, payouts,  │
        │   │       notifications, reconciliation    │
        │  postgres 16 (+ pgvector, pg_trgm)         │
        │  [optional] LM Studio headless (CPU)       │
        └───────┬───────────────────────┬────────────┘
                │                       │  job leases over HTTPS
   Lightsail bucket + CDN          AI worker(s) — pull model
   audio renditions, artwork,      your GPU machine: LM Studio,
   uploads (signed URLs)           image model, faster-whisper
                                   (or the VM itself, slowly)

 External (only where local models or self-hosting are the wrong tool):
 Sarvam (speech-to-text) · Razorpay / Stripe / RevenueCat (billing)
 Amazon SES (email) · Expo push → APNs / FCM · error tracking
```

## Key decisions and why

### Clients

- **Expo (React Native + TypeScript)** for the listener and narrator
  experience on iOS, Android, and web from one codebase. It covers background
  audio, lock-screen controls, offline storage, in-app purchases, push, and
  store builds (EAS), and it can do CarPlay/Android Auto through native
  modules. Flutter would also work; Expo wins on sharing TypeScript types with
  the studio and on its web target.
- **Studio** is a separate React + Vite web app. Editor and admin work is
  desktop, table-heavy, and keyboard-driven; forcing it into React Native web
  would slow editors down.
- Both clients use a typed client generated from the API's OpenAPI spec.
- The current vanilla JS pages are retired after Phase 1 reaches parity.

### API and data

- **FastAPI** keeps the team in Python, where the audio, AI, and pipeline code
  already lives. Pydantic gives request validation and the OpenAPI spec.
- **PostgreSQL 16** on the same VM as the system of record. Extensions:
  `pg_trgm` (fuzzy search), `unaccent`, `pgvector` (recommendations).
  Money is stored as integer minor units with a currency code.
- **Job queue on PostgreSQL** (`SELECT … FOR UPDATE SKIP LOCKED` with leases,
  retries, backoff, dead-letter). No Redis until measurements justify it.
- **Pull-based AI workers:** workers authenticate with a worker token, lease
  jobs over HTTPS, and upload results. A GPU machine at home or in the office
  can serve production without inbound ports or a VPN, and more workers can be
  added without changing the server.

### Media

- Uploads land in the bucket through pre-signed URLs (chunked and resumable).
  The API never streams large files through Python.
- The worker normalizes loudness (EBU R128, −16 LUFS integrated, −1.5 dBTP),
  converts to mono AAC-LC 64 kbps (standard) and HE-AAC 32 kbps (data saver),
  and extracts duration, a waveform, chapter markers, and QC metrics.
- Playback uses CDN URLs signed per entitlement with a short expiry, which
  supports HTTP Range seeking. Offline downloads are encrypted in the app
  sandbox and expire with the entitlement.
- Originals are kept in a private bucket prefix; renditions are addressed by
  asset ID + version + checksum.

### Identity and access

- Listeners: email one-time code, Sign in with Apple, Sign in with Google.
  Phone OTP (important in India) is added when SMS cost is acceptable.
- Staff (editors, admins, finance): password + TOTP, enforced.
- Web uses httpOnly session cookies with CSRF protection; mobile uses a
  15-minute access token plus a rotating refresh token in secure storage.
- **Households:** one billing parent, up to N profiles, child profiles without
  credentials, a parental PIN gate for settings, purchases, and external links.
- Role- and permission-based authorization is enforced in the API only.

### AI: local first

All model names, endpoints, and prompt versions are configuration. Every AI
output is stored with provider, model, prompt version, input version, and
review status.

| Task | Default (local) | Internet fallback / reason | Candidates to benchmark |
|---|---|---|---|
| Speech-to-text | — | **Sarvam** (Saarika/Saaras): local Telugu STT quality is not good enough yet | faster-whisper large-v3, AI4Bharat IndicConformer |
| Metadata, teaser, moral, age band, safety descriptors (structured JSON) | LM Studio, OpenAI-compatible, JSON schema output | none planned | Sarvam-M (24B, Indic-tuned), Gemma 3 12B/27B, Qwen3 14B/30B-A3B |
| Translation (teasers, metadata) | LM Studio | none planned | Sarvam-Translate, IndicTrans2, the metadata model |
| Review moderation | LM Studio classifier + word lists | none planned | Llama Guard 3, Gemma 3 |
| Embeddings (search, recommendations) | LM Studio embeddings endpoint | none planned | bge-m3, multilingual-e5-large |
| Cover artwork | Local diffusion on the GPU worker (ComfyUI or diffusers) | paid FLUX API only if no GPU is available | FLUX.1-schnell (Apache 2.0), SDXL |
| Transliteration for search | Rule-based libraries | none | indic-transliteration, Aksharamukha |

Benchmark before locking in: 20 licensed sample stories per language, scored for
factual accuracy, spoilers, fluency, JSON validity, and time per story. Model
choice is per language. The harness is `worker/bench/llm_benchmark.py`; results
are kept in `docs/benchmarks/`.

**Current hardware (desktop GPU worker): RTX 5060, 8 GB.** That fits roughly
8–12B models in 4-bit form. Telugu text costs about 1.4 tokens per character, so
the teaser prompt sends the opening and ending of long transcripts (never the
middle) to stay within LM Studio's default 8k context. Larger Indic-tuned models
(Sarvam-M 24B) need a bigger GPU or a cloud GPU worker.

**Hosting reality check:** Lightsail has no GPU instances. An 8B-class model on
a 4-vCPU CPU instance produces a few tokens per second, which is acceptable
for batch drafting (a minute or two per story) but not for image generation or
larger models. That is why AI runs as pull-based jobs: a GPU machine does the
heavy work, and the VM can process a slow backlog on its own if the GPU worker
is offline.

### Payments

- The server owns **entitlements**; payment providers only report events.
- `PaymentProvider` interface with implementations for Razorpay (INR
  subscriptions with UPI Autopay and e-mandates), Stripe (international), and
  RevenueCat (App Store and Google Play subscriptions).
- All money movements are written to an append-only double-entry ledger:
  customer charges, refunds, provider fees, taxes, narrator accruals,
  adjustments, holds, clawbacks, and payouts.
- Webhooks are verified, idempotent, stored raw, and replayable. A nightly job
  reconciles the ledger against provider reports.
- **App store rules:** digital subscriptions sold inside iOS/Android apps
  generally must use store billing (15–30% fee). "Reader" apps (audio content)
  may instead let users sign up outside the app in some regions, and payment
  rules differ by country (for example external links in the US storefront,
  alternative billing in India on Google Play). Recommendation: launch with
  store billing via RevenueCat and revisit per region after launch. Re-check
  the current store guidelines at Phase 4.
- Narrator payouts: RazorpayX Payouts (India) and Stripe Connect
  (international), with KYC, monthly close, and admin approval.

### Multilingual design

- BCP 47 language tags on stories, chapters, audio, transcripts, teasers,
  metadata, prompts, narrators, editors, profiles, and search documents.
- Localized text lives in `*_localizations` tables keyed by
  `(entity_id, language)`, each with its own review status and source version.
- The AI router picks the STT provider, LLM model, prompt template, and safety
  lists by language.
- PostgreSQL full-text configuration is chosen by language, plus trigram
  search and transliterated search keys.
- The UI uses ICU messages, locale-aware formatting, Noto font stacks for each
  script, and logical CSS properties so right-to-left scripts work later.

## Data model (v1 outline)

```
users, identities (email/apple/google), sessions, refresh_tokens, staff_mfa
households, profiles (adult|child, age_band, languages[]), parental_pins
narrators (user_id, languages[], trust_level, kyc_status), narrator_agreements
works (source text: title, origin, public_domain|original|licensed)
stories / series / chapters (language, age_band, duration, status, version)
audio_assets (checksum, original_key, rendition keys, qc_metrics, version)
story_localizations (story_id, language, title, teaser_short/long, moral, review_status)
transcripts (asset_version, language, segments jsonb, provider, confidence, status)
ai_outputs (task, input_version, provider, model, prompt_version, output jsonb, status)
rights_records, rights_evidence, takedowns
reviews_editorial (entity, decision, reasons, reviewer, at)
ratings (profile_id, story_id, story_score, narration_score, listen_ratio, weight)
reviews_text, reports, moderation_actions
listening_sessions, listening_progress, listening_daily, favorites, downloads
collections, shelves (moment: bedtime|drive|run|work|learn, language)
plans, prices (region, currency), subscriptions, entitlements, purchases
payment_events (raw webhooks), ledger_entries (double-entry), invoices
earnings_statements, payouts, payout_accounts
jobs (type, payload, status, lease_until, attempts, idempotency_key), workers
audit_log, notifications, devices (push tokens)
```

## Deployment on Lightsail

| Environment | Size (starting point) | Notes |
|---|---|---|
| Staging | 4 GB / 2 vCPU | Phases 0–5; sandbox payment keys |
| Production (no on-VM LLM) | 8 GB / 2 vCPU | GPU worker handles AI |
| Production (with CPU LLM fallback) | 16 GB / 4 vCPU | Slow backlog processing when the GPU worker is offline |

- Docker Compose services: `caddy`, `api` (Uvicorn workers), `worker`,
  `postgres`, optional `lmstudio`.
- Lightsail bucket (private) + Lightsail CDN distribution for media delivery.
- Backups: Lightsail automatic snapshots (daily), nightly `pg_dump` to the
  bucket, WAL archiving for point-in-time recovery before launch (Phase 6).
  Target: lose at most 15 minutes of data; restore within 2 hours.
- CI/CD: GitHub Actions builds images and deploys over SSH with a health-check
  gate. Mobile builds and store submissions go through EAS; small JavaScript
  fixes ship as OTA updates.
- The single VM is a single point of failure. That is acceptable for launch
  with a practiced restore drill. The move out is to managed PostgreSQL
  (Lightsail managed database) first, then a second app VM behind a Lightsail
  load balancer.

## Observability and privacy

- Structured JSON logs with request IDs; `/api/health`; uptime checks; error
  tracking with PII scrubbing.
- First-party product analytics stored in PostgreSQL (events table), not
  third-party SDKs; no behavioural tracking or advertising identifiers for
  child profiles.
- Data retention rules per table; account deletion cascades within 30 days;
  export on request.
