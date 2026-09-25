"""Editor and admin studio API (P2-08, P2-10, P2-12, P2-14).

One consolidated review per story: the editor edits the AI drafts in place and publishes with one
action that approves metadata, teaser, transcript, and rights together, or asks for changes with
templated reasons. Nothing is published without an editor's action.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from .. import jobs
from ..auth import Identity, audit, require, require_identity, utcnow
from ..db import get_db
from ..models import (
    AssetRights, AudioAsset, EditorialEvent, Job, NarratorProfile, Notification, TeaserDraft, Transcript, User, Worker,
)
from ..services import pipeline, policy
from ..services import settings as app_settings
from ..services.assets import apply_metadata, asset_payload, clean_metadata, iso, mastering_payload, metadata_of
from ..services.notify import notify
from ..storage import media_url
from .editorial import (
    _job_payload, _rights_payload, accept_narrator_attestation, grant_owned_rights, mark_published, publish_readiness,
)

router = APIRouter(prefix="/api/studio", tags=["studio"])
me_router = APIRouter(prefix="/api/notifications", tags=["notifications"])

VIEWS = {
    "review": ("ready",),
    "attention": ("failed", "needs-fix"),
    "transcription": ("waiting-transcript",),  # catalog stories waiting for an admin to allow paid transcription
    "waiting": ("changes-requested", "awaiting-submit"),
    "pipeline": ("checking", "transcribing", "drafting", "illustrating"),
}


def _asset(db: Session, asset_id: str) -> AudioAsset:
    asset = db.scalars(select(AudioAsset).where(AudioAsset.id == asset_id)
                       .options(selectinload(AudioAsset.narrator_user), selectinload(AudioAsset.series))).first()
    if not asset:
        raise HTTPException(status_code=404, detail="Story not found.")
    return asset


def _event(db: Session, asset_id: str, action: str, actor: str, notes: str | None = None) -> None:
    db.add(EditorialEvent(entity_type="audio_asset", entity_id=asset_id, action=action, actor=actor, notes=notes))


def _trust(db: Session, user_ids: set[int]) -> dict[int, str]:
    if not user_ids:
        return {}
    return dict(db.execute(select(NarratorProfile.user_id, NarratorProfile.trust_level)
                           .where(NarratorProfile.user_id.in_(user_ids))).all())


def _latest_by_asset(db: Session, model, asset_ids: list[str], statuses: tuple[str, ...]) -> dict[str, Any]:
    if not asset_ids:
        return {}
    rows = db.scalars(select(model).where(model.audio_asset_id.in_(asset_ids), model.status.in_(statuses))
                      .order_by(model.id)).all()
    return {row.audio_asset_id: row for row in rows}  # later ids overwrite earlier ones


def bulk_blockers(db: Session, asset: AudioAsset, trust: str | None, draft: TeaserDraft | None,
                  transcript: Transcript | None) -> list[str]:
    """Why a story can't be published in bulk (without opening it). Empty means eligible."""
    problems = []
    if asset.pipeline_stage != "ready":
        problems.append("not ready for review")
    if asset.narrator_user_id and trust != "trusted":
        problems.append("narrator isn't trusted yet")
    if not draft:
        problems.append("no AI drafts")
    elif (draft.safety or {}).get("rating") != "all-ages" or any(
            f.get("severity") == "high" for f in (draft.safety or {}).get("flags", [])):
        problems.append("safety check needs a person")
    if pipeline.transcript_review_required(db, asset, transcript):
        problems.append("transcript needs reading")
    if (asset.qc or {}).get("verdict") == "fail":
        problems.append("sound check failed")
    return problems


