# KathaChepta Platform Roadmap

This is the working source of truth for turning the local prototype into a
store-published, multilingual listening platform for families, listeners,
narrators, and editors. The target architecture is in
[ARCHITECTURE.md](./ARCHITECTURE.md).

Last reviewed: 2026-09-23.

## North star

A calm, screen-light home for human-narrated stories and audiobooks that spark
imagination. Families press play and put the phone down: in the car, on a run,
at bedtime, or at work. Narrators earn a fair living from quality work, and
listeners decide what quality means through ratings.

**Product metrics that matter**

- Weekly listening minutes per household, and the share of listening with the
  screen off (the screen-time reduction proof point).
- Stories finished per listener per week.
- Narrator time from upload to publish (target: under 24 hours, with under 5
  minutes of editor effort per story).
- Paid conversion and monthly churn.
- Narrator retention and average monthly earnings.

**Anti-goals:** infinite feeds, autoplay rabbit holes for children, ads,
third-party tracking in the children's experience, or AI-generated narration
presented as human work.

## Principles

1. **Screen-off first.** Every core action (resume, skip, sleep timer, next
   story) works from the lock screen, headphones, car, or voice. Visual
   screens are for choosing, not for staying.
2. **Families by default.** Child profiles, parental gates, and age-appropriate
   catalog filtering are the baseline for everyone, not a separate premium mode.
3. **Multilingual from day one.** Language is a first-class dimension of
   content, UI, search, AI routing, pricing, and narrator matching. Telugu is
   the launch language, not a hard-coded assumption.
4. **AI drafts, humans decide.** Local models do the drafting work (metadata,
   teasers, safety checks, translations, moderation). Nothing is published or
   paid out without a human approval event.
5. **Local models first.** LM Studio models through an OpenAI-compatible
   adapter for text and embeddings. Internet providers only where local models
   are clearly weaker: speech-to-text (Sarvam), payments, email, push, and
   store billing.
6. **Rights before reach.** No publishing, preview, translation, or payout
   without recorded rights and provenance.
7. **Every workflow is one screen.** If a narrator, editor, or listener needs
   more than one screen or more than a few taps to finish a common task, that
   is a bug.

## Personas and the jobs they hire us for

| Persona | Context | Job to be done | Friction to remove |
|---|---|---|---|
| Parent | Car, bedtime, chores | "Keep my kids engaged without a screen, and let me trust what they hear." | Choosing content, age suitability, managing the app from the driver's seat |
| Child (3–12) | Bedtime, car | "Play my favorite story again." | Reading, logins, accidental purchases |
| Adult listener | Run, commute, desk | "Pick up exactly where I left off, at my speed." | Finding the next good listen, losing position, data usage |
| Narrator | Home studio or phone | "Record, submit, get published, and get paid, without learning the tools." | Audio quality rejections, metadata forms, opaque review, payout uncertainty |
| Editor | Desk | "Make a confident publish decision in minutes." | Clicking through 5+ approval gates, manually triggering each AI step |
| Admin/finance | Desk | "Close the month: payouts, subscriptions, disputes." | Spreadsheets, reconciliation |

## Critique of the current prototype

What exists is a useful proof of the editorial pipeline, not a foundation for a
store-published app. Being honest about the gaps:

| # | Finding | Impact | Resolution |
|---|---|---|---|
| C1 | One 1,500-line standard-library HTTP server, no framework, no tests | Can't safely add payments, mobile auth, or concurrency | Phase 0 replatform (FastAPI + PostgreSQL + tests) |
| C2 | Sessions kept in memory, cookie-only | Restarts log everyone out; no mobile token auth | Persistent sessions + mobile refresh tokens |
| C3 | Audio served by reading the whole file into memory, with no HTTP Range support | Seeking breaks on iOS/Safari; long audiobooks exhaust RAM; no CDN | Object storage + CDN + signed URLs + Range |
| C4 | Background jobs are subprocess threads with no queue | Jobs are lost on restart; duplicate job rows; no retries | PostgreSQL-backed job queue with leases and retries |
| C5 | 5–6 manual editorial gates per story, each AI step triggered by hand | Editor effort does not scale; the narrator waits | Automatic pipeline on upload + one consolidated review screen |
| C6 | Narrators can only upload a file; no quality feedback | Bad audio is found late by editors | Automated audio QC with instant feedback; in-app recording |
| C7 | Listener UI has hard-coded placeholders (resume button, hero card, sleep timer, captions, queue are toasts) | Not shippable | Rebuilt listener app (Phase 1) |
| C8 | Web only, no background audio, lock-screen controls, offline, or CarPlay/Android Auto | Fails the drive/run/bedtime use cases | Native mobile app (Expo/React Native) |
| C9 | Artwork via Pollinations (third-party, unclear commercial terms), no artwork review gate | Licensing risk; contradicts local-first | Local image model (FLUX.1-schnell/SDXL) on the AI worker; review step |
| C10 | Docs reference Ollama; you run LM Studio | Two adapters to maintain | One OpenAI-compatible adapter; LM Studio is the default |
| C11 | Demo accounts use `change-me`; a Sarvam key was shared in chat; no rate limits or HTTPS | Security exposure | Rotate the key; staff 2FA; rate limits; TLS |
| C12 | No child profiles or parental gate | Core audience not served; store policy risk | Household + child profiles (Phase 1) |
| C13 | Telugu assumed in code paths, fonts, prompts, and search | Blocks new languages | Language dimension everywhere (see Epic L) |
| C14 | Name spelled `kadachepta` (repo/DB) and `KathaChepta` (UI) | Brand and store listing confusion | **Resolved:** brand is KathaChepta on `kathachepta.com`; `kadachepta.com` redirects to it; code and database identifiers are renamed in Phase 0 |

Critique of my own recent work: the favorites, listening stats, artwork, and
diagnostics features were built on the stack that Phase 0 replaces. Their data
model (`listener_favorites`, `listening_progress`, `listening_daily`,
`artwork_path`) carries over; the UI code will be rewritten.

## Phase plan

Each phase ends with something you can use and review end to end on the local
desktop environment (the hosting environment until the final phase) and (from Phase 1) on an installable Android build plus mobile web. Phases are
ordered by dependency and risk, not by feature appeal.

```
Phase 0  Foundation & replatform          → same features, new stack, running locally in Docker
Phase 1  Listener app (mobile + web)       → a family uses it daily on real phones
Phase 2  Narrator studio + auto pipeline   → narrator records on a phone; editor publishes in minutes
Phase 3  Ratings, discovery, community     → ratings drive quality signals and recommendations
Phase 4  Subscriptions & payments          → sandbox purchases on web, iOS, Android grant access
Phase 5  Narrator earnings & payouts       → a sandbox month-end close produces statements and payouts
Phase 6  Hardening & store launch          → apps approved in both stores; production live
```

Multilingual work (Epic L) runs through every phase rather than being a phase
of its own.

---

## Phase 0 — Foundation and replatform

**Status (2026-09-23): built, awaiting your review** — checklist in
[docs/phase-0-review.md](docs/phase-0-review.md). Deviations from the plan below:
`app/` and `studio/` are created in Phases 1 and 2 (the prototype pages are served meanwhile);
the Lightsail bucket storage backend (part of P0-06) moves to Phase 6 with hosting; the CI workflow
(P0-12) is written but runs only once the branch is pushed. Added beyond plan: job priorities, email
one-time-code sign-in, staff TOTP, and a local-LLM benchmark (`docs/benchmarks/`).

**Goal:** everything that works today keeps working, on a stack that can carry
payments and mobile clients, running on the local desktop with the same Docker
Compose setup that will later run on Lightsail.

**Exit criteria**

- Listener, narrator, and editor flows from the prototype work on the new API
  (feature-parity checklist signed off by you).
- Existing SQLite data (assets, transcripts, teasers, rights, users, favorites,
  listening history, artwork) is migrated to PostgreSQL with identical IDs, and
  a verification report shows matching counts and checksums.
- The full stack starts with one command on the desktop (`docker compose up`),
  is reachable from phones on the home network, and has nightly local backups.
- The Lightsail deployment scripts exist but are not run until AWS details are
  provided (Phase 6).
- Automated tests run in CI on every push.

