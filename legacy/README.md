# Prototype code (retired in Phase 0)

The single-file standard-library server and scripts that ran the prototype.
Everything here is replaced by `api/` (FastAPI + PostgreSQL) and `worker/`:

| Prototype | Replacement |
|---|---|
| `scripts/editor_server.py` | `api/app/` |
| `scripts/init_local_store.py`, `create_demo_users.py` | Alembic migrations, `python -m app.cli seed-demo` |
| `scripts/transcribe_sarvam.py` | `worker/kc_worker/handlers/transcription.py` |
| `scripts/ollama_teaser.py`, `review_*.py` | `worker/kc_worker/handlers/teaser.py` (LM Studio), editor UI |
| `scripts/generate_artwork.py` | `worker/kc_worker/handlers/artwork.py` |
| `scripts/ingest_catalog.py` | One-time import already done; data migrated by `api/app/migrate_sqlite.py` |
| `config/secrets.local.json` | `.env` (created by `scripts/setup_local.py`) |

Delete this folder once the Phase 0 parity checklist is signed off.