@router.get("/queue")
def queue(view: str = "review", q: str | None = None, language: str | None = None,
          identity: Identity = Depends(require("content.publish")), db: Session = Depends(get_db)):
    query = select(AudioAsset).options(selectinload(AudioAsset.narrator_user), selectinload(AudioAsset.series))
    if view in VIEWS:
        query = query.where(AudioAsset.pipeline_stage.in_(VIEWS[view]))
        order = [AudioAsset.ready_for_review_at.asc().nulls_last(), AudioAsset.updated_at.asc()]
    elif view == "published":
        query, order = query.where(AudioAsset.status == "published"), [AudioAsset.published_at.desc().nulls_last()]
    elif view == "catalog":  # seed catalog stories not yet in the pipeline
        query = query.where(AudioAsset.narrator_user_id.is_(None), AudioAsset.pipeline_stage == "none",
                            AudioAsset.status != "published")
        order = [AudioAsset.title]
    else:
        raise HTTPException(status_code=400, detail=f"Unknown view {view!r}.")
    if q:
        like = f"%{q.strip()}%"
        query = query.where(or_(AudioAsset.title.ilike(like), AudioAsset.album.ilike(like), AudioAsset.id == q.strip()))
    if language:
        query = query.where(AudioAsset.language == language)
    assets = db.scalars(query.order_by(*order).limit(300)).all()
    ids = [a.id for a in assets]
    drafts = _latest_by_asset(db, TeaserDraft, ids, ("needs-review", "approved"))
    transcripts = _latest_by_asset(db, Transcript, ids, pipeline.USABLE)
    trust = _trust(db, {a.narrator_user_id for a in assets if a.narrator_user_id})
    sla = float(app_settings.get(db, "review.slaHours"))
    now = utcnow()
    items = []
    for asset in assets:
        draft, transcript = drafts.get(asset.id), transcripts.get(asset.id)
        waiting = (now - asset.ready_for_review_at).total_seconds() / 3600 if asset.ready_for_review_at else None
        blockers = bulk_blockers(db, asset, trust.get(asset.narrator_user_id), draft, transcript)
        items.append({
            "id": asset.id, "title": asset.title, "narrator": asset_payload(asset)["narrator"],
            "language": asset.language, "duration": asset.duration_seconds, "status": asset.status,
            "stage": asset.pipeline_stage, "stageLabel": pipeline.STAGES.get(asset.pipeline_stage),
            "pipelineError": asset.pipeline_error, "isSubmission": asset.narrator_user_id is not None,
            "trustLevel": trust.get(asset.narrator_user_id), "readyForReviewAt": iso(asset.ready_for_review_at),
            "waitingHours": round(waiting, 1) if waiting is not None else None,
            "overdue": waiting is not None and waiting > sla, "qcVerdict": (asset.qc or {}).get("verdict"),
            "safetyRating": (draft.safety or {}).get("rating") if draft else None,
            "teaser": draft.short_text if draft else None, "hasTranscript": transcript is not None,
            "transcriptReviewRequired": pipeline.transcript_review_required(db, asset, transcript),
            "artworkUrl": asset_payload(asset)["artworkUrl"], "series": asset.series.title if asset.series else None,
            "bulkEligible": not blockers, "bulkBlockers": blockers, "publishedAt": iso(asset.published_at),
        })
    if view in VIEWS:  # trusted narrators get expedited review: their stories go first
        items.sort(key=lambda item: (item["trustLevel"] != "trusted", -(item["waitingHours"] or 0)))
    counts = dict(db.execute(select(AudioAsset.pipeline_stage, func.count()).group_by(AudioAsset.pipeline_stage)).all())
    tabs = {name: sum(counts.get(stage, 0) for stage in stages) for name, stages in VIEWS.items()}
    tabs["catalog"] = db.scalar(select(func.count()).select_from(AudioAsset).where(
        AudioAsset.narrator_user_id.is_(None), AudioAsset.pipeline_stage == "none", AudioAsset.status != "published"))
    tabs["published"] = db.scalar(select(func.count()).select_from(AudioAsset).where(AudioAsset.status == "published"))
    return {"view": view, "items": items, "counts": tabs, "slaHours": sla}


def _contact(user: User | None) -> dict[str, Any]:
    """How editors reach a narrator about a submission (staff only)."""
    if not user:
        return {}
    preferences = user.contact_preferences or {}
    return {"email": user.email, "phone": user.phone, "contactChannel": preferences.get("channel") or "email",
            "contactNotes": preferences.get("notes") or ""}


