"""Narrator studio API: onboarding, submissions (upload or in-app recording), status, series, and stats."""

from __future__ import annotations

import hashlib
import re
from pathlib import PurePosixPath
from typing import Any, Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload
from starlette.concurrency import run_in_threadpool

from .. import jobs
from ..auth import Identity, audit, require, require_identity, utcnow
from ..config import get_settings
from ..db import get_db
from ..models import (
    AssetRights, AudioAsset, EditorialEvent, ListenerFavorite, ListeningProgress, NarratorCredit, NarratorProfile,
    Notification, Series, TeaserDraft, Transcript, Upload,
)
from ..services import pipeline
from ..services import settings as app_settings
from ..services.assets import apply_metadata, asset_payload, clean_metadata, iso, normalize_language
from ..storage import get_storage, media_url

router = APIRouter(prefix="/api/narrator", tags=["narrator"])

AUDIO_EXTENSIONS = {".mp3", ".m4a", ".aac", ".wav", ".flac", ".ogg", ".opus", ".webm", ".3gp", ".caf"}
AGREEMENT_VERSION = "2026-09"
AGREEMENT = [
    "I only submit recordings of my own voice.",
    "I have the right to narrate the text: it is my own work, in the public domain, owned by KathaChepta, or "
    "licensed to me for audio. I will say which when I submit.",
    "I won't add music, sound effects, or other material I don't have rights to.",
    "My recordings follow the KathaChepta content policy for children and families.",
    "I never present AI-generated narration as my own voice.",
    "KathaChepta may edit, publish, and distribute my published recordings; payments follow the narrator "
    "terms that start with narrator earnings (Phase 5).",
]
SOURCE_TYPES = ("original", "public-domain", "kathachepta-owned", "licensed")


def safe_filename(name: str | None) -> str:
    stem = PurePosixPath((name or "narration.mp3").replace("\\", "/")).name
    stem = re.sub(r"[^\w.\- ]+", "_", stem, flags=re.UNICODE).strip() or "narration.mp3"
    return stem[:120]


def _own_assets(identity: Identity):
    return (select(AudioAsset).where(AudioAsset.narrator_user_id == identity.user.id)
            .options(selectinload(AudioAsset.narrator_user), selectinload(AudioAsset.series)))


def _own_asset(db: Session, identity: Identity, asset_id: str) -> AudioAsset:
    asset = db.scalars(_own_assets(identity).where(AudioAsset.id == asset_id)).first()
    if not asset:
        raise HTTPException(status_code=404, detail="Submission not found.")
    return asset


def submission_summary(asset: AudioAsset) -> dict[str, Any]:
    return asset_payload(asset, stage=asset.pipeline_stage, stageLabel=pipeline.STAGES.get(asset.pipeline_stage),
                         qcVerdict=(asset.qc or {}).get("verdict"), changesRequested=asset.changes_requested or None,
                         series={"id": asset.series.id, "title": asset.series.title} if asset.series else None,
                         seriesPosition=asset.series_position)


def _profile_payload(profile: NarratorProfile | None, identity: Identity) -> dict[str, Any] | None:
    if not profile:
        return None
    return {"username": identity.username, "displayName": profile.display_name, "biography": profile.biography,
            "language": (profile.languages or ["te-IN"])[0], "languages": profile.languages,
            "trustLevel": profile.trust_level, "onboarded": bool(profile.onboarded_at),
            "agreementVersion": profile.agreement_version, "sampleUrl": media_url(profile.sample_key),
            "updatedAt": iso(profile.updated_at)}


# --- Onboarding (P2-01) ---

@router.get("/agreement")
def agreement():
    return {"version": AGREEMENT_VERSION, "items": AGREEMENT, "sourceTypes": SOURCE_TYPES,
            "payouts": "Payout details are collected when narrator earnings start (Phase 5)."}


