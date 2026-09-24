"""Editorial workspace API: queues, review decisions, rights, processing, publishing."""

from __future__ import annotations

from datetime import date
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session, selectinload

from .. import jobs
from ..auth import Identity, require, require_identity, utcnow
from ..db import get_db
from ..models import (
    AssetRights, AudioAsset, EditorialEvent, Job, NarratorCredit, TeaserDraft, Transcript,
)
from ..services.assets import (
    apply_metadata, asset_payload, clean_metadata, iso, missing_publication_metadata,
)
from ..services.notify import notify
from ..storage import get_storage

router = APIRouter(prefix="/api", tags=["editorial"])

RIGHTS_FLAGS = ("recordingRights", "performanceRights", "adaptationRights", "artworkRights", "musicRights")
RIGHTS_COLUMNS = {"recordingRights": "recording_rights", "performanceRights": "performance_rights",
                  "adaptationRights": "adaptation_rights", "artworkRights": "artwork_rights",
                  "musicRights": "music_rights"}


def _event(db: Session, entity_type: str, entity_id: str, action: str, actor: str, notes: str | None = None):
    db.add(EditorialEvent(entity_type=entity_type, entity_id=str(entity_id), action=action, actor=actor, notes=notes))


def _asset_or_404(db: Session, asset_id: str) -> AudioAsset:
    asset = db.scalars(select(AudioAsset).where(AudioAsset.id == asset_id)
                       .options(selectinload(AudioAsset.narrator_user))).first()
    if not asset:
        raise HTTPException(status_code=404, detail=f"Audio asset {asset_id!r} not found.")
    return asset


@router.get("/dashboard")
def dashboard(identity: Identity = Depends(require("transcript.review")), db: Session = Depends(get_db)):
    transcripts = dict(db.execute(select(Transcript.status, func.count()).group_by(Transcript.status)).all())
    teasers = dict(db.execute(select(TeaserDraft.status, func.count()).group_by(TeaserDraft.status)).all())
    assets = db.scalar(select(func.count()).select_from(AudioAsset))
    media = dict(db.execute(select(AudioAsset.media_status, func.count()).group_by(AudioAsset.media_status)).all())
    job_counts = dict(db.execute(select(Job.status, func.count()).group_by(Job.status)).all())
    return {"assets": assets, "transcripts": transcripts, "teasers": teasers, "media": media, "jobs": job_counts}


QUEUE_PERMISSION = {"teasers": "teaser.review", "narrator-submissions": "content.publish",
                    "published": "metadata.review", "catalog": "metadata.review"}


@router.get("/queue")
def queue(queue: str = "transcripts", q: str | None = None, identity: Identity = Depends(require_identity),
          db: Session = Depends(get_db)):
    permission = QUEUE_PERMISSION.get(queue, "transcript.review")
    if permission not in identity.permissions:
        raise HTTPException(status_code=403, detail="Insufficient permission.")
    if queue == "teasers":
        rows = db.execute(select(TeaserDraft, AudioAsset, Transcript.text)
                          .join(AudioAsset, AudioAsset.id == TeaserDraft.audio_asset_id)
                          .outerjoin(Transcript, Transcript.id == TeaserDraft.transcript_id)
                          .order_by(TeaserDraft.id.desc()).limit(100)).all()
        items = [{"id": teaser.id, "assetId": asset.id, "status": teaser.status, "language": teaser.language,
                  "shortText": teaser.short_text, "longText": teaser.long_text, "title": asset.title,
                  "album": asset.album, "transcript": text} for teaser, asset, text in rows]
    elif queue in {"narrator-submissions", "published", "catalog"}:
        query = select(AudioAsset).options(selectinload(AudioAsset.narrator_user))
        if queue == "narrator-submissions":
            query = query.where(AudioAsset.narrator_user_id.is_not(None),
                                AudioAsset.status.in_(("draft", "needs-review", "rejected")))
        elif queue == "published":
            query = query.where(AudioAsset.status == "published")
        else:  # the seed catalog that is not yet published
            query = query.where(AudioAsset.narrator_user_id.is_(None), AudioAsset.status != "published")
        if q:
            like = f"%{q.strip()}%"
            query = query.where(AudioAsset.title.ilike(like) | AudioAsset.album.ilike(like))
        order = AudioAsset.published_at.desc().nulls_last() if queue == "published" else AudioAsset.updated_at.desc()
        items = [asset_payload(asset) for asset in db.scalars(query.order_by(order).limit(100))]
    else:
        rows = db.execute(select(Transcript, AudioAsset).join(AudioAsset, AudioAsset.id == Transcript.audio_asset_id)
                          .order_by(Transcript.id.desc()).limit(100)).all()
        items = [{"id": transcript.id, "assetId": asset.id, "version": transcript.version,
                  "status": transcript.status, "language": transcript.language, "text": transcript.text,
                  "title": asset.title, "album": asset.album, "duration": asset.duration_seconds}
                 for transcript, asset in rows]
    return {"queue": queue, "items": items}