def review_payload(db: Session, asset: AudioAsset) -> dict[str, Any]:
    transcript = pipeline.latest_transcript(db, asset.id)
    if transcript:
        pipeline.prepare_transcript(db, transcript, asset)
    draft = pipeline.latest_draft(db, asset.id)
    rights = db.get(AssetRights, asset.id)
    profile = db.get(NarratorProfile, asset.narrator_user_id) if asset.narrator_user_id else None
    narrator_stats = None
    if asset.narrator_user_id:
        counts = dict(db.execute(select(AudioAsset.status, func.count())
                                 .where(AudioAsset.narrator_user_id == asset.narrator_user_id)
                                 .group_by(AudioAsset.status)).all())
        narrator_stats = {"published": counts.get("published", 0), "rejected": counts.get("rejected", 0),
                          "changesRequested": db.scalar(select(func.count()).select_from(EditorialEvent).where(
                              EditorialEvent.action == "content:changes-requested",
                              EditorialEvent.entity_id.in_(select(AudioAsset.id).where(
                                  AudioAsset.narrator_user_id == asset.narrator_user_id))))}
    job_rows = db.scalars(select(Job).where(Job.audio_asset_id == asset.id).order_by(Job.id.desc()).limit(20)).all()
    history = db.scalars(select(EditorialEvent).where(EditorialEvent.entity_id == asset.id)
                         .order_by(EditorialEvent.id.desc()).limit(40)).all()
    sla = float(app_settings.get(db, "review.slaHours"))
    waiting = (utcnow() - asset.ready_for_review_at).total_seconds() / 3600 if asset.ready_for_review_at else None
    return {
        "asset": asset_payload(asset, include_original=True), "stage": asset.pipeline_stage,
        "stageLabel": pipeline.STAGES.get(asset.pipeline_stage), "pipelineError": asset.pipeline_error,
        "waveform": (asset.renditions or {}).get("waveform", []), "qc": asset.qc or {},
        "mastering": mastering_payload(asset),
        "waitingHours": round(waiting, 1) if waiting is not None else None,
        "overdue": waiting is not None and waiting > sla, "captionsEnabled": asset.captions_enabled,
        "changesRequested": asset.changes_requested or None, "sourceText": asset.source_text,
        "series": {"id": asset.series.id, "title": asset.series.title, "position": asset.series_position}
        if asset.series else None,
        "narrator": {"userId": asset.narrator_user_id, "name": asset_payload(asset)["narrator"],
                     **_contact(asset.narrator_user),
                     "trustLevel": profile.trust_level if profile else None,
                     "sampleUrl": media_url(profile.sample_key) if profile else None, **(narrator_stats or {})}
        if asset.narrator_user_id else None,
        "transcript": {"id": transcript.id, "version": transcript.version, "status": transcript.status,
                       "language": transcript.language, "text": transcript.text, "introRemoved": transcript.intro_removed,
                       "confidence": transcript.confidence, "quality": transcript.quality,
                       "reviewRequired": pipeline.transcript_review_required(db, asset, transcript),
                       "provider": transcript.provider, "model": transcript.model} if transcript else None,
        "draft": {"id": draft.id, "status": draft.status, "language": draft.language, "shortText": draft.short_text,
                  "longText": draft.long_text, "alternates": draft.alternates, "themes": draft.themes,
                  "mood": draft.mood, "ageSuggestion": draft.age_suggestion, "warnings": draft.warnings,
                  "safety": draft.safety, "suggestions": draft.suggestions, "model": draft.model,
                  "promptVersion": draft.prompt_version, "createdAt": iso(draft.created_at)} if draft else None,
        "rights": {**_rights_payload(rights), "attestation": rights.attestation if rights else {},
                   "evidenceUrl": media_url(rights.evidence_key) if rights else None},
        "policy": {"checklist": policy.REVIEW_CHECKLIST, "changeReasons": policy.CHANGE_REASONS,
                   "ageRubric": policy.AGE_RUBRIC, "safetyCategories": policy.SAFETY_CATEGORIES},
        "readiness": publish_readiness(db, asset),
        "jobs": [_job_payload(job) for job in job_rows],
        "history": [{"action": e.action, "actor": e.actor, "notes": e.notes, "createdAt": iso(e.created_at)}
                    for e in history],
    }


@router.get("/review/{asset_id}")
def review(asset_id: str, identity: Identity = Depends(require("content.publish")), db: Session = Depends(get_db)):
    payload = review_payload(db, _asset(db, asset_id))
    db.commit()  # prepare_transcript may have cleaned the transcript once
    return payload


class TeaserText(BaseModel):
    short: str = Field(default="", max_length=400)
    long: str = Field(default="", max_length=2000)


class TranscriptDecision(BaseModel):
    text: str | None = Field(default=None, max_length=500_000)
    reviewed: bool = False


class PublishRequest(BaseModel):
    metadata: dict[str, Any] = Field(default_factory=dict)
    teaser: dict[str, TeaserText] = Field(default_factory=dict)  # by language
    transcript: TranscriptDecision = Field(default_factory=TranscriptDecision)
    rights: Literal["owned", "attestation"] | None = None
    checklist: list[str] = Field(default_factory=list)
    captionsEnabled: bool | None = None
    seriesPosition: int | None = None
    notes: str | None = Field(default=None, max_length=2000)