class Application(BaseModel):
    displayName: str = Field(min_length=1, max_length=120)
    biography: str = Field(default="", max_length=2000)
    languages: list[str] = Field(min_length=1, max_length=8)
    agreementVersion: str
    sampleUploadId: str | None = None


@router.post("/apply")
def apply(payload: Application, request: Request, identity: Identity = Depends(require_identity),
          db: Session = Depends(get_db)):
    """Listeners become narrators in one step. Nothing they submit is published without an editor."""
    user = identity.user
    if user.role not in {"listener", "parent", "narrator"}:
        raise HTTPException(status_code=409, detail="Staff accounts can't become narrators.")
    if payload.agreementVersion != AGREEMENT_VERSION:
        raise HTTPException(status_code=409, detail="The narrator agreement changed; please read it again.")
    profile = db.get(NarratorProfile, user.id) or NarratorProfile(user_id=user.id)
    profile.display_name, profile.biography = payload.displayName.strip(), payload.biography.strip()
    user.display_name = profile.display_name  # the name listeners see on stories
    profile.languages = [normalize_language(language) for language in payload.languages]
    profile.agreement_version, profile.agreement_accepted_at = AGREEMENT_VERSION, utcnow()
    profile.onboarded_at = profile.onboarded_at or utcnow()
    if payload.sampleUploadId:
        upload = db.scalars(select(Upload).where(Upload.id == payload.sampleUploadId, Upload.user_id == user.id,
                                                 Upload.status == "complete")).first()
        if not upload:
            raise HTTPException(status_code=409, detail="The sample recording hasn't finished uploading.")
        key = f"samples/{user.id}/{upload.id}-{upload.filename}"
        get_storage().move(upload.key, key)
        upload.status, profile.sample_key = "used", key
    db.add(profile)
    if user.role != "narrator":
        audit(db, "role:self-narrator", request, user.id, previous=user.role)
        user.role = "narrator"
    db.commit()
    return {"ok": True, "profile": _profile_payload(profile, identity)}


# --- Home and status (P2-07) ---

@router.get("/home")
def home(identity: Identity = Depends(require("narrator.pipeline")), db: Session = Depends(get_db)):
    profile = db.get(NarratorProfile, identity.user.id)
    rows = db.scalars(_own_assets(identity).order_by(AudioAsset.updated_at.desc()).limit(200)).all()
    unread = db.scalar(select(func.count()).select_from(Notification).where(
        Notification.user_id == identity.user.id, Notification.read_at.is_(None)))
    stats = _story_stats(db, [a.id for a in rows if a.status == "published"])
    totals = {"published": sum(1 for a in rows if a.status == "published"),
              "inProgress": sum(1 for a in rows if a.pipeline_stage in pipeline.IN_PROGRESS),
              "needsAttention": sum(1 for a in rows if a.pipeline_stage in ("needs-fix", "changes-requested",
                                                                               "awaiting-submit")),
              "listeners": sum(s["listeners"] for s in stats.values()),
              "minutesListened": round(sum(s["seconds"] for s in stats.values()) / 60),
              "completions": sum(s["completions"] for s in stats.values()),
              "favorites": sum(s["favorites"] for s in stats.values()),
              "publishedMinutes": round(sum(a.duration_seconds or 0 for a in rows if a.status == "published") / 60)}
    return {"profile": _profile_payload(profile, identity), "totals": totals, "unreadNotifications": unread,
            "submissions": [submission_summary(a) | {"stats": stats.get(a.id)} for a in rows],
            "series": _series_list(db, identity)}


