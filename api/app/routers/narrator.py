"""Narrator workspace API."""

from __future__ import annotations

import hashlib
import re
from pathlib import PurePosixPath

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload
from starlette.concurrency import run_in_threadpool

from .. import jobs
from ..auth import Identity, require, utcnow
from ..config import get_settings
from ..db import get_db
from ..models import AudioAsset, EditorialEvent, NarratorCredit, NarratorProfile
from ..services.assets import apply_metadata, asset_payload, clean_metadata, iso, normalize_language
from ..storage import get_storage

router = APIRouter(prefix="/api/narrator", tags=["narrator"])

AUDIO_EXTENSIONS = {".mp3", ".m4a", ".aac", ".wav", ".flac", ".ogg", ".opus", ".webm"}


def _own_assets(db: Session, identity: Identity):
    return (select(AudioAsset).where(AudioAsset.narrator_user_id == identity.user.id)
            .options(selectinload(AudioAsset.narrator_user)))


@router.get("/dashboard")
def dashboard(identity: Identity = Depends(require("narrator.pipeline")), db: Session = Depends(get_db)):
    counts = dict(db.execute(select(AudioAsset.status, func.count())
                             .where(AudioAsset.narrator_user_id == identity.user.id)
                             .group_by(AudioAsset.status)).all())
    credits = db.execute(select(NarratorCredit, AudioAsset).join(AudioAsset)
                         .where(NarratorCredit.narrator_user_id == identity.user.id)
                         .order_by(NarratorCredit.awarded_at.desc()).limit(100)).all()
    profile = db.get(NarratorProfile, identity.user.id)
    published = db.scalars(_own_assets(db, identity).where(AudioAsset.status == "published")
                           .order_by(AudioAsset.published_at.desc()).limit(100)).all()
    return {
        "counts": counts,
        "credits": len(credits),
        "profile": {
            "username": identity.username, "displayName": profile.display_name, "biography": profile.biography,
            "language": (profile.languages or ["te-IN"])[0], "languages": profile.languages,
            "updatedAt": iso(profile.updated_at),
        } if profile else None,
        "creditHistory": [{"assetId": asset.id, "title": asset.title, "versionNumber": asset.version_number,
                           "awardedAt": iso(credit.awarded_at), "reason": credit.reason}
                          for credit, asset in credits],
        "published": [asset_payload(asset) for asset in published],
    }


@router.get("/assets")
def assets(identity: Identity = Depends(require("narrator.pipeline")), db: Session = Depends(get_db)):
    rows = db.scalars(_own_assets(db, identity).order_by(AudioAsset.updated_at.desc())).all()
    return {"items": [asset_payload(asset) for asset in rows]}


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


def _safe_filename(name: str | None) -> str:
    stem = PurePosixPath((name or "narration.mp3").replace("\\", "/")).name
    stem = re.sub(r"[^\w.\- ]+", "_", stem, flags=re.UNICODE).strip() or "narration.mp3"
    return stem[:120]


@router.post("/upload", status_code=201)
async def upload(request: Request, audio: UploadFile = File(...), parentAssetId: str | None = Form(None),
                 identity: Identity = Depends(require("narrator.upload")), db: Session = Depends(get_db)):
    settings = get_settings()
    filename = _safe_filename(audio.filename)
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
                           language=metadata["language"] or settings.default_language)
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
