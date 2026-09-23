# KathaChepta (కథాచెప్టా)

Human-narrated stories and audiobooks for families: press play, put the phone down.
Telugu first, built for many languages. See [BACKLOG.md](BACKLOG.md) for the roadmap and
[ARCHITECTURE.md](ARCHITECTURE.md) for the design.

## Run it locally

Requirements: Docker Desktop, Python 3.12+, and (for AI drafting) LM Studio with its server running.

```powershell
python scripts/setup_local.py      # creates .env with random secrets and worker tokens
docker compose up -d --build       # PostgreSQL, API, media workers, Caddy, Mailpit, backups
```

| What | Where |
|---|---|
| App (listener, narrator, editor sign-in) | http://localhost:8080 — phones on your Wi-Fi: `http://<desktop-ip>:8080` |
| API docs (OpenAPI) | http://localhost:8080/api/docs |
| Health and build info | http://localhost:8080/api/health |
| Sign-in codes sent by email (development) | http://localhost:8025 (Mailpit) |

Development accounts (created by the prototype migration or `npm run users:demo`) all use the password
`change-me`: `listener`, `parent`, `narrator`, `editor`, `admin`. Never use these in production.

### AI worker on the GPU

Teasers (LLM) and artwork run on the desktop, next to LM Studio, through the same pull-based worker a
GPU machine will use in production:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\run_gpu_worker.ps1
```

The model is set by `KC_LLM_MODEL` in `.env`. Compare models on real transcripts with
`python worker/bench/llm_benchmark.py --models qwen/qwen3-8b google/gemma-3-12b`.

### Everyday commands

```powershell
npm run status        # service health
npm run logs          # API and media worker logs
npm test              # lint + API tests in Docker
npm run stop
```

## Layout

| Path | Contents |
|---|---|
| `api/` | FastAPI service, SQLAlchemy models, Alembic migrations, tests |
| `worker/` | Pull-based job worker: audio processing (ffmpeg), transcription (Sarvam), teasers (LM Studio), artwork |
| `web/` | Current web pages (listener, narrator, editor); replaced by the Phase 1 app and Phase 2 studio |
| `infra/` | Caddy config, backup script, Lightsail provisioning (Phase 6) |
| `scripts/` | Local setup and the GPU worker launcher |
| `legacy/` | Retired prototype code, kept until Phase 0 sign-off |
| `data/` (ignored) | Local media storage and database backups |
| `audio/` (ignored) | Original prototype audio, mounted read-only |

## Migrating the prototype database

Already done on this desktop. To redo it from `catalog/kadachepta.db`:

```powershell
docker compose exec api python -m app.migrate_sqlite --reset
```

The report is printed and saved under `data/media/reports/`.