def _story_stats(db: Session, asset_ids: list[str]) -> dict[str, dict[str, Any]]:
    """Aggregated listening for a narrator's stories. Never exposes who listened."""
    if not asset_ids:
        return {}
    stats = {asset_id: {"listeners": 0, "seconds": 0, "completions": 0, "favorites": 0} for asset_id in asset_ids}
    for asset_id, listeners, seconds, completions in db.execute(
            select(ListeningProgress.audio_asset_id, func.count(), func.sum(ListeningProgress.seconds_listened),
                   func.count().filter(ListeningProgress.completed))
            .where(ListeningProgress.audio_asset_id.in_(asset_ids)).group_by(ListeningProgress.audio_asset_id)):
        stats[asset_id].update(listeners=listeners, seconds=round(seconds or 0), completions=completions)
    for asset_id, count in db.execute(select(ListenerFavorite.audio_asset_id, func.count())
                                      .where(ListenerFavorite.audio_asset_id.in_(asset_ids))
                                      .group_by(ListenerFavorite.audio_asset_id)):
        stats[asset_id]["favorites"] = count
    return stats


@router.get("/submissions/{asset_id}")
def submission(asset_id: str, identity: Identity = Depends(require("narrator.pipeline")),
               db: Session = Depends(get_db)):
    asset = _own_asset(db, identity, asset_id)
    draft = pipeline.latest_draft(db, asset.id)
    rights = db.get(AssetRights, asset.id)
    history = db.scalars(select(EditorialEvent).where(EditorialEvent.entity_id == asset.id)
                         .order_by(EditorialEvent.id.desc()).limit(30)).all()
    return {
        **submission_summary(asset), "timeline": pipeline.narrator_timeline(db, asset),
        "pipelineError": asset.pipeline_error, "waveform": (asset.renditions or {}).get("waveform", []),
        "sourceText": asset.source_text,
        "draft": {"shortText": draft.short_text, "longText": draft.long_text, "themes": draft.themes,
                  "ageSuggestion": draft.age_suggestion} if draft else None,
        "attestation": rights.attestation if rights else {},
        "stats": _story_stats(db, [asset.id]).get(asset.id) if asset.status == "published" else None,
        "history": [{"action": e.action, "notes": e.notes, "createdAt": iso(e.created_at),
                     "actor": "you" if e.actor == identity.username else ("KathaChepta" if not e.actor.startswith("ai:")
                                                                          else "automatic")}
                    for e in history],
    }


# --- Submissions (P2-02, P2-03, P2-06, P2-11) ---

class Attestation(BaseModel):
    sourceType: Literal["original", "public-domain", "kathachepta-owned", "licensed"]
    sourceReference: str = Field(default="", max_length=500)  # book, author, link, or "my own story"
    notes: str = Field(default="", max_length=2000)
    evidenceUploadId: str | None = None


class NewSubmission(BaseModel):
    uploadIds: list[str] = Field(min_length=1, max_length=50)  # several takes are joined in order
    title: str = Field(min_length=1, max_length=200)
    language: str = "te-IN"
    seriesId: int | None = None
    seriesPosition: int | None = Field(default=None, ge=1, le=10000)
    parentAssetId: str | None = None  # a new version of one of your published stories
    sourceText: str | None = Field(default=None, max_length=200_000)
    attestation: Attestation
    autoSubmit: bool = True  # continue to review automatically when the sound check passes


def _completed_uploads(db: Session, identity: Identity, upload_ids: list[str]) -> list[Upload]:
    uploads = {u.id: u for u in db.scalars(select(Upload).where(Upload.id.in_(upload_ids),
                                                                Upload.user_id == identity.user.id))}
    missing = [uid for uid in upload_ids if uid not in uploads or uploads[uid].status != "complete"
               or uploads[uid].purpose != "audio"]
    if missing:
        raise HTTPException(status_code=409, detail={"error": "Some recordings haven't finished uploading.",
                                                     "uploadIds": missing})
    return [uploads[uid] for uid in upload_ids]


def _checksum(key: str) -> str:
    digest = hashlib.sha256()
    with get_storage().path(key).open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _check_in_progress_limit(db: Session, identity: Identity) -> None:
    profile = db.get(NarratorProfile, identity.user.id)
    if profile and profile.trust_level == "trusted":
        return
    limit = int(app_settings.get(db, "narrators.newInProgressLimit"))
    count = db.scalar(select(func.count()).select_from(AudioAsset).where(
        AudioAsset.narrator_user_id == identity.user.id, AudioAsset.pipeline_stage.in_(pipeline.IN_PROGRESS)))
    if count >= limit:
        raise HTTPException(status_code=409, detail=f"You have {count} stories being prepared or reviewed. New "
                            f"narrators can have {limit} at a time; you can submit more once one is published.")


