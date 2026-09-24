"""Test harness: a dedicated PostgreSQL database, a temporary media root, and helpers.

Run with:  docker compose --profile test run --rm api-test
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

_media = Path(tempfile.mkdtemp(prefix="kc-media-"))
_legacy = Path(tempfile.mkdtemp(prefix="kc-legacy-"))
_base_url = os.environ.get("KC_DATABASE_URL", "postgresql+psycopg://kathachepta:kathachepta@localhost:5433/kathachepta")
TEST_DATABASE_URL = os.environ.get("KC_TEST_DATABASE_URL") or _base_url.rsplit("/", 1)[0] + "/kathachepta_test"
os.environ.update({
    "KC_ENVIRONMENT": "test", "KC_DATABASE_URL": TEST_DATABASE_URL, "KC_MEDIA_ROOT": str(_media),
    "KC_LEGACY_AUDIO_ROOT": str(_legacy), "KC_SECRET_KEY": "test-secret-key-for-signing-media-urls-0123456789",
    "KC_BOOTSTRAP_WORKERS": "", "KC_STAFF_MFA_REQUIRED": "false",
})

import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402

from app import mailer, ratelimit  # noqa: E402
from app.db import get_sessionmaker  # noqa: E402
from app.models import AssetRights, AudioAsset, NarratorProfile, TeaserDraft, Transcript, User, Worker  # noqa: E402
from app.security import hash_password, token_hash  # noqa: E402

API_ROOT = Path(__file__).resolve().parents[1]


def _ensure_database() -> None:
    admin_url = TEST_DATABASE_URL.rsplit("/", 1)[0] + "/postgres"
    engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with engine.connect() as connection:
        exists = connection.execute(text("SELECT 1 FROM pg_database WHERE datname='kathachepta_test'")).scalar()
        if not exists:
            connection.execute(text("CREATE DATABASE kathachepta_test"))
    engine.dispose()


@pytest.fixture(scope="session", autouse=True)
def database():
    _ensure_database()
    config = Config(str(API_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(API_ROOT / "alembic"))
    command.downgrade(config, "base")
    command.upgrade(config, "head")
    yield


@pytest.fixture(autouse=True)
def clean(database):
    with get_sessionmaker()() as db:
        tables = db.execute(text("SELECT tablename FROM pg_tables WHERE schemaname='public' "
                                 "AND tablename <> 'alembic_version'")).scalars().all()
        db.execute(text(f"TRUNCATE {', '.join(tables)} RESTART IDENTITY CASCADE"))
        db.commit()
    ratelimit.reset()
    mailer.sent_messages.clear()
    yield


@pytest.fixture
def db():
    with get_sessionmaker()() as session:
        yield session


@pytest.fixture
def client():
    from app.main import app
    with TestClient(app) as test_client:
        yield test_client


def make_user(db, username: str, role: str, password: str = "correct horse battery", **extra) -> User:
    user = User(username=username, role=role, display_name=username, password_hash=hash_password(password), **extra)
    db.add(user)
    db.flush()
    if role == "narrator":
        db.add(NarratorProfile(user_id=user.id, display_name=username))
    db.commit()
    return user


def login(client: TestClient, username: str, password: str = "correct horse battery") -> dict:
    response = client.post("/api/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text
    return response.json()


def make_asset(db, asset_id: str = "a" * 16, *, status: str = "draft", narrator: User | None = None,
               audio_bytes: bytes = b"ID3" + b"\0" * 5000, ready_to_publish: bool = False, **fields) -> AudioAsset:
    key = f"legacy/{asset_id}.mp3"
    (_legacy / f"{asset_id}.mp3").write_bytes(audio_bytes)
    asset = AudioAsset(id=asset_id, source_key=key, source_filename=f"{asset_id}.mp3", checksum_sha256="0" * 64,
                       title=fields.pop("title", f"Story {asset_id[:4]}"), status=status,
                       narrator_user_id=narrator.id if narrator else None, duration_seconds=300,
                       genres=fields.pop("genres", ["Folklore"]), **fields)
    db.add(asset)
    db.flush()
    if ready_to_publish:
        asset.audience_age_range, asset.moral_takeaway, asset.source_adaptation = "4-8", "Be kind.", "Folk tale"
        asset.metadata_review_status = "approved"
        asset.media_status = "ready"
        transcript = Transcript(audio_asset_id=asset.id, version=1, language="te-IN", text="కథ", status="approved",
                                source_audio_checksum="0" * 64)
        db.add(transcript)
        db.flush()
        db.add(TeaserDraft(audio_asset_id=asset.id, transcript_id=transcript.id, language="te-IN",
                           short_text="చిన్న కథ", long_text="ఒక మంచి కథ", status="approved"))
        db.add(AssetRights(audio_asset_id=asset.id, status="approved", recording_rights=True, performance_rights=True,
                           adaptation_rights=True, artwork_rights=True, music_rights=True))
    db.commit()
    return asset


def make_worker(db, name: str = "test-worker", capabilities=("media", "stt", "llm", "image")) -> str:
    token = f"worker-token-{name}-0123456789abcdef"
    db.add(Worker(name=name, token_hash=token_hash(token), capabilities=list(capabilities)))
    db.commit()
    return token