| ID | Item | Notes |
|---|---|---|
| P0-01 | Monorepo layout: `api/`, `worker/`, `app/` (Expo), `studio/` (editor/admin web), `infra/`, `docs/` | Keep `scripts/` pipeline logic as worker tasks |
| P0-02 | FastAPI service, SQLAlchemy models, Alembic migrations, Pydantic schemas, OpenAPI spec | The OpenAPI spec generates the typed client for app and studio |
| P0-03 | PostgreSQL 16 schema v1 with a language dimension on content, users, and narrators | See the data model in ARCHITECTURE.md |
| P0-04 | SQLite → PostgreSQL migration script with a verification report | Idempotent; re-runnable |
| P0-05 | Auth v1: staff email + password + TOTP; listener email OTP; persistent sessions; mobile access/refresh tokens; roles and permissions ported | Sign in with Apple/Google in Phase 1 |
| P0-06 | Storage abstraction (local disk in development, Lightsail bucket in production), signed media URLs, HTTP Range streaming | Fixes C3 |
| P0-07 | Job queue on PostgreSQL (`SKIP LOCKED` leases, retries, dead-letter, idempotency keys); pull-based AI workers authenticated by worker tokens | Lets a GPU machine at home run AI jobs without opening inbound ports |
| P0-08 | AI provider adapters: `llm` (OpenAI-compatible → LM Studio), `stt` (Sarvam), `image` (local ComfyUI/diffusers worker) | Models, endpoints, and prompts are configuration |
| P0-09 | Media pipeline v1 in the worker: ffmpeg loudness normalization (−16 LUFS), AAC 64 kbps standard + 32 kbps data-saver renditions, duration, waveform, checksums | |
| P0-10 | Docker Compose: Caddy, api, worker, postgres; `.env`-based secrets; health checks | |
| P0-11 | Local hosting on the desktop: Docker Compose stack, local media storage behind the same storage interface as the Lightsail bucket, LAN access for phones, nightly `pg_dump` backups. Lightsail provisioning scripts are written but run in Phase 6 | Hosting environment until the final phase (decided 2026-09-23) |
| P0-12 | CI: lint, type check, unit and API tests, image build; local deploy script; cloud deploy wired in Phase 6 | GitHub Actions |
| P0-13 | Observability baseline: structured logs, request IDs, `/api/health`, error tracking with PII scrubbing, uptime check | |
| P0-14 | Security baseline: rotate the Sarvam key, remove demo passwords from production, rate limits, CORS, CSRF for cookie sessions, audit log table | |

**Risk to watch:** rewrites stall when they chase new features. Phase 0 is
parity plus the platform capabilities later phases need, nothing else.

---

## Phase 1 — Listener app (iOS, Android, web)

**Goal:** a family installs the Android review build (or uses mobile web on iPhone) and uses it daily
with no help.

**Exit criteria**

- A parent signs up in under 60 seconds, creates a child profile, and starts a
  story in two taps.
- Playback continues with the screen locked, survives app switches and phone
  calls, and resumes on another device at the same position.
- Stories download for offline listening; data-saver mode halves data usage.
- Bedtime mode (sleep timer with fade-out, no autoplay into a new story,
  screen dim) works without touching the screen after starting.
- The same experience works in a mobile browser and on desktop web.