def _own_series(db: Session, identity: Identity, series_id: int | None) -> Series | None:
    if series_id is None:
        return None
    series = db.get(Series, series_id)
    if not series or series.narrator_user_id != identity.user.id:
        raise HTTPException(status_code=404, detail="Series not found.")
    return series


def _attest(db: Session, identity: Identity, asset: AudioAsset, attestation: Attestation) -> None:
    rights = db.get(AssetRights, asset.id) or AssetRights(audio_asset_id=asset.id)
    if rights.status == "approved" and asset.status == "published":
        return
    rights.attestation = {"sourceType": attestation.sourceType, "sourceReference": attestation.sourceReference.strip(),
                          "notes": attestation.notes.strip(), "by": identity.username, "attestedAt": iso(utcnow()),
                          "agreementVersion": AGREEMENT_VERSION}
    rights.source_type, rights.attested_by, rights.attested_at = attestation.sourceType, identity.username, utcnow()
    rights.status = "needs-review"
    if attestation.evidenceUploadId:
        upload = db.scalars(select(Upload).where(Upload.id == attestation.evidenceUploadId,
                                                 Upload.user_id == identity.user.id, Upload.status == "complete")).first()
        if not upload:
            raise HTTPException(status_code=409, detail="The evidence file hasn't finished uploading.")
        key = f"evidence/{asset.id}/{upload.id}-{upload.filename}"
        get_storage().move(upload.key, key)
        upload.status, rights.evidence_key = "used", key
    db.add(rights)


def _place_audio(db: Session, identity: Identity, asset_id: str, uploads: list[Upload]) -> tuple[str, list[str]]:
    """Move uploaded takes into originals/. Returns (source key, extra part keys to join)."""
    keys = []
    for index, upload in enumerate(uploads):
        key = f"originals/{asset_id}/{index + 1:02d}-{upload.filename}" if len(uploads) > 1 \
            else f"originals/{asset_id}/{upload.filename}"
        get_storage().move(upload.key, key)
        upload.status = "used"
        keys.append(key)
    return keys[0], keys if len(keys) > 1 else []


@router.post("/submissions", status_code=201)
def create_submission(payload: NewSubmission, identity: Identity = Depends(require("narrator.upload")),
                      db: Session = Depends(get_db)):
    settings = get_settings()
    uploads = _completed_uploads(db, identity, payload.uploadIds)
    _check_in_progress_limit(db, identity)
    series = _own_series(db, identity, payload.seriesId)
    checksums = [_checksum(upload.key) for upload in uploads]
    checksum = checksums[0] if len(checksums) == 1 else hashlib.sha256("".join(checksums).encode()).hexdigest()
    asset_id = checksum[:16]
    existing = db.get(AudioAsset, asset_id)
    if existing:
        raise HTTPException(status_code=409, detail="This exact recording was already submitted.")
    version, parent = 1, None
    if payload.parentAssetId:
        parent = db.get(AudioAsset, payload.parentAssetId)
        if not parent or parent.narrator_user_id != identity.user.id or parent.status != "published":
            raise HTTPException(status_code=409, detail="Only your published stories can get a new version.")
        version = (db.scalar(select(func.max(AudioAsset.version_number)).where(
            (AudioAsset.id == parent.id) | (AudioAsset.parent_asset_id == parent.id))) or 1) + 1
    source_key, parts = _place_audio(db, identity, asset_id, uploads)
    now = utcnow()
    asset = AudioAsset(id=asset_id, source_key=source_key, source_filename=PurePosixPath(source_key).name,
                       checksum_sha256=checksum, title=payload.title.strip(), narrator_user_id=identity.user.id,
                       status="draft", parent_asset_id=parent.id if parent else None, version_number=version,
                       language=normalize_language(payload.language or settings.default_language),
                       series_id=series.id if series else None, series_position=payload.seriesPosition,
                       source_text=(payload.sourceText or "").strip() or None,
                       source_adaptation=_source_label(payload.attestation),
                       submitted_at=now if payload.autoSubmit else None, pipeline_stage="checking")
    if series:
        asset.album = series.title
    db.add(asset)
    db.flush()
    _attest(db, identity, asset, payload.attestation)
    jobs.enqueue(db, "media.process", asset_id=asset_id, created_by=identity.username,
                 payload={"parts": parts} if parts else {}, idempotency_key=f"media:{asset_id}:{checksum}",
                 priority=jobs.PRIORITY_INTERACTIVE)
    db.add(EditorialEvent(entity_type="audio_asset", entity_id=asset_id, action="content:uploaded",
                          actor=identity.username, notes=f"{len(uploads)} recording(s)"))
    db.commit()
    return submission_summary(asset)