def _apply_review_edits(db: Session, asset: AudioAsset, payload: PublishRequest, actor: str) -> list[str]:
    problems = []
    if payload.metadata:
        merged = {**metadata_of(asset), **payload.metadata}
        apply_metadata(asset, clean_metadata(merged, fallback_title=asset.title))
    asset.metadata_review_status = "approved"
    if payload.captionsEnabled is not None:
        asset.captions_enabled = payload.captionsEnabled
    if payload.seriesPosition is not None:
        asset.series_position = payload.seriesPosition

    draft = pipeline.latest_draft(db, asset.id)
    if not draft:
        problems.append("No teaser yet: regenerate the AI drafts")
    else:
        alternates = dict(draft.alternates or {})
        for language, text in payload.teaser.items():
            if language == draft.language:
                draft.short_text, draft.long_text = text.short.strip() or draft.short_text, text.long.strip() or draft.long_text
            else:
                alternates[language] = {"short": text.short.strip(), "long": text.long.strip()}
        draft.alternates = alternates
        if not (draft.short_text or draft.long_text):
            problems.append("The teaser is empty")
        draft.status, draft.reviewer = "approved", actor

    transcript = pipeline.latest_transcript(db, asset.id)
    if transcript:
        if payload.transcript.text is not None and payload.transcript.text.strip() != (transcript.text or "").strip():
            transcript.text = payload.transcript.text.strip()
        required = pipeline.transcript_review_required(db, asset, transcript)
        if payload.transcript.reviewed:
            transcript.status, transcript.reviewer, transcript.reviewed_at = "approved", actor, utcnow()
        elif required:
            problems.append("Read the transcript and tick “I checked the transcript” (captions are on or it looks unreliable)")
        else:
            transcript.status = "accepted"  # published without a line-by-line read (P2-09)

    if payload.rights == "owned":
        grant_owned_rights(db, asset, actor)
    elif payload.rights == "attestation":
        accept_narrator_attestation(db, asset, actor)

    missing = policy.required_checklist_ids() - set(payload.checklist)
    if missing:
        texts = [item["text"] for item in policy.REVIEW_CHECKLIST if item["id"] in missing]
        problems.append("Confirm the checklist: " + " ".join(texts))
    return problems


@router.post("/review/{asset_id}/publish")
def publish(asset_id: str, payload: PublishRequest, identity: Identity = Depends(require("content.publish")),
            db: Session = Depends(get_db)):
    asset = _asset(db, asset_id)
    if asset.status == "published":
        raise HTTPException(status_code=409, detail="Already published.")
    problems = _apply_review_edits(db, asset, payload, identity.username)
    db.flush()
    problems += [p for p in publish_readiness(db, asset) if p not in problems]
    if problems:
        db.rollback()  # all or nothing: nothing is half-approved
        raise HTTPException(status_code=409, detail={"error": "Not ready to publish.", "problems": problems})
    _event(db, asset.id, "review:checklist", identity.username, ", ".join(sorted(payload.checklist)))
    mark_published(db, asset, identity.username, payload.notes)
    _suggest_trust(db, asset)
    db.commit()
    return {"ok": True, "status": "published"}


@router.post("/review/{asset_id}/save")
def save_draft(asset_id: str, payload: PublishRequest, identity: Identity = Depends(require("content.publish")),
               db: Session = Depends(get_db)):
    """Save edits without publishing (metadata stays unapproved)."""
    asset = _asset(db, asset_id)
    if payload.metadata:
        apply_metadata(asset, clean_metadata({**metadata_of(asset), **payload.metadata}, fallback_title=asset.title))
    draft = pipeline.latest_draft(db, asset.id)
    if draft and payload.teaser:
        alternates = dict(draft.alternates or {})
        for language, text in payload.teaser.items():
            if language == draft.language:
                draft.short_text, draft.long_text = text.short.strip(), text.long.strip()
            else:
                alternates[language] = {"short": text.short.strip(), "long": text.long.strip()}
        draft.alternates = alternates
    transcript = pipeline.latest_transcript(db, asset.id)
    if transcript and payload.transcript.text is not None:
        transcript.text = payload.transcript.text.strip()
    if payload.captionsEnabled is not None:
        asset.captions_enabled = payload.captionsEnabled
    _event(db, asset.id, "review:saved", identity.username)
    db.commit()
    return {"ok": True}


def _suggest_trust(db: Session, asset: AudioAsset) -> None:
    if not asset.narrator_user_id:
        return
    profile = db.get(NarratorProfile, asset.narrator_user_id)
    if not profile or profile.trust_level != "new":
        return
    needed = int(app_settings.get(db, "narrators.trustAfterPublished"))
    published = db.scalar(select(func.count()).select_from(AudioAsset).where(
        AudioAsset.narrator_user_id == asset.narrator_user_id, AudioAsset.status == "published"))
    if published >= needed:
        _event(db, asset.id, "trust:suggested", "pipeline",
               f"{published} stories published; consider marking this narrator trusted.")


class ChangesRequest(BaseModel):
    reasons: list[str] = Field(min_length=1)
    note: str = Field(default="", max_length=2000)