| ID | Item | Notes |
|---|---|---|
| P1-01 | Expo (React Native, TypeScript) app with Expo Router; web build from the same codebase | One listener codebase for iOS, Android, and web |
| P1-02 | Onboarding: pick languages → pick ages of children → pick listening moments → done. Email OTP, Sign in with Apple, Sign in with Google | Apple requires Sign in with Apple when other social logins are offered |
| P1-03 | Households: parent account + child profiles (avatar, age band, languages); profile switch without login; PIN-protected parent area (parental gate) | Children never see settings, purchases, or external links |
| P1-04 | Home organized by **listening moments**: Bedtime, Drive, Run/Walk, Work/Focus, Learn — each a filtered, ordered shelf with duration chips (5/15/30/60+ min) | Replaces the generic grid |
| P1-05 | Player: background audio, lock-screen and headphone controls, speed 0.75–2×, ±15/30 s skip, chapters, queue, resume, sleep timer (end of chapter / minutes) with fade-out | `react-native-track-player` |
| P1-06 | Drive mode: full-screen giant controls, voice-friendly naming, auto-continue within a series | CarPlay/Android Auto in Phase 6 (needs Apple entitlement) |
| P1-07 | Bedtime mode: warm dark UI, dimmed screen, sleep timer by default, never autoplays a new story, optional gentle "goodnight" outro | |
| P1-08 | Cross-device sync: position, queue, favorites, history, per-profile | Ports existing favorites/stats |
| P1-09 | Offline downloads: encrypted in the app sandbox, storage management, Wi-Fi-only option, expire when the entitlement ends | |
| P1-10 | Data-saver mode and low-bandwidth handling (32 kbps rendition, small artwork) | |
| P1-11 | Story page: artwork, teaser (in the listener's language), narrator, duration, age band, moral/themes, "why it's good for bedtime/drive" | |
| P1-12 | Listening stats for parents: weekly minutes per child, screen-off share, stories finished, streaks, genre mix | Extends the current stats |
| P1-13 | Accessibility baseline: screen reader labels, dynamic type, 44 pt targets, contrast, reduced motion | |
| P1-14 | UI localization framework (ICU messages); English + Telugu UI strings; locale-aware numbers and dates | Epic L |
| P1-15 | Account deletion and data export inside the app | App Store requirement |

---

## Phase 2 — Narrator studio and automated pipeline

**Goal:** a narrator records a story on their phone and submits it in under 5
minutes of effort; an editor makes a publish decision in under 5 minutes.

**Exit criteria**

- Upload or record → automatic QC → transcription → AI drafts (metadata,
  teaser, safety, artwork) with no manual triggers.
- The narrator gets instant, plain-language QC feedback ("Too quiet — move
  closer to the mic") before submitting.
- The editor sees one consolidated review screen with AI pre-checks and
  publishes with one action; bulk publishing works for trusted narrators.

| ID | Item | Notes |
|---|---|---|
| P2-01 | Narrator onboarding: profile, languages, sample recording, rights and conduct agreement, payout details placeholder (KYC in Phase 5) | |
| P2-02 | In-app recording (mobile and web): level meter, pause/resume, retake the last section, optional teleprompter for the source text | Removes the need for recording software |
| P2-03 | Resumable uploads for large files (chunked, background upload on mobile) | |
| P2-04 | Automated audio QC: loudness, clipping, noise floor, silence, sample rate, duration, and speech ratio, with pass/warn/fail and fix tips | ffmpeg + simple DSP in the worker |
| P2-05 | Automatic pipeline orchestration: QC → STT → LLM metadata + teaser + safety + moral → artwork → ready for review; each step retryable and visible | Replaces manual process buttons |
| P2-06 | Source and rights attestation per submission: source type (original, public domain, licensed), source reference, license evidence upload | Epic R |
| P2-07 | Narrator dashboard: submission timeline with plain status ("Being checked", "With editor", "Published"), notifications, published catalog, listener stats | |
| P2-08 | Consolidated editor review: audio with waveform + transcript side by side, AI drafts as editable fields with confidence, safety flags, QC report, rights status, one-click Publish / Request changes (with templated reasons) | Collapses the current gates |
| P2-09 | Transcript review becomes optional: required only when captions are enabled or STT confidence is low | Saves the most editor time |
| P2-10 | Trust levels: narrators with a clean track record get expedited review and bulk publish | |
| P2-11 | Series and audiobooks: multi-chapter uploads, ordering, series metadata | |
| P2-12 | Studio web app (editor/admin): queues with SLA timers, keyboard shortcuts, bulk actions, audit trail | |
| P2-13 | Content safety policy and the age-rating rubric encoded as review checklists and AI safety prompts | Replaces BKL-003 |

---

## Phase 3 — Ratings, discovery, and community

**Goal:** listener ratings produce trustworthy quality signals for stories and
narrators, and discovery gets better with use.

**Exit criteria**

- Only genuine listeners can rate; one rating per account per story; the
  displayed scores resist brigading.
- Narrator scores are visible on narrator pages and ready to feed payouts.
- Search finds Telugu stories typed in English letters (transliteration).

| ID | Item | Notes |
|---|---|---|
| P3-01 | Story rating (1–5) and a separate narration rating ("How was the narration?"), prompted at the end of a story or after 60% listened | Separates content quality from performance quality |
| P3-02 | Rating integrity: minimum listen threshold, one per household member, parents rate for young children (kids get a simple emoji reaction), Bayesian averaging, rater trust weighting, anomaly detection for rating spikes | Needed before ratings affect money |
| P3-03 | Written reviews (adults only) with local-LLM moderation, a report button, editor moderation queue, narrator right of reply | |
| P3-04 | Narrator public pages: bio, languages, catalog, scores, follow | |
| P3-05 | Search: PostgreSQL full-text + trigram, transliteration (Telugu script ↔ Latin), synonyms, language filters | Epic L |
| P3-06 | Recommendations v1: embeddings from a local model (bge-m3 or multilingual-e5 via LM Studio) + listening co-occurrence; "Because you finished…", "More from this narrator" | pgvector |
| P3-07 | Imagination prompts: optional short spoken or written question at the end of a story ("What would you have done?"), drafted by a local LLM, approved by an editor, shown to parents as conversation starters | Supports the "provoke creativity" goal |
| P3-08 | Collections and editorial shelves (festivals, themes, age), manageable in the studio | |
| P3-09 | Notifications (opt-in): new story from followed narrator, series continuation; no streak-pressure notifications for children | |

---

## Phase 4 — Subscriptions and payments

**Goal:** a listener subscribes on web, iOS, or Android; the server grants the
same entitlement everywhere.

**Exit criteria**

- Sandbox purchases through Razorpay (web, India, UPI Autopay), Stripe (web,
  international), App Store, and Google Play all create the same entitlement.
- Renewals, cancellations, refunds, grace periods, and failed payments update
  access through webhooks within a minute.
- Every money event is in an append-only ledger that reconciles with provider
  reports.

| ID | Item | Notes |
|---|---|---|
| P4-01 | Plans and pricing per region/currency: free tier (limited catalog/samples), monthly, annual, family plan | Pricing numbers are your decision |
| P4-02 | Entitlements service: the server is the single source of truth; clients only read entitlements | |
| P4-03 | Web billing: Razorpay Subscriptions (INR, UPI Autopay, cards, e-mandate) and Stripe Billing (international) behind a `PaymentProvider` interface | |
| P4-04 | Store billing: App Store and Play subscriptions via RevenueCat, synced to entitlements by webhook | Store rules forbid pointing to cheaper web prices in most regions; see ARCHITECTURE.md |
| P4-05 | One-time purchases: individual audiobooks or gift subscriptions | |
| P4-06 | Paywall and trial UX: behind the parental gate, clear pricing, restore purchases, manage subscription | Store requirements |
| P4-07 | Webhook handling: signature verification, idempotency, replay, dead-letter, reconciliation job | |
| P4-08 | Tax and invoices: GST invoices for India, tax-inclusive pricing, invoice history in account | Confirm with an accountant |
| P4-09 | Finance dashboard: MRR, churn, refunds, failed payments, provider fees | |

---

## Phase 5 — Narrator earnings and payouts

**Goal:** a sandbox month-end close calculates each narrator's earnings from
published minutes and quality, produces statements, and sends approved payouts.

**Exit criteria**

- Earnings are fully explainable per story (minutes × rate × quality
  multiplier + engagement share) and visible to narrators in real time as
  "estimated".
- An admin reviews, holds, or approves the month's payouts; payouts are
  executed through the provider and reconciled.
- Clawbacks work when content is removed for rights violations.

| ID | Item | Notes |
|---|---|---|
| P5-01 | Earnings model v1 (see below) with configurable rates per language/region | |
| P5-02 | Double-entry earnings ledger: accruals, adjustments, holds, clawbacks, payouts | Immutable entries |
| P5-03 | Narrator KYC and payout accounts: RazorpayX Payouts (India: PAN, bank/UPI) and Stripe Connect (international) | |
| P5-04 | Monthly close: calculate → admin review → approve → payout → reconcile; minimum payout threshold | |
| P5-05 | Statements: monthly PDF/online statement per narrator with per-story breakdown | |
| P5-06 | Tax: TDS deduction and certificates (India), tax forms internationally | Confirm with an accountant |
| P5-07 | Disputes and adjustments workflow with an audit trail | |

**Earnings model v1 (recommended; confirm before build)**

A pure "per minute narrated" payment rewards padding and volume, and creates
payout liability that is not tied to revenue. The recommended hybrid keeps your
per-minute idea as the base and bounds the risk:

1. **Publication fee:** one-time `rate_per_finished_minute × published minutes`,
   paid when a story is published, capped per narrator per month.
2. **Quality multiplier:** 0.8–1.2 applied to the publication fee, from the
   Bayesian narration score once a story has at least N qualified ratings
   (1.0 until then). Paid as a true-up when the threshold is reached.
3. **Engagement pool:** a fixed share of net subscription revenue, split by
   qualified listening minutes (weighted by the quality multiplier). This ties
   ongoing earnings to what listeners actually value.
4. **Guards:** dead air and very slow narration are trimmed by QC before
   counting minutes; rights violations claw back earnings; ratings from
   suspicious accounts are excluded.

---

## Phase 6 — Hardening and store launch

**Goal:** both apps approved in the stores; production running with backups,
monitoring, and a documented restore.

**Exit criteria**

- App Store and Google Play approval, including family/children policy reviews.
- A restore drill from backup to a fresh Lightsail instance succeeds within the
  documented recovery time.
- A load test at 10× the expected launch concurrency passes on the production
  VM size.

| ID | Item | Notes |
|---|---|---|
| P6-01 | CarPlay and Android Auto browsing and playback | Apple CarPlay audio entitlement request needed |
| P6-02 | Privacy and compliance: India DPDP Act (verifiable parental consent, no behavioural tracking of children), COPPA, GDPR; privacy policy; terms; narrator agreement; data retention | Legal review required |
| P6-03 | Store readiness: listings in each launch language, screenshots, age ratings, data-safety forms, Google Play Families policy, Apple guidelines for kids and subscriptions | |
| P6-04 | Security review: dependency audit, pen test checklist, secrets rotation, staff 2FA enforcement, admin action audit | |
| P6-05 | Reliability: WAL archiving for point-in-time recovery, restore drill, runbooks, alerting, status page | |
| P6-06 | Performance: CDN caching, image optimization, API p95 < 300 ms, app cold start < 2.5 s on mid-range Android | |
| P6-07 | Accessibility audit (WCAG 2.2 AA on web; VoiceOver/TalkBack on mobile) | |
| P6-08 | Move hosting from the desktop to Lightsail (AWS details provided at this stage): staging + production, DNS for `kathachepta.com`, bucket + CDN, data migration from the desktop; blue/green deploys; mobile release pipeline via EAS Build/Submit and OTA updates | |
| P6-09 | Support tooling: in-app feedback, help center, refund handling | |

---

## Cross-cutting epics

### Epic L — Multilingual platform

Languages will grow beyond Telugu, so language is designed in, never bolted on.

- **Content language vs UI language are separate.** A Telugu-speaking parent
  may use an English UI and listen in Telugu and Hindi. Profiles store preferred
  listening languages in priority order.
- **Every content record has a BCP 47 language tag** (`te-IN`, `hi-IN`,
  `en-IN`, …). Teasers, metadata, and imagination prompts are stored per
  language with their own review status. Translations link to the source
  version and are invalidated when it changes.
- **AI routing per language:** STT provider and model, LLM model, prompt
  templates, and safety word lists are configured per language. Sarvam covers
  ten Indian languages plus English; languages it doesn't cover need a fallback
  (for example faster-whisper large-v3, benchmarked per language).
- **Search per script:** full-text configuration per language, transliteration
  to and from Latin script, and language-aware ranking.
- **UI:** ICU message format, locale-aware formatting, font stacks for each
  Indic script (Noto families), and layouts that support right-to-left
  scripts (for example Urdu) from Phase 1 by using logical CSS properties.
- **Narrators** declare languages and dialects; editors are assigned by
  language; payout rates can vary by language market.
- **Launching a language is a checklist, not a project:** UI strings
  translated, STT/LLM benchmarked, safety lists added, editor staffed, launch
  shelf curated.

### Epic R — Rights and provenance

- Rights register per story: source type, rights holder, license terms,
  territory, allowed uses (streaming, download, preview, translation), dates,
  evidence files.
- Narrator attestation at submission; editor verification before publish;
  automatic takedown flow; payouts held while rights are disputed.
- Existing 588-file catalog: **KathaChepta holds the rights** and no other
  copyright owners are known. Phase 0 migration records KathaChepta as rights
  holder with an owner attestation on every existing story, so they are
  publishable. The takedown flow still applies if a claim ever arrives.

### Epic S — Safety and trust

- Age bands and content descriptors (for example fear, violence, loss) per
  story, drafted by AI and confirmed by editors.
- Children never see reviews, comments, or external links; purchases and
  settings sit behind the parental gate.
- Moderation of reviews and narrator profiles, with a report flow and response
  SLA.

### Epic Q — Quality engineering

- Tests: unit tests for pricing, earnings, and entitlements; API contract tests;
  end-to-end flows (Playwright for web, Maestro for mobile); audio pipeline
  fixture tests.
- Release gates: no deploy with failing tests; database migrations reviewed;
  payment and earnings changes need a second approval (you).

## Decisions needed from you

| # | Decision | Needed by | My default if you don't choose |
|---|---|---|---|
| D1 | ~~Launch markets and currencies (India only, or India + US/diaspora)~~ | Phase 4 | **Decided (default accepted):** India (INR, Razorpay) + international (USD, Stripe) |
| D2 | ~~Where AI models run in production. Lightsail has no GPU instances.~~ | Phase 0 | **Decided (default accepted):** Pull-based AI worker on your GPU machine with LM Studio; slow CPU fallback on the VM |
| D3 | ~~Canonical brand name and spelling; domain~~ | — | **Decided:** KathaChepta. Production `kathachepta.com` (app at `app.`, API at `api.`), staging `staging.kathachepta.com`, `kadachepta.com` → 301 redirect |
| D4 | Apple/Google developer accounts (an organization account needs a D-U-N-S number) | Phase 6 (store submission) | **Deferred by you until near launch.** Until then: Android review builds are installable APKs (EAS internal distribution, no Play account needed); iOS review happens on mobile web and in a simulator build, because installing on a real iPhone needs an Apple developer account. Start the D-U-N-S request a few weeks before Phase 6 because it can take time |
| D5 | ~~Rights status of the existing 588 audio files~~ | — | **Decided:** KathaChepta holds the rights; all 588 are publishable as the seed catalog after editorial review |
| D6 | Pricing, narrator per-minute rate, pool share | Phases 4–5 | Configurable placeholders |
| D7 | ~~Second launch language~~ | Phase 3 | **Decided (default accepted):** Hindi (largest Sarvam-supported audience) |
| D8 | ~~Store billing strategy: in-app purchase everywhere vs. "reader app" external sign-up where allowed~~ | Phase 4 | **Decided (default accepted):** In-app purchase via RevenueCat (simplest approval path) |

## Retired backlog items

The previous BKL items are folded into the phases above:

| Old | New |
|---|---|
| BKL-001 content model | P0-02/P0-03, Epic L |
| BKL-002 rights register | Epic R, P2-06 |
| BKL-003 editorial and child-safety policy | P2-13, Epic S |
| BKL-010–012 ingestion, normalization, review queue | P0-04, P0-09, P2-12 |
| BKL-020–023 transcription and translation | P0-08, P2-05, P2-09, Epic L |
| BKL-030–034 teasers and previews | P2-05, P2-08, P1-11 |
| BKL-040–044 listening MVP | Phase 1 |
| BKL-050–053 discovery and family | P1-03/04/07, P3-04–08 |
| BKL-060–063 operations and monetization | P2-12, P4, P5, P4-09 |
| BKL-070–073 platform quality | P1-13, P1-09/10, P0-14, P6, Epic Q |