def _job_payload(job: Job) -> dict[str, Any]:
    return {"id": job.id, "jobType": "media" if job.job_type == "media.process" else job.job_type,
            "status": jobs.LEGACY_STATUS.get(job.status, job.status), "queueStatus": job.status,
            "attempts": job.attempts, "maxAttempts": job.max_attempts, "error": job.error,
            "logTail": job.log_tail, "leasedBy": job.leased_by, "updatedAt": iso(job.updated_at),
            "runAfter": iso(job.run_after)}


def _rights_payload(rights: AssetRights | None) -> dict[str, Any]:
    if not rights:
        return {"status": "not-configured", "message": "Configure the rights checklist before publishing."}
    return {
        "status": rights.status, "sourceType": rights.source_type, "rightsHolder": rights.rights_holder,
        **{flag: getattr(rights, column) for flag, column in RIGHTS_COLUMNS.items()},
        "territory": rights.territory, "allowedUses": rights.allowed_uses,
        "licenseStart": rights.license_start.isoformat() if rights.license_start else None,
        "licenseEnd": rights.license_end.isoformat() if rights.license_end else None,
        "evidenceReference": rights.evidence_reference, "attestedBy": rights.attested_by,
        "attestedAt": iso(rights.attested_at), "reviewer": rights.reviewer, "reviewNotes": rights.review_notes,
        "updatedAt": iso(rights.updated_at),
        "message": "Rights are approved." if rights.status == "approved" else "Rights need review before publishing.",
    }


@router.get("/narrator/asset")
def asset_detail(id: str, identity: Identity = Depends(require("content.publish")), db: Session = Depends(get_db)):
    asset = _asset_or_404(db, id)
    transcript = db.scalars(select(Transcript).where(Transcript.audio_asset_id == id)
                            .order_by(Transcript.version.desc())).first()
    teaser = db.scalars(select(TeaserDraft).where(TeaserDraft.audio_asset_id == id)
                        .order_by(TeaserDraft.id.desc())).first()
    job_rows = db.scalars(select(Job).where(Job.audio_asset_id == id).order_by(Job.id.desc()).limit(30)).all()
    history = db.scalars(select(EditorialEvent).where(EditorialEvent.entity_id == id)
                         .order_by(EditorialEvent.id.desc()).limit(30)).all()
    return {
        "asset": asset_payload(asset, include_original=True),
        "transcript": {"id": transcript.id, "version": transcript.version, "status": transcript.status,
                       "language": transcript.language, "text": transcript.text, "reviewer": transcript.reviewer,
                       "reviewedAt": iso(transcript.reviewed_at), "provider": transcript.provider,
                       "model": transcript.model} if transcript else None,
        "teaser": {"id": teaser.id, "status": teaser.status, "language": teaser.language,
                   "shortText": teaser.short_text, "longText": teaser.long_text, "alternates": teaser.alternates,
                   "themes": teaser.themes, "ageSuggestion": teaser.age_suggestion, "warnings": teaser.warnings,
                   "model": teaser.model, "reviewer": teaser.reviewer,
                   "createdAt": iso(teaser.created_at)} if teaser else None,
        "jobs": [_job_payload(job) for job in job_rows],
        "rights": _rights_payload(db.get(AssetRights, id)),
        "history": [{"action": event.action, "actor": event.actor, "notes": event.notes,
                     "createdAt": iso(event.created_at)} for event in history],
    }


