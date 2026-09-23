"""PostgreSQL schema v1.

Carries over the prototype's data model (with IDs preserved) and adds what the
platform needs: persistent sessions and tokens, a leased job queue, pull-based
workers, storage keys instead of file paths, audit logging, and language tags
(BCP 47) on content, people, and preferences.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    BigInteger, Boolean, Date, DateTime, Float, ForeignKey, Index, Integer, String, Text,
    UniqueConstraint, func, text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base

Timestamp = DateTime(timezone=True)


def now_column(**kwargs: Any) -> Mapped[datetime]:
    return mapped_column(Timestamp, server_default=func.now(), nullable=False, **kwargs)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    username: Mapped[str | None] = mapped_column(String(64), unique=True)
    email: Mapped[str | None] = mapped_column(String(254), unique=True)
    display_name: Mapped[str | None] = mapped_column(String(120))
    role: Mapped[str] = mapped_column(String(32), nullable=False, server_default="listener")
    password_hash: Mapped[str | None] = mapped_column(Text)
    totp_secret: Mapped[str | None] = mapped_column(String(64))
    totp_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    ui_language: Mapped[str] = mapped_column(String(16), nullable=False, server_default="en")
    listening_languages: Mapped[list[str]] = mapped_column(
        ARRAY(String(16)), nullable=False, server_default=text("ARRAY['te-IN']::varchar[]"))
    created_at: Mapped[datetime] = now_column()
    updated_at: Mapped[datetime] = now_column(onupdate=func.now())
    last_login_at: Mapped[datetime | None] = mapped_column(Timestamp)
    disabled_at: Mapped[datetime | None] = mapped_column(Timestamp)

    @property
    def handle(self) -> str:
        return self.username or self.email or f"user-{self.id}"


class AuthSession(Base):
    """Web sessions and mobile access/refresh tokens. Only SHA-256 hashes are stored."""

    __tablename__ = "auth_sessions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)  # web | access | refresh
    family_id: Mapped[str | None] = mapped_column(String(36), index=True)  # refresh-token rotation family
    expires_at: Mapped[datetime] = mapped_column(Timestamp, nullable=False)
    created_at: Mapped[datetime] = now_column()
    last_used_at: Mapped[datetime | None] = mapped_column(Timestamp)
    revoked_at: Mapped[datetime | None] = mapped_column(Timestamp)
    mfa_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    user_agent: Mapped[str | None] = mapped_column(String(300))
    ip: Mapped[str | None] = mapped_column(String(64))

    user: Mapped[User] = relationship()


class EmailOtp(Base):
    __tablename__ = "email_otps"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    email: Mapped[str] = mapped_column(String(254), nullable=False, index=True)
    code_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(Timestamp, nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    consumed_at: Mapped[datetime | None] = mapped_column(Timestamp)
    created_at: Mapped[datetime] = now_column()


class AudioAsset(Base):
    """One recorded story (or story version). Phase 2 splits stories from their audio versions."""

    __tablename__ = "audio_assets"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    source_key: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    source_filename: Mapped[str | None] = mapped_column(Text)
    checksum_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    album: Mapped[str | None] = mapped_column(Text)
    collection: Mapped[str | None] = mapped_column(Text, index=True)
    artist: Mapped[str | None] = mapped_column(Text)
    narrator_name: Mapped[str | None] = mapped_column(Text)
    narrator_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    submitted_at: Mapped[datetime | None] = mapped_column(Timestamp)
    review_required: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    track_number: Mapped[str | None] = mapped_column(Text)
    episode_number: Mapped[str | None] = mapped_column(Text)
    genre: Mapped[str | None] = mapped_column(Text)
    genres: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, server_default="{}")
    language: Mapped[str] = mapped_column(String(16), nullable=False, server_default="te-IN", index=True)
    year: Mapped[str | None] = mapped_column(Text)
    audience_age_range: Mapped[str | None] = mapped_column(Text)
    mood: Mapped[str | None] = mapped_column(Text)
    listening_contexts: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, server_default="{}")
    content_warnings: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, server_default="{}")
    keywords: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, server_default="{}")
    moral_takeaway: Mapped[str | None] = mapped_column(Text)
    source_adaptation: Mapped[str | None] = mapped_column(Text)
    duration_seconds: Mapped[float] = mapped_column(Float, nullable=False, server_default="0")
    bitrate: Mapped[int | None] = mapped_column(Integer)
    sample_rate: Mapped[int | None] = mapped_column(Integer)
    channels: Mapped[int | None] = mapped_column(Integer)
    has_embedded_artwork: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    status: Mapped[str] = mapped_column(String(24), nullable=False, server_default="draft", index=True)
    metadata_review_status: Mapped[str] = mapped_column(String(24), nullable=False, server_default="not-reviewed")
    parent_asset_id: Mapped[str | None] = mapped_column(ForeignKey("audio_assets.id"))
    version_number: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    artwork_key: Mapped[str | None] = mapped_column(Text)
    artwork_updated_at: Mapped[datetime | None] = mapped_column(Timestamp)
    # {"standard": {"key", "bitrate", "bytes", "mime"}, "datasaver": {...}, "waveform": [...]} after media processing
    renditions: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    media_status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="pending")
    qc: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    published_at: Mapped[datetime | None] = mapped_column(Timestamp)
    created_at: Mapped[datetime] = now_column()
    updated_at: Mapped[datetime] = now_column(onupdate=func.now())

    narrator_user: Mapped[User | None] = relationship(foreign_keys=[narrator_user_id])


class NarratorProfile(Base):
    __tablename__ = "narrator_profiles"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    display_name: Mapped[str | None] = mapped_column(Text)
    biography: Mapped[str | None] = mapped_column(Text)
    languages: Mapped[list[str]] = mapped_column(ARRAY(String(16)), nullable=False, server_default="{te-IN}")
    updated_at: Mapped[datetime] = now_column(onupdate=func.now())


class NarratorCredit(Base):
    __tablename__ = "narrator_credits"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    narrator_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    audio_asset_id: Mapped[str] = mapped_column(ForeignKey("audio_assets.id"), unique=True, nullable=False)
    awarded_at: Mapped[datetime] = now_column()
    reason: Mapped[str] = mapped_column(Text, nullable=False, server_default="approved publication")


class AssetRights(Base):
    __tablename__ = "asset_rights"

    audio_asset_id: Mapped[str] = mapped_column(ForeignKey("audio_assets.id", ondelete="CASCADE"), primary_key=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, server_default="needs-review")
    source_type: Mapped[str | None] = mapped_column(String(32))  # kathachepta-owned | original | public-domain | licensed
    rights_holder: Mapped[str | None] = mapped_column(Text)
    recording_rights: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    performance_rights: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    adaptation_rights: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    artwork_rights: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    music_rights: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    territory: Mapped[str | None] = mapped_column(Text)
    allowed_uses: Mapped[str | None] = mapped_column(Text)
    license_start: Mapped[date | None] = mapped_column(Date)
    license_end: Mapped[date | None] = mapped_column(Date)
    evidence_reference: Mapped[str | None] = mapped_column(Text)
    attested_by: Mapped[str | None] = mapped_column(Text)
    attested_at: Mapped[datetime | None] = mapped_column(Timestamp)
    reviewer: Mapped[str | None] = mapped_column(Text)
    review_notes: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = now_column(onupdate=func.now())


class Transcript(Base):
    __tablename__ = "transcripts"
    __table_args__ = (UniqueConstraint("audio_asset_id", "version"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    audio_asset_id: Mapped[str] = mapped_column(ForeignKey("audio_assets.id", ondelete="CASCADE"), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    language: Mapped[str] = mapped_column(String(16), nullable=False)
    text: Mapped[str | None] = mapped_column(Text)
    segments: Mapped[Any] = mapped_column(JSONB, nullable=False, server_default="[]")
    raw_key: Mapped[str | None] = mapped_column(Text)
    provider: Mapped[str | None] = mapped_column(Text)
    model: Mapped[str | None] = mapped_column(Text)
    source_audio_checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, server_default="needs-review", index=True)
    reviewer: Mapped[str | None] = mapped_column(Text)
    review_notes: Mapped[str | None] = mapped_column(Text)
    reviewed_at: Mapped[datetime | None] = mapped_column(Timestamp)
    created_at: Mapped[datetime] = now_column()


class TeaserDraft(Base):
    __tablename__ = "teaser_drafts"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    audio_asset_id: Mapped[str] = mapped_column(ForeignKey("audio_assets.id", ondelete="CASCADE"), nullable=False, index=True)
    transcript_id: Mapped[int | None] = mapped_column(ForeignKey("transcripts.id", ondelete="SET NULL"))
    language: Mapped[str] = mapped_column(String(16), nullable=False)
    short_text: Mapped[str | None] = mapped_column(Text)
    long_text: Mapped[str | None] = mapped_column(Text)
    # Other-language renderings produced in the same pass: {"en-IN": {"short": .., "long": ..}}
    alternates: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    themes: Mapped[Any] = mapped_column(JSONB, nullable=False, server_default="[]")
    mood: Mapped[Any] = mapped_column(JSONB, nullable=False, server_default="[]")
    age_suggestion: Mapped[str | None] = mapped_column(Text)
    warnings: Mapped[Any] = mapped_column(JSONB, nullable=False, server_default="[]")
    provider: Mapped[str | None] = mapped_column(Text)
    model: Mapped[str | None] = mapped_column(Text)
    prompt_version: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(24), nullable=False, server_default="needs-review", index=True)
    reviewer: Mapped[str | None] = mapped_column(Text)
    review_notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = now_column()


class Job(Base):
    """Leased background job. Workers pull jobs over HTTPS; results are applied by the API."""

    __tablename__ = "jobs"
    __table_args__ = (
        Index("ix_jobs_ready", "status", "job_type", "priority", "run_after"),
        Index("ix_jobs_asset_type", "audio_asset_id", "job_type"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    job_type: Mapped[str] = mapped_column(String(32), nullable=False)
    audio_asset_id: Mapped[str | None] = mapped_column(ForeignKey("audio_assets.id", ondelete="CASCADE"))
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="queued")
    # queued | leased | succeeded | failed (will retry) | dead (gave up) | cancelled
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="3")
    # Lower runs first: people waiting on a result (uploads, editor actions) beat bulk backfills.
    priority: Mapped[int] = mapped_column(Integer, nullable=False, server_default="50")
    run_after: Mapped[datetime] = now_column()
    lease_until: Mapped[datetime | None] = mapped_column(Timestamp)
    leased_by: Mapped[str | None] = mapped_column(String(64))
    idempotency_key: Mapped[str | None] = mapped_column(String(128), unique=True)
    error: Mapped[str | None] = mapped_column(Text)
    log_tail: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = now_column()
    updated_at: Mapped[datetime] = now_column(onupdate=func.now())


class Worker(Base):
    __tablename__ = "workers"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    capabilities: Mapped[list[str]] = mapped_column(ARRAY(String(32)), nullable=False, server_default="{}")
    last_seen_at: Mapped[datetime | None] = mapped_column(Timestamp)
    info: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    created_at: Mapped[datetime] = now_column()
    disabled_at: Mapped[datetime | None] = mapped_column(Timestamp)


class ListenerFavorite(Base):
    __tablename__ = "listener_favorites"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    audio_asset_id: Mapped[str] = mapped_column(ForeignKey("audio_assets.id", ondelete="CASCADE"), primary_key=True)
    created_at: Mapped[datetime] = now_column()


class ListeningProgress(Base):
    __tablename__ = "listening_progress"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    audio_asset_id: Mapped[str] = mapped_column(ForeignKey("audio_assets.id", ondelete="CASCADE"), primary_key=True)
    seconds_listened: Mapped[float] = mapped_column(Float, nullable=False, server_default="0")
    last_position: Mapped[float] = mapped_column(Float, nullable=False, server_default="0")
    play_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    completed: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    first_listened_at: Mapped[datetime] = now_column()
    last_listened_at: Mapped[datetime] = now_column()


class ListeningDaily(Base):
    __tablename__ = "listening_daily"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    seconds: Mapped[float] = mapped_column(Float, nullable=False, server_default="0")


class EditorialEvent(Base):
    __tablename__ = "editorial_events"
    __table_args__ = (Index("ix_editorial_events_entity", "entity_type", "entity_id"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    entity_type: Mapped[str] = mapped_column(String(32), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(64), nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    actor: Mapped[str] = mapped_column(Text, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = now_column()


class AuditLog(Base):
    """Security-relevant events: logins, failures, token reuse, role and MFA changes."""

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    actor_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    action: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    detail: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    ip: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = now_column()