def _source_label(attestation: Attestation) -> str:
    label = {"original": "Original story by the narrator", "public-domain": "Public domain",
             "kathachepta-owned": "KathaChepta", "licensed": "Licensed"}[attestation.sourceType]
    reference = attestation.sourceReference.strip()
    return f"{label}: {reference}" if reference and attestation.sourceType != "original" else label


class SubmissionEdit(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    language: str | None = None
    seriesId: int | None = None
    seriesPosition: int | None = Field(default=None, ge=1, le=10000)
    sourceText: str | None = Field(default=None, max_length=200_000)
    attestation: Attestation | None = None


@router.post("/submissions/{asset_id}/details")
def edit_submission(asset_id: str, payload: SubmissionEdit, identity: Identity = Depends(require("narrator.upload")),
                    db: Session = Depends(get_db)):
    asset = _own_asset(db, identity, asset_id)
    if asset.status in ("published", "archived"):
        raise HTTPException(status_code=409, detail="Published stories change through a new version.")
    fields = payload.model_fields_set
    if payload.title:
        asset.title = payload.title.strip()
    if payload.language:
        asset.language = normalize_language(payload.language)
    if "seriesId" in fields:
        series = _own_series(db, identity, payload.seriesId)
        asset.series_id, asset.album = (series.id, series.title) if series else (None, asset.album)
    if "seriesPosition" in fields:
        asset.series_position = payload.seriesPosition
    if "sourceText" in fields:
        asset.source_text = (payload.sourceText or "").strip() or None
    if payload.attestation:
        _attest(db, identity, asset, payload.attestation)
        asset.source_adaptation = _source_label(payload.attestation)
    asset.metadata_review_status = "not-reviewed"
    db.add(EditorialEvent(entity_type="audio_asset", entity_id=asset.id, action="content:details-edited",
                          actor=identity.username))
    db.commit()
    return submission_summary(asset)


@router.post("/submissions/{asset_id}/submit")
def submit(asset_id: str, identity: Identity = Depends(require("narrator.upload")), db: Session = Depends(get_db)):
    """Send a checked recording on to preparation and review (or back to review after changes)."""
    asset = _own_asset(db, identity, asset_id)
    if asset.pipeline_stage not in ("awaiting-submit", "changes-requested"):
        raise HTTPException(status_code=409, detail=f"This story is {pipeline.STAGES.get(asset.pipeline_stage, '')}.")
    if (asset.qc or {}).get("verdict") == "fail":
        raise HTTPException(status_code=409, detail="Fix the sound problems first by replacing the recording.")
    asset.submitted_at = utcnow()
    if asset.status == "rejected":
        asset.status = "draft"
    if asset.pipeline_stage == "changes-requested":
        asset.changes_requested = {**asset.changes_requested, "resolvedAt": iso(utcnow())}
    db.add(EditorialEvent(entity_type="audio_asset", entity_id=asset.id, action="content:submitted",
                          actor=identity.username))
    asset.pipeline_stage = "checking"
    pipeline.advance(db, asset, actor=identity.username, start=True)
    db.commit()
    return submission_summary(asset)


class Replacement(BaseModel):
    uploadIds: list[str] = Field(min_length=1, max_length=50)
    autoSubmit: bool = True


@router.post("/submissions/{asset_id}/replace-audio")
def replace_audio(asset_id: str, payload: Replacement, identity: Identity = Depends(require("narrator.upload")),
                  db: Session = Depends(get_db)):
    """Re-record after a failed sound check or an editor's request, keeping the story's details."""
    asset = _own_asset(db, identity, asset_id)
    if asset.status in ("published", "archived"):
        raise HTTPException(status_code=409, detail="Published stories change through a new version.")
    uploads = _completed_uploads(db, identity, payload.uploadIds)
    old_keys = [asset.source_key, *[(v or {}).get("key") for v in (asset.renditions or {}).values()
                                    if isinstance(v, dict)]]
    checksums = [_checksum(upload.key) for upload in uploads]
    asset.checksum_sha256 = checksums[0] if len(checksums) == 1 else hashlib.sha256("".join(checksums).encode()).hexdigest()
    asset.version_number += 1
    source_key, parts = _place_audio(db, identity, asset.id, uploads)
    asset.source_key, asset.source_filename = source_key, PurePosixPath(source_key).name
    asset.renditions, asset.qc, asset.media_status = {}, {}, "pending"
    asset.submitted_at = utcnow() if payload.autoSubmit else None
    if asset.status == "rejected":
        asset.status = "draft"
    # The transcript and drafts described the old recording.
    for transcript in db.scalars(select(Transcript).where(Transcript.audio_asset_id == asset.id,
                                                          Transcript.status.in_(pipeline.USABLE))):
        transcript.status = "superseded"
    for draft in db.scalars(select(TeaserDraft).where(TeaserDraft.audio_asset_id == asset.id,
                                                      TeaserDraft.status.in_(("needs-review", "approved")))):
        draft.status = "superseded"
    jobs.enqueue(db, "media.process", asset_id=asset.id, created_by=identity.username,
                 payload={"parts": parts} if parts else {}, idempotency_key=f"media:{asset.id}:{asset.checksum_sha256}",
                 priority=jobs.PRIORITY_INTERACTIVE)
    asset.pipeline_stage = "checking"
    db.add(EditorialEvent(entity_type="audio_asset", entity_id=asset.id, action="content:audio-replaced",
                          actor=identity.username, notes=f"version {asset.version_number}"))
    db.commit()
    for key in filter(None, old_keys):
        if key.startswith("originals/") and key != source_key:
            get_storage().delete(key)
    return submission_summary(asset)


@router.post("/submissions/{asset_id}/withdraw")
def withdraw(asset_id: str, identity: Identity = Depends(require("narrator.upload")), db: Session = Depends(get_db)):
    asset = _own_asset(db, identity, asset_id)
    if asset.status in ("published", "archived"):
        raise HTTPException(status_code=409, detail="Published stories can't be withdrawn here; contact an editor.")
    keys = [asset.source_key, asset.artwork_key,
            *[(v or {}).get("key") for v in (asset.renditions or {}).values() if isinstance(v, dict)]]
    jobs.cancel_active(db, asset.id)
    db.delete(asset)
    db.add(EditorialEvent(entity_type="narrator_asset", entity_id=asset.id, action="content:withdrawn",
                          actor=identity.username))
    db.commit()
    for key in filter(None, keys):
        if not key.startswith("legacy/"):
            get_storage().delete(key)
    return {"ok": True}


# --- Series (P2-11) ---

def _series_list(db: Session, identity: Identity) -> list[dict[str, Any]]:
    rows = db.execute(select(Series, func.count(AudioAsset.id)).outerjoin(AudioAsset, AudioAsset.series_id == Series.id)
                      .where(Series.narrator_user_id == identity.user.id).group_by(Series.id)
                      .order_by(Series.updated_at.desc())).all()
    return [{"id": s.id, "title": s.title, "description": s.description, "language": s.language, "chapters": count}
            for s, count in rows]


class NewSeries(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)
    language: str = "te-IN"


@router.get("/series")
def list_series(identity: Identity = Depends(require("narrator.pipeline")), db: Session = Depends(get_db)):
    return {"items": _series_list(db, identity)}


@router.post("/series", status_code=201)
def create_series(payload: NewSeries, identity: Identity = Depends(require("narrator.upload")),
                  db: Session = Depends(get_db)):
    series = Series(title=payload.title.strip(), description=payload.description.strip() or None,
                    language=normalize_language(payload.language), narrator_user_id=identity.user.id,
                    created_by=identity.username)
    db.add(series)
    db.commit()
    return {"id": series.id, "title": series.title, "description": series.description, "language": series.language,
            "chapters": 0}


# --- Prototype narrator page endpoints (kept until the prototype pages are removed) ---

@router.get("/dashboard")
def dashboard(identity: Identity = Depends(require("narrator.pipeline")), db: Session = Depends(get_db)):
    counts = dict(db.execute(select(AudioAsset.status, func.count())
                             .where(AudioAsset.narrator_user_id == identity.user.id)
                             .group_by(AudioAsset.status)).all())
    credits = db.execute(select(NarratorCredit, AudioAsset).join(AudioAsset)
                         .where(NarratorCredit.narrator_user_id == identity.user.id)
                         .order_by(NarratorCredit.awarded_at.desc()).limit(100)).all()
    profile = db.get(NarratorProfile, identity.user.id)
    published = db.scalars(_own_assets(identity).where(AudioAsset.status == "published")
                           .order_by(AudioAsset.published_at.desc()).limit(100)).all()
    return {
        "counts": counts,
        "credits": len(credits),
        "profile": _profile_payload(profile, identity),
        "creditHistory": [{"assetId": asset.id, "title": asset.title, "versionNumber": asset.version_number,
                           "awardedAt": iso(credit.awarded_at), "reason": credit.reason}
                          for credit, asset in credits],
        "published": [asset_payload(asset) for asset in published],
    }


@router.get("/assets")
def assets(identity: Identity = Depends(require("narrator.pipeline")), db: Session = Depends(get_db)):
    rows = db.scalars(_own_assets(identity).order_by(AudioAsset.updated_at.desc())).all()
    return {"items": [submission_summary(asset) for asset in rows]}


class ProfileUpdate(BaseModel):
    displayName: str = Field(min_length=1, max_length=120)
    biography: str = Field(default="", max_length=4000)
    languages: list[str] | None = None


@router.post("/profile")
def update_profile(payload: ProfileUpdate, identity: Identity = Depends(require("narrator.pipeline")),
                   db: Session = Depends(get_db)):
    profile = db.get(NarratorProfile, identity.user.id) or NarratorProfile(user_id=identity.user.id)
    profile.display_name = payload.displayName.strip()
    profile.biography = payload.biography.strip()
    if payload.languages:
        profile.languages = [normalize_language(language) for language in payload.languages]
    db.add(profile)
    db.commit()
    return {"ok": True}


@router.post("/upload", status_code=201)
async def upload(request: Request, audio: UploadFile = File(...), parentAssetId: str | None = Form(None),
                 identity: Identity = Depends(require("narrator.upload")), db: Session = Depends(get_db)):
    """Single-request upload for small files and the prototype page; the app uses resumable uploads."""
    settings = get_settings()
    filename = safe_filename(audio.filename)
    if PurePosixPath(filename).suffix.lower() not in AUDIO_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"Unsupported audio format. Use one of: {', '.join(sorted(AUDIO_EXTENSIONS))}.")
    digest, size = hashlib.sha256(), 0
    while chunk := await audio.read(1024 * 1024):
        digest.update(chunk)
        size += len(chunk)
        if size > settings.max_upload_bytes:
            raise HTTPException(status_code=413, detail=f"Audio files are limited to {settings.max_upload_bytes // (1024 * 1024)} MB.")
    if not size:
        raise HTTPException(status_code=400, detail="The uploaded audio file is empty.")
    checksum = digest.hexdigest()
    form = await request.form()
    fields = {key: (form.getlist(key) if len(form.getlist(key)) > 1 else form.get(key))
              for key in form.keys() if key != "audio"}
    metadata = clean_metadata(fields, fallback_title=PurePosixPath(filename).stem)
    await audio.seek(0)
    # Database and file work are blocking, so they run in the thread pool, never on the event loop.
    return await run_in_threadpool(_store_upload, db, identity, audio, filename, checksum, size, metadata,
                                   parentAssetId)