@router.post("/review/{asset_id}/request-changes")
def request_changes(asset_id: str, payload: ChangesRequest, identity: Identity = Depends(require("content.publish")),
                    db: Session = Depends(get_db)):
    asset = _asset(db, asset_id)
    if asset.status == "published":
        raise HTTPException(status_code=409, detail="Published stories can't be sent back.")
    if not asset.narrator_user_id:
        raise HTTPException(status_code=409, detail="Catalog stories have no narrator to ask; edit or reject instead.")
    unknown = [code for code in payload.reasons if code not in policy.CHANGE_REASONS]
    if unknown:
        raise HTTPException(status_code=400, detail=f"Unknown reasons: {', '.join(unknown)}.")
    texts = policy.change_reason_texts(payload.reasons)
    asset.changes_requested = {"reasons": payload.reasons, "texts": texts, "note": payload.note.strip(),
                               "by": identity.username, "at": iso(utcnow())}
    asset.pipeline_stage, asset.ready_for_review_at = "changes-requested", None
    _event(db, asset.id, "content:changes-requested", identity.username, "; ".join([*texts, payload.note]))
    notify(db, asset.narrator_user_id, "changes-requested", f"“{asset.title}” needs a few changes",
           "\n".join([*texts, payload.note.strip()]).strip(), asset.id)
    db.commit()
    return {"ok": True, "stage": asset.pipeline_stage}


class RejectRequest(BaseModel):
    note: str = Field(min_length=1, max_length=2000)


@router.post("/review/{asset_id}/reject")
def reject(asset_id: str, payload: RejectRequest, identity: Identity = Depends(require("content.publish")),
           db: Session = Depends(get_db)):
    asset = _asset(db, asset_id)
    if asset.status == "published":
        raise HTTPException(status_code=409, detail="Published stories can't be rejected; unpublish first.")
    asset.status, asset.pipeline_stage, asset.ready_for_review_at = "rejected", "rejected", None
    _event(db, asset.id, "content:rejected", identity.username, payload.note)
    notify(db, asset.narrator_user_id, "rejected", f"“{asset.title}” wasn't accepted", payload.note, asset.id)
    db.commit()
    return {"ok": True}


class Regenerate(BaseModel):
    step: Literal["drafts", "artwork", "audio", "transcription"]


@router.post("/review/{asset_id}/regenerate", status_code=202)
def regenerate(asset_id: str, payload: Regenerate, identity: Identity = Depends(require("content.publish")),
               db: Session = Depends(get_db)):
    asset = _asset(db, asset_id)
    if payload.step == "transcription" and "jobs.manage" not in identity.permissions:
        raise HTTPException(status_code=403, detail="Only admins can start paid transcription.")
    job_type = {"drafts": "teaser", "artwork": "artwork", "audio": "media.process",
                "transcription": "transcription"}[payload.step]
    if jobs.active_job(db, asset.id, job_type):
        raise HTTPException(status_code=409, detail=f"{payload.step.capitalize()} is already running for this story.")
    job_payload: dict[str, Any] = {}
    if job_type == "teaser":
        transcript = pipeline.latest_transcript(db, asset.id)
        if not transcript:
            raise HTTPException(status_code=409, detail="There's no transcript to draft from.")
        job_payload = {"transcriptId": transcript.id}
        for draft in db.scalars(select(TeaserDraft).where(TeaserDraft.audio_asset_id == asset.id,
                                                          TeaserDraft.status == "needs-review")):
            draft.status = "superseded"
    elif job_type == "transcription":
        job_payload = {"language": asset.language}
    job = jobs.enqueue(db, job_type, asset_id=asset.id, payload=job_payload, created_by=identity.username,
                       priority=jobs.PRIORITY_INTERACTIVE)
    if asset.pipeline_stage == "failed":
        asset.pipeline_stage = {"teaser": "drafting", "artwork": "illustrating", "media.process": "checking",
                                "transcription": "transcribing"}[job_type]
        asset.pipeline_error = None
    _event(db, asset.id, f"regenerate:{payload.step}", identity.username, f"job {job.id}")
    db.commit()
    return {"ok": True, "job": _job_payload(job)}


class BulkPublish(BaseModel):
    assetIds: list[str] = Field(min_length=1, max_length=200)
    markOwned: bool = False  # catalog stories: KathaChepta owns them (one-click rights)
    spotChecked: bool = False