class MetadataUpdate(BaseModel):
    model_config = {"extra": "allow"}
    audioAssetId: str
    metadataReviewStatus: Literal["not-reviewed", "needs-changes", "approved"] | None = None
    reviewState: Literal["not-reviewed", "needs-changes", "approved"] | None = None
    notes: str | None = None


def _update_metadata(payload: MetadataUpdate, identity: Identity, db: Session, *, review: bool):
    editor = "metadata.review" in identity.permissions
    if review and not editor:
        raise HTTPException(status_code=403, detail="Metadata review permission required.")
    if not editor and "narrator.upload" not in identity.permissions:
        raise HTTPException(status_code=403, detail="Metadata editing permission required.")
    asset = _asset_or_404(db, payload.audioAssetId)
    if not editor and asset.narrator_user_id != identity.user.id:
        raise HTTPException(status_code=404, detail="Audio asset not found.")
    status = (payload.metadataReviewStatus or payload.reviewState or "not-reviewed") if editor else "not-reviewed"
    metadata = clean_metadata(payload.model_extra or {}, fallback_title=asset.title)
    apply_metadata(asset, metadata)
    asset.metadata_review_status = status
    default_notes = "Published audio metadata updated." if asset.status == "published" else "Audio asset metadata updated."
    _event(db, "audio_asset", asset.id, f"metadata:{status}", identity.username, payload.notes or default_notes)
    db.commit()
    return {"ok": True, "assetId": asset.id, "metadata": metadata, "metadataReviewStatus": status}


@router.post("/narrator/metadata")
def update_metadata(payload: MetadataUpdate, identity: Identity = Depends(require_identity),
                    db: Session = Depends(get_db)):
    return _update_metadata(payload, identity, db, review=False)


@router.post("/narrator/metadata-review")
def review_metadata(payload: MetadataUpdate, identity: Identity = Depends(require_identity),
                    db: Session = Depends(get_db)):
    return _update_metadata(payload, identity, db, review=True)


class ProcessRequest(BaseModel):
    assetId: str = ""
    action: str = ""


PROCESS_ACTIONS = ("transcription", "teaser", "artwork", "media")


@router.post("/narrator/process", status_code=202)
def process(payload: ProcessRequest, identity: Identity = Depends(require("content.publish")),
            db: Session = Depends(get_db)):
    if not payload.assetId:
        raise HTTPException(status_code=400, detail={"error": "Processing request is missing assetId.",
                                                     "received": payload.model_dump()})
    if payload.action not in PROCESS_ACTIONS:
        raise HTTPException(status_code=400, detail={
            "error": f"Unsupported processing action {payload.action!r}. Supported: {', '.join(PROCESS_ACTIONS)}.",
            "received": payload.model_dump()})
    asset = _asset_or_404(db, payload.assetId)
    job_type = "media.process" if payload.action == "media" else payload.action
    running = jobs.active_job(db, asset.id, job_type)
    if running:
        raise HTTPException(status_code=409, detail={
            "error": f"{payload.action.capitalize()} is already {jobs.LEGACY_STATUS[running.status]} for this story.",
            "job": _job_payload(running)})
    job_payload: dict[str, Any] = {}
    if job_type == "transcription":
        latest = db.scalars(select(Transcript).where(Transcript.audio_asset_id == asset.id)
                            .order_by(Transcript.version.desc())).first()
        if latest and latest.status in {"needs-review", "approved"}:
            raise HTTPException(status_code=409, detail="A transcript already exists for this audio.")
        job_payload = {"language": asset.language}
    elif job_type == "teaser":
        transcript = db.scalars(select(Transcript).where(Transcript.audio_asset_id == asset.id,
                                                         Transcript.status == "approved")
                                .order_by(Transcript.version.desc())).first()
        if not transcript:
            raise HTTPException(status_code=409, detail="Approve the transcript before generating a teaser.")
        teaser = db.scalars(select(TeaserDraft).where(TeaserDraft.audio_asset_id == asset.id)
                            .order_by(TeaserDraft.id.desc())).first()
        if teaser and teaser.status in {"needs-review", "approved"}:
            raise HTTPException(status_code=409, detail="A teaser draft already exists for this audio.")
        job_payload = {"transcriptId": transcript.id}
    job = jobs.enqueue(db, job_type, asset_id=asset.id, payload=job_payload, created_by=identity.username,
                       priority=jobs.PRIORITY_INTERACTIVE)
    _event(db, "audio_asset", asset.id, f"process:{payload.action}", identity.username, f"job {job.id}")
    db.commit()
    return {"assetId": asset.id, "action": payload.action, "status": "queued", "job": _job_payload(job)}