def _store_upload(db: Session, identity: Identity, audio: UploadFile, filename: str, checksum: str, size: int,
                  metadata: dict, parentAssetId: str | None) -> dict:
    settings = get_settings()
    asset_id = checksum[:16]
    version, status = 1, "draft"
    if parentAssetId:
        parent = db.get(AudioAsset, parentAssetId)
        if not parent or parent.narrator_user_id != identity.user.id or parent.status != "published":
            raise HTTPException(status_code=409, detail="Only your published audio can receive a replacement upload.")
        version = (db.scalar(select(func.max(AudioAsset.version_number)).where(
            (AudioAsset.id == parentAssetId) | (AudioAsset.parent_asset_id == parentAssetId))) or 1) + 1
        status = "needs-review"

    asset = db.get(AudioAsset, asset_id)
    if asset and asset.narrator_user_id not in (None, identity.user.id):
        raise HTTPException(status_code=409, detail="This exact recording was already submitted by another narrator.")
    key = f"originals/{asset_id}/{filename}"
    get_storage().put_stream(key, audio.file)
    now = utcnow()
    if not asset:
        asset = AudioAsset(id=asset_id, source_key=key, source_filename=filename, checksum_sha256=checksum,
                           title=metadata["title"], narrator_user_id=identity.user.id, submitted_at=now,
                           status=status, parent_asset_id=parentAssetId, version_number=version,
                           language=metadata["language"] or settings.default_language, pipeline_stage="checking")
        db.add(asset)
    apply_metadata(asset, metadata)
    asset.language = metadata["language"] or asset.language or settings.default_language
    asset.metadata_review_status = "not-reviewed"
    db.flush()
    jobs.enqueue(db, "media.process", asset_id=asset_id, created_by=identity.username,
                 idempotency_key=f"media:{asset_id}:{checksum}", priority=jobs.PRIORITY_INTERACTIVE)
    db.add(EditorialEvent(entity_type="audio_asset", entity_id=asset_id, action="content:uploaded",
                          actor=identity.username, notes=f"{filename} ({size} bytes)"))
    db.commit()
    return {"assetId": asset_id, "parentAssetId": parentAssetId, "versionNumber": asset.version_number,
            "status": asset.status, "metadataReviewStatus": "not-reviewed", "filename": filename,
            "metadata": clean_metadata(metadata, metadata["title"])}


class SubmitEdit(BaseModel):
    audioAssetId: str
    notes: str | None = None


@router.post("/submit-edit")
def submit_edit(payload: SubmitEdit, identity: Identity = Depends(require("narrator.upload")),
                db: Session = Depends(get_db)):
    asset = db.get(AudioAsset, payload.audioAssetId)
    if not asset or asset.narrator_user_id != identity.user.id:
        raise HTTPException(status_code=404, detail="Narrator audio asset not found.")
    if asset.status != "published":
        raise HTTPException(status_code=409, detail="Only published audio can receive an edit submission.")
    db.add(EditorialEvent(entity_type="content", entity_id=asset.id, action="content:edit-submitted",
                          actor=identity.username, notes=payload.notes))
    db.commit()
    return {"ok": True}