@router.post("/bulk-publish")
def bulk_publish(payload: BulkPublish, identity: Identity = Depends(require("content.publish")),
                 db: Session = Depends(get_db)):
    """P2-10: trusted narrators' and catalog stories that passed every automatic check, in one action."""
    if not payload.spotChecked:
        raise HTTPException(status_code=409, detail="Confirm you spot-checked a few of these stories first.")
    results = []
    for asset_id in dict.fromkeys(payload.assetIds):
        asset = db.scalars(select(AudioAsset).where(AudioAsset.id == asset_id)
                           .options(selectinload(AudioAsset.narrator_user))).first()
        if not asset:
            results.append({"id": asset_id, "ok": False, "problems": ["not found"]})
            continue
        draft, transcript = pipeline.latest_draft(db, asset.id), pipeline.latest_transcript(db, asset.id)
        trust = _trust(db, {asset.narrator_user_id} if asset.narrator_user_id else set()).get(asset.narrator_user_id)
        problems = bulk_blockers(db, asset, trust, draft, transcript)
        if not problems:
            with db.begin_nested() as savepoint:
                if not asset.source_adaptation and not asset.narrator_user_id and payload.markOwned:
                    asset.source_adaptation = "KathaChepta"
                if not asset.audience_age_range and draft and draft.age_suggestion:
                    asset.audience_age_range = draft.age_suggestion
                asset.metadata_review_status = "approved"
                draft.status, draft.reviewer = "approved", identity.username
                if transcript and transcript.status == "needs-review":
                    transcript.status = "accepted"
                if asset.narrator_user_id:
                    try:
                        accept_narrator_attestation(db, asset, identity.username, "Trusted narrator; bulk publish.")
                    except HTTPException as error:
                        problems.append(str(error.detail))
                elif payload.markOwned:
                    grant_owned_rights(db, asset, identity.username, "Bulk publish of the KathaChepta catalog.")
                db.flush()
                problems += publish_readiness(db, asset)
                if problems:
                    savepoint.rollback()
                else:
                    mark_published(db, asset, identity.username, "Bulk publish")
        results.append({"id": asset.id, "title": asset.title, "ok": not problems, "problems": problems})
    db.commit()
    return {"published": sum(r["ok"] for r in results), "results": results}


class Prepare(BaseModel):
    assetIds: list[str] = Field(default_factory=list, max_length=1000)
    allowTranscription: bool = False
    limit: int = Field(default=50, ge=1, le=1000)


@router.post("/prepare")
def prepare(payload: Prepare, identity: Identity = Depends(require("content.publish")), db: Session = Depends(get_db)):
    """Bring catalog stories into the pipeline. Stories with transcripts get free local drafts and artwork;
    paid transcription runs only when an admin allows it."""
    if payload.allowTranscription and "jobs.manage" not in identity.permissions:
        raise HTTPException(status_code=403, detail="Only admins can start paid transcription.")
    query = select(AudioAsset).where(AudioAsset.narrator_user_id.is_(None), AudioAsset.status != "published")
    if payload.assetIds:
        query = query.where(AudioAsset.id.in_(payload.assetIds))
    else:
        query = query.where(AudioAsset.pipeline_stage.in_(("none", "waiting-transcript"))).limit(payload.limit)
    stages: dict[str, int] = {}
    minutes = 0.0
    for asset in db.scalars(query):
        if not pipeline.latest_transcript(db, asset.id):
            minutes += (asset.duration_seconds or 0) / 60
        stage = pipeline.advance(db, asset, actor=identity.username, start=True,
                                 allow_transcription=payload.allowTranscription)
        stages[stage] = stages.get(stage, 0) + 1
    _event(db, "catalog", "catalog:prepare", identity.username,
           f"{sum(stages.values())} stories; transcription {'allowed' if payload.allowTranscription else 'not allowed'}")
    db.commit()
    return {"stories": sum(stages.values()), "stages": stages,
            "transcriptionMinutes": round(minutes) if payload.allowTranscription else 0,
            "untranscribedMinutes": round(minutes)}


# --- Mastering (P2-18) ---

class MasteringChoice(BaseModel):
    choice: Literal["auto", "full", "light", "none"]


@router.post("/review/{asset_id}/mastering", status_code=202)
def choose_mastering(asset_id: str, payload: MasteringChoice, identity: Identity = Depends(require("content.publish")),
                     db: Session = Depends(get_db)):
    """Re-master one story: automatic, clean up (noise removal), light polish, or the recording as made."""
    asset = _asset(db, asset_id)
    if jobs.active_job(db, asset.id, "media.process"):
        raise HTTPException(status_code=409, detail="The audio is already being processed; try again in a minute.")
    asset.audio_mastering = None if payload.choice == "auto" else payload.choice
    job = jobs.enqueue(db, "media.process", asset_id=asset.id, created_by=identity.username,
                       priority=jobs.PRIORITY_INTERACTIVE)
    _event(db, asset.id, "audio:mastering", identity.username, f"{payload.choice}; job {job.id}")
    db.commit()
    return {"ok": True, "job": _job_payload(job)}


REMASTER_SCOPES = {
    "pipeline": "Stories being prepared, in review, or published",
    "catalog": "Every story with processed audio",
}


def _remaster_query(scope: str):
    query = select(AudioAsset).where(AudioAsset.media_status == "ready", AudioAsset.status != "rejected")
    if scope == "pipeline":
        query = query.where(AudioAsset.pipeline_stage != "none")
    return query