class RightsUpdate(BaseModel):
    audioAssetId: str
    status: Literal["needs-review", "approved", "rejected"] = "needs-review"
    sourceType: str | None = None
    rightsHolder: str | None = None
    recordingRights: bool = False
    performanceRights: bool = False
    adaptationRights: bool = False
    artworkRights: bool = False
    musicRights: bool = False
    territory: str | None = None
    allowedUses: str | None = None
    licenseStart: date | None = None
    licenseEnd: date | None = None
    evidenceReference: str | None = None
    reviewNotes: str | None = None

    @field_validator("licenseStart", "licenseEnd", "sourceType", "rightsHolder", "territory", "allowedUses",
                     "evidenceReference", "reviewNotes", mode="before")
    @classmethod
    def _blank_is_none(cls, value):
        return None if isinstance(value, str) and not value.strip() else value


@router.post("/narrator/rights")
def update_rights(payload: RightsUpdate, identity: Identity = Depends(require("rights.manage")),
                  db: Session = Depends(get_db)):
    asset = _asset_or_404(db, payload.audioAssetId)
    rights = db.get(AssetRights, asset.id) or AssetRights(audio_asset_id=asset.id)
    rights.status = payload.status
    rights.source_type = payload.sourceType or rights.source_type
    rights.rights_holder = payload.rightsHolder
    for flag, column in RIGHTS_COLUMNS.items():
        setattr(rights, column, getattr(payload, flag))
    rights.territory, rights.allowed_uses = payload.territory, payload.allowedUses
    rights.license_start, rights.license_end = payload.licenseStart, payload.licenseEnd
    rights.evidence_reference, rights.review_notes = payload.evidenceReference, payload.reviewNotes
    rights.reviewer = identity.username
    db.add(rights)
    _event(db, "rights", asset.id, f"rights:{payload.status}", identity.username, payload.reviewNotes)
    db.commit()
    return {"ok": True, "status": payload.status}


class OwnedRights(BaseModel):
    audioAssetId: str
    notes: str | None = None


@router.post("/narrator/rights/owned")
def mark_kathachepta_owned(payload: OwnedRights, identity: Identity = Depends(require("rights.manage")),
                           db: Session = Depends(get_db)):
    """One click for stories KathaChepta owns outright: every right granted, worldwide, no expiry."""
    asset = _asset_or_404(db, payload.audioAssetId)
    rights = grant_owned_rights(db, asset, identity.username, payload.notes)
    db.commit()
    return {"ok": True, "rights": _rights_payload(rights)}


def grant_owned_rights(db: Session, asset: AudioAsset, actor: str, notes: str | None = None) -> AssetRights:
    rights = db.get(AssetRights, asset.id) or AssetRights(audio_asset_id=asset.id)
    now = utcnow()
    attestation = f"KathaChepta-owned; confirmed by {actor} on {now:%Y-%m-%d}."
    rights.status, rights.source_type, rights.rights_holder = "approved", "kathachepta-owned", "KathaChepta"
    for column in RIGHTS_COLUMNS.values():
        setattr(rights, column, True)
    rights.territory, rights.allowed_uses = "Worldwide", "streaming, download, preview, translation"
    rights.license_start = rights.license_end = None
    rights.evidence_reference, rights.attested_by, rights.attested_at = attestation, actor, now
    rights.reviewer, rights.review_notes = actor, notes or attestation
    db.add(rights)
    _event(db, "rights", asset.id, "rights:kathachepta-owned", actor, notes)
    return rights


def accept_narrator_attestation(db: Session, asset: AudioAsset, actor: str, notes: str | None = None) -> AssetRights:
    """The editor accepts what the narrator attested at submission (their voice, a text they may narrate)."""
    rights = db.get(AssetRights, asset.id)
    if not rights or not rights.attestation:
        raise HTTPException(status_code=409, detail="The narrator hasn't said where this story comes from.")
    claim = rights.attestation
    rights.status = "approved"
    for column in RIGHTS_COLUMNS.values():
        setattr(rights, column, True)  # narration, performance by the narrator; artwork is made by KathaChepta
    rights.rights_holder = rights.rights_holder or (
        "KathaChepta" if claim.get("sourceType") == "kathachepta-owned" else asset.narrator_user.handle
        if asset.narrator_user else None)
    rights.territory = rights.territory or "Worldwide"
    rights.allowed_uses = rights.allowed_uses or "streaming, download, preview"
    rights.evidence_reference = claim.get("sourceReference") or rights.evidence_reference
    rights.reviewer, rights.review_notes = actor, notes or f"Narrator attestation ({claim.get('sourceType')}) accepted."
    db.add(rights)
    _event(db, "rights", asset.id, "rights:attestation-accepted", actor, notes)
    return rights


class ContentEdit(BaseModel):
    type: Literal["transcript", "teaser"]
    id: int
    text: str = Field(min_length=1)


@router.post("/narrator/content-edit")
def content_edit(payload: ContentEdit, identity: Identity = Depends(require_identity), db: Session = Depends(get_db)):
    needed = "transcript.review" if payload.type == "transcript" else "teaser.review"
    if needed not in identity.permissions:
        raise HTTPException(status_code=403, detail="Insufficient permission.")
    text = payload.text.strip()
    if payload.type == "transcript":
        transcript = db.get(Transcript, payload.id)
        if not transcript:
            raise HTTPException(status_code=404, detail="Transcript not found.")
        transcript.text, transcript.status = text, "needs-review"
        transcript.reviewer, transcript.reviewed_at = None, None
        transcript.review_notes = "Edited content requires re-review."
        db.execute(update(TeaserDraft).where(TeaserDraft.audio_asset_id == transcript.audio_asset_id,
                                             TeaserDraft.status == "approved")
                   .values(status="needs-review", review_notes="Transcript changed; teaser requires re-review."))
    else:
        teaser = db.get(TeaserDraft, payload.id)
        if not teaser:
            raise HTTPException(status_code=404, detail="Teaser draft not found.")
        teaser.long_text, teaser.status = text, "needs-review"
        teaser.reviewer, teaser.review_notes = None, "Edited content requires re-review."
    _event(db, payload.type, str(payload.id), f"{payload.type}:edited", identity.username,
           "Content edited; re-review required.")
    db.commit()
    return {"ok": True, "status": "needs-review"}


class DeleteRequest(BaseModel):
    audioAssetId: str
    notes: str | None = None


@router.post("/narrator/delete")
def delete_submission(payload: DeleteRequest, identity: Identity = Depends(require("content.publish")),
                      db: Session = Depends(get_db)):
    asset = _asset_or_404(db, payload.audioAssetId)
    if asset.narrator_user_id is None:
        raise HTTPException(status_code=409, detail="Only narrator submissions can be deleted; archive catalog stories instead.")
    if asset.status in {"published", "archived"}:
        raise HTTPException(status_code=409, detail="Published or archived audio cannot be deleted.")
    keys = [asset.source_key, asset.artwork_key,
            *[(value or {}).get("key") for value in (asset.renditions or {}).values() if isinstance(value, dict)]]
    jobs.cancel_active(db, asset.id)
    db.delete(asset)
    _event(db, "narrator_asset", asset.id, "content:deleted", identity.username, payload.notes)
    db.commit()
    storage = get_storage()
    for key in filter(None, keys):
        if not key.startswith("legacy/"):
            storage.delete(key)
    return {"ok": True, "assetId": asset.id}


class AssetDecision(BaseModel):
    audioAssetId: str
    decision: str | None = None
    notes: str | None = None