@router.get("/audio/mastering")
def mastering_summary(identity: Identity = Depends(require("jobs.manage")), db: Session = Depends(get_db)):
    """How the catalog was mastered: counts by background profile and level, and what re-processing would cost."""
    profiles: dict[str, int] = {}
    levels: dict[str, int] = {}
    overrides = 0
    for qc, override in db.execute(select(AudioAsset.qc, AudioAsset.audio_mastering)
                                   .where(AudioAsset.media_status == "ready")):
        mastering = (qc or {}).get("mastering")
        if override:
            overrides += 1
        profile = mastering.get("profile") if mastering else "not-analysed"
        profiles[profile] = profiles.get(profile, 0) + 1
        if mastering:
            levels[mastering.get("level", "none")] = levels.get(mastering.get("level", "none"), 0) + 1
    scopes = []
    for scope, label in REMASTER_SCOPES.items():
        rows = _remaster_query(scope).subquery()
        stories, seconds = db.execute(select(func.count(), func.coalesce(func.sum(rows.c.duration_seconds), 0))).one()
        scopes.append({"scope": scope, "label": label, "stories": stories, "minutes": round(float(seconds) / 60)})
    running = db.scalar(select(func.count()).select_from(Job).where(
        Job.job_type == "media.process", Job.status.in_(("queued", "leased", "failed"))))
    return {"profiles": profiles, "levels": levels, "editorChoices": overrides, "scopes": scopes, "running": running}


class Remaster(BaseModel):
    scope: Literal["pipeline", "catalog"]


@router.post("/audio/remaster", status_code=202)
def remaster(payload: Remaster, request: Request, identity: Identity = Depends(require("jobs.manage")),
             db: Session = Depends(get_db)):
    """Run the audio step again with the current mastering settings (free: it runs on our own workers).

    Listeners keep hearing the current copy until each new one is ready; editors' per-story choices stay.
    """
    queued = 0
    for asset in db.scalars(_remaster_query(payload.scope)):
        if jobs.active_job(db, asset.id, "media.process"):
            continue
        jobs.enqueue(db, "media.process", asset_id=asset.id, created_by=identity.username,
                     priority=jobs.PRIORITY_BULK)
        queued += 1
    audit(db, "audio:remaster", request, identity.user.id, scope=payload.scope, stories=queued)
    db.commit()
    return {"queued": queued}


# --- Narrators and trust (P2-10) ---

@router.get("/narrators")
def narrators(identity: Identity = Depends(require("content.publish")), db: Session = Depends(get_db)):
    rows = db.execute(select(User, NarratorProfile).join(NarratorProfile, NarratorProfile.user_id == User.id)
                      .order_by(User.id)).all()
    counts: dict[int, dict[str, int]] = {}
    for user_id, status, count in db.execute(select(AudioAsset.narrator_user_id, AudioAsset.status, func.count())
                                             .where(AudioAsset.narrator_user_id.is_not(None))
                                             .group_by(AudioAsset.narrator_user_id, AudioAsset.status)):
        counts.setdefault(user_id, {})[status] = count
    needed = int(app_settings.get(db, "narrators.trustAfterPublished"))
    return {"items": [{"userId": user.id, "name": profile.display_name or user.handle, "email": user.email,
                       "phone": user.phone, "contactChannel": (user.contact_preferences or {}).get("channel") or "email",
                       "contactNotes": (user.contact_preferences or {}).get("notes") or "",
                       "languages": profile.languages, "trustLevel": profile.trust_level,
                       "onboardedAt": iso(profile.onboarded_at), "sampleUrl": media_url(profile.sample_key),
                       "published": counts.get(user.id, {}).get("published", 0),
                       "rejected": counts.get(user.id, {}).get("rejected", 0),
                       "inReview": sum(v for k, v in counts.get(user.id, {}).items() if k not in ("published", "rejected")),
                       "suggestTrust": profile.trust_level == "new" and counts.get(user.id, {}).get("published", 0) >= needed}
                      for user, profile in rows]}


class TrustChange(BaseModel):
    trustLevel: Literal["new", "trusted"]