def publish_readiness(db: Session, asset: AudioAsset) -> list[str]:
    problems = []
    if asset.media_status != "ready":
        problems.append("Audio processing hasn't finished" if asset.media_status == "pending"
                        else "Audio processing failed; reprocess the audio")
    missing = missing_publication_metadata(asset)
    if missing:
        problems.append(f"Missing metadata: {', '.join(missing)}")
    if asset.metadata_review_status != "approved":
        problems.append("Metadata is not approved")
    if not db.scalar(select(Transcript.id).where(Transcript.audio_asset_id == asset.id,
                                                 Transcript.status.in_(("approved", "accepted"))).limit(1)):
        problems.append("No approved transcript")
    if not db.scalar(select(TeaserDraft.id).where(TeaserDraft.audio_asset_id == asset.id,
                                                  TeaserDraft.status == "approved").limit(1)):
        problems.append("No approved teaser")
    rights = db.get(AssetRights, asset.id)
    if not rights or rights.status != "approved" or not all(getattr(rights, c) for c in RIGHTS_COLUMNS.values()):
        problems.append("Rights are not fully approved")
    elif rights.license_end and rights.license_end < utcnow().date():
        problems.append("Rights license has expired")
    return problems


@router.post("/content/publish")
def publish(payload: AssetDecision, identity: Identity = Depends(require("content.publish")),
            db: Session = Depends(get_db)):
    asset = _asset_or_404(db, payload.audioAssetId)
    missing = missing_publication_metadata(asset)
    if missing:
        raise HTTPException(status_code=409, detail={"error": "Required narrator metadata is missing.",
                                                     "missingMetadata": missing})
    problems = publish_readiness(db, asset)
    if problems:
        raise HTTPException(status_code=409, detail={"error": "Not ready to publish: " + "; ".join(problems) + ".",
                                                     "problems": problems})
    mark_published(db, asset, identity.username, payload.notes)
    db.commit()
    return {"ok": True, "status": "published"}


def mark_published(db: Session, asset: AudioAsset, actor: str, notes: str | None = None) -> None:
    now = utcnow()
    asset.status, asset.published_at, asset.review_required = "published", now, False
    asset.pipeline_stage, asset.pipeline_error = "published", None
    if asset.parent_asset_id:
        db.execute(update(AudioAsset).where(AudioAsset.id == asset.parent_asset_id, AudioAsset.status == "published")
                   .values(status="archived"))
    if asset.narrator_user_id and not db.scalar(select(NarratorCredit.id).where(NarratorCredit.audio_asset_id == asset.id)):
        db.add(NarratorCredit(narrator_user_id=asset.narrator_user_id, audio_asset_id=asset.id))
    _event(db, "content", asset.id, "content:published", actor, notes)
    notify(db, asset.narrator_user_id, "published", f"“{asset.title}” is published",
           "Families can listen to it now. Thank you for narrating!", asset.id)


@router.post("/narrator/review")
def reject(payload: AssetDecision, identity: Identity = Depends(require("content.publish")),
           db: Session = Depends(get_db)):
    if payload.decision != "rejected":
        raise HTTPException(status_code=400, detail="Submissions can be rejected here, or published after readiness checks.")
    asset = _asset_or_404(db, payload.audioAssetId)
    asset.status = "rejected"
    _event(db, "content", asset.id, "content:rejected", identity.username, payload.notes)
    db.commit()
    return {"ok": True, "status": "rejected"}


class ReviewDecision(BaseModel):
    id: int
    decision: Literal["approved", "rejected", "needs-review"]
    notes: str | None = None


@router.post("/transcript/review")
def review_transcript(payload: ReviewDecision, identity: Identity = Depends(require("transcript.review")),
                      db: Session = Depends(get_db)):
    transcript = db.get(Transcript, payload.id)
    if not transcript:
        raise HTTPException(status_code=404, detail="Transcript not found.")
    transcript.status, transcript.reviewer = payload.decision, identity.username
    transcript.review_notes, transcript.reviewed_at = payload.notes, utcnow()
    _event(db, "transcript", str(payload.id), f"transcript:{payload.decision}", identity.username, payload.notes)
    db.commit()
    return {"ok": True, "status": payload.decision}


@router.post("/teaser/review")
def review_teaser(payload: ReviewDecision, identity: Identity = Depends(require("teaser.review")),
                  db: Session = Depends(get_db)):
    teaser = db.get(TeaserDraft, payload.id)
    if not teaser:
        raise HTTPException(status_code=404, detail="Teaser draft not found.")
    teaser.status, teaser.reviewer, teaser.review_notes = payload.decision, identity.username, payload.notes
    _event(db, "teaser", str(payload.id), f"teaser:{payload.decision}", identity.username, payload.notes)
    db.commit()
    return {"ok": True, "status": payload.decision}