@router.post("/narrators/{user_id}/trust")
def set_trust(user_id: int, payload: TrustChange, request: Request, identity: Identity = Depends(require("content.publish")),
              db: Session = Depends(get_db)):
    profile = db.get(NarratorProfile, user_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Narrator not found.")
    previous, profile.trust_level = profile.trust_level, payload.trustLevel
    audit(db, "narrator:trust", request, identity.user.id, narrator=user_id, previous=previous, new=payload.trustLevel)
    db.commit()
    return {"ok": True, "trustLevel": profile.trust_level}


@router.get("/activity")
def activity(limit: int = 100, identity: Identity = Depends(require("content.publish")), db: Session = Depends(get_db)):
    events = db.scalars(select(EditorialEvent).order_by(EditorialEvent.id.desc()).limit(min(limit, 500))).all()
    titles = dict(db.execute(select(AudioAsset.id, AudioAsset.title).where(
        AudioAsset.id.in_({e.entity_id for e in events}))).all())
    return {"items": [{"id": e.id, "assetId": e.entity_id if e.entity_id in titles else None,
                       "title": titles.get(e.entity_id), "action": e.action, "actor": e.actor, "notes": e.notes,
                       "createdAt": iso(e.created_at)} for e in events]}


# --- AI & processing settings (P2-14) ---

def _workers(db: Session) -> list[dict[str, Any]]:
    now = utcnow()
    return [{"name": w.name, "capabilities": w.capabilities, "lastSeenAt": iso(w.last_seen_at),
             "online": bool(w.last_seen_at and (now - w.last_seen_at).total_seconds() < 120),
             "info": {k: v for k, v in (w.info or {}).items() if k != "token"}, "disabled": bool(w.disabled_at)}
            for w in db.scalars(select(Worker).order_by(Worker.name))]


@router.get("/settings")
def get_settings_page(identity: Identity = Depends(require("jobs.manage")), db: Session = Depends(get_db)):
    workers = _workers(db)
    models = sorted({m for w in workers for m in (w["info"].get("teaser") or {}).get("availableModels", [])
                     if "embed" not in m})  # embedding models can't draft
    queued = dict(db.execute(select(Job.job_type, func.count()).where(Job.status.in_(("queued", "leased", "failed")))
                             .group_by(Job.job_type)).all())
    dead = dict(db.execute(select(Job.job_type, func.count()).where(
        Job.status == "dead", Job.updated_at > utcnow() - timedelta(days=7)).group_by(Job.job_type)).all())
    return {"specs": app_settings.describe(), "values": app_settings.all_settings(db), "workers": workers,
            "availableModels": models, "queue": queued, "deadLastWeek": dead,
            "transcriptionMinutesToday": round(pipeline._transcription_minutes_today(db))}


class SettingsChange(BaseModel):
    values: dict[str, Any]


@router.put("/settings")
def put_settings(payload: SettingsChange, request: Request, identity: Identity = Depends(require("jobs.manage")),
                 db: Session = Depends(get_db)):
    before = app_settings.all_settings(db)
    changed = {}
    for key, value in payload.values.items():
        value = app_settings.put(db, key, value, identity.username)
        if before.get(key) != value:
            changed[key] = {"from": before.get(key), "to": value}
    if changed:
        audit(db, "settings:changed", request, identity.user.id, changes=changed)
    db.commit()
    return {"ok": True, "changed": list(changed), "values": app_settings.all_settings(db)}


class SettingsTest(BaseModel):
    task: Literal["drafts", "artwork"]
    assetId: str
    values: dict[str, Any] = Field(default_factory=dict)  # unsaved settings to try


@router.post("/settings/test", status_code=202)
def test_settings(payload: SettingsTest, identity: Identity = Depends(require("jobs.manage")),
                  db: Session = Depends(get_db)):
    """Run one job with the given (unsaved) settings; the result is shown, never applied to the story."""
    asset = _asset(db, payload.assetId)
    for key, value in payload.values.items():
        app_settings.validate(key, value)
    job_payload: dict[str, Any] = {"test": True, "settings": payload.values}
    if payload.task == "drafts":
        transcript = pipeline.latest_transcript(db, asset.id)
        if not transcript:
            raise HTTPException(status_code=409, detail="Pick a story that has a transcript.")
        job_payload["transcriptId"] = transcript.id
    job = jobs.enqueue(db, "teaser" if payload.task == "drafts" else "artwork", asset_id=asset.id,
                       payload=job_payload, created_by=identity.username, priority=jobs.PRIORITY_INTERACTIVE,
                       max_attempts=1)
    db.commit()
    return {"jobId": job.id}


@router.get("/jobs/{job_id}")
def job_detail(job_id: int, identity: Identity = Depends(require("content.publish")), db: Session = Depends(get_db)):
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")
    result = dict(job.result or {})
    if job.job_type == "artwork" and result.get("key"):
        result["url"] = media_url(result["key"])
    return {**_job_payload(job), "type": job.job_type, "result": result, "payload": job.payload,
            "assetId": job.audio_asset_id}


# --- Notifications (everyone) ---

@me_router.get("")
def list_notifications(identity: Identity = Depends(require_identity), db: Session = Depends(get_db)):
    rows = db.scalars(select(Notification).where(Notification.user_id == identity.user.id)
                      .order_by(Notification.id.desc()).limit(50)).all()
    return {"items": [{"id": n.id, "kind": n.kind, "title": n.title, "body": n.body, "assetId": n.audio_asset_id,
                       "read": n.read_at is not None, "createdAt": iso(n.created_at)} for n in rows],
            "unread": sum(1 for n in rows if n.read_at is None)}


@me_router.post("/read")
def read_notifications(identity: Identity = Depends(require_identity), db: Session = Depends(get_db)):
    db.execute(Notification.__table__.update().where(Notification.user_id == identity.user.id,
                                                     Notification.read_at.is_(None)).values(read_at=utcnow()))
    db.commit()
    return {"ok": True}
