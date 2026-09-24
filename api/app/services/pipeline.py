"""Automatic story pipeline (P2-05).

upload → audio check (QC) → transcription → AI drafts (teaser, metadata, safety) → artwork → editor review

Each finished job calls ``advance``, which works out the next missing step from the data (not from a
stored cursor), so a retried, regenerated, or manually run step never leaves the pipeline stuck.
Seed-catalog stories only enter the pipeline when an admin prepares them, and are never transcribed
(a paid step) unless the admin explicitly allows it.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import jobs
from ..auth import utcnow
from ..models import AudioAsset, EditorialEvent, Job, TeaserDraft, Transcript
from . import settings as app_settings
from .notify import notify
from .transcripts import assess, strip_intro

# Narrator-facing stage names. "none" means the story isn't in the pipeline (seed catalog, untouched).
STAGES = {
    "none": "Not started",
    "checking": "Being checked",
    "needs-fix": "Needs a fix",
    "awaiting-submit": "Ready to submit",
    "transcribing": "Being prepared",
    "waiting-transcript": "Waiting for transcription approval",
    "drafting": "Being prepared",
    "illustrating": "Being prepared",
    "ready": "With editor",
    "changes-requested": "Changes requested",
    "published": "Published",
    "rejected": "Not accepted",
    "failed": "Stuck: we're looking into it",
}
IN_PROGRESS = ("checking", "awaiting-submit", "transcribing", "waiting-transcript", "drafting", "illustrating",
               "ready", "failed")
FINAL = ("published", "rejected")
STEP_OF_JOB = {"media.process": "Audio check", "transcription": "Transcription", "teaser": "AI drafts",
               "artwork": "Artwork"}
STT_LANGUAGES = {"te-IN", "hi-IN", "ta-IN", "kn-IN", "ml-IN", "mr-IN", "bn-IN", "gu-IN", "pa-IN", "od-IN", "en-IN"}
USABLE = ("needs-review", "approved", "accepted")


def latest_transcript(db: Session, asset_id: str) -> Transcript | None:
    return db.scalars(select(Transcript).where(Transcript.audio_asset_id == asset_id, Transcript.status.in_(USABLE))
                      .order_by(Transcript.version.desc())).first()


def latest_draft(db: Session, asset_id: str) -> TeaserDraft | None:
    return db.scalars(select(TeaserDraft).where(TeaserDraft.audio_asset_id == asset_id,
                                                TeaserDraft.status.in_(("needs-review", "approved")))
                      .order_by(TeaserDraft.id.desc())).first()


def _event(db: Session, asset: AudioAsset, action: str, notes: str | None = None, actor: str = "pipeline") -> None:
    db.add(EditorialEvent(entity_type="audio_asset", entity_id=asset.id, action=action, actor=actor, notes=notes))


def _set_stage(db: Session, asset: AudioAsset, stage: str, note: str | None = None) -> None:
    if asset.pipeline_stage != stage:
        asset.pipeline_stage = stage
        _event(db, asset, f"pipeline:{stage}", note)
    if stage != "failed":
        asset.pipeline_error = None


def _enqueue(db: Session, asset: AudioAsset, job_type: str, actor: str, payload: dict | None = None,
             run_after: datetime | None = None) -> Job:
    running = jobs.active_job(db, asset.id, job_type)
    if running:
        return running
    priority = jobs.PRIORITY_INTERACTIVE if asset.narrator_user_id else jobs.PRIORITY_DEFAULT
    job = jobs.enqueue(db, job_type, asset_id=asset.id, payload=payload or {}, created_by=actor, priority=priority)
    if run_after:
        job.run_after = run_after
    return job


def prepare_transcript(db: Session, transcript: Transcript, asset: AudioAsset) -> None:
    """Strip the channel intro and score confidence once per transcript (idempotent)."""
    if transcript.confidence is None:
        patterns = app_settings.get(db, "pipeline.introPatterns")
        if transcript.intro_removed is None and transcript.text:
            cleaned, removed = strip_intro(transcript.text, transcript.language, patterns)
            if removed:
                transcript.text, transcript.intro_removed = cleaned, removed
        confidence, quality = assess(transcript.text or "", asset.duration_seconds or 0,
                                     language_probability=(transcript.quality or {}).get("languageProbability"),
                                     segments=transcript.segments)
        transcript.confidence, transcript.quality = confidence, quality


def transcript_review_required(db: Session, asset: AudioAsset, transcript: Transcript | None) -> bool:
    """P2-09: read the transcript only when captions are on or the transcription looks unreliable."""
    if transcript is None:
        return False
    if asset.captions_enabled:
        return True
    threshold = float(app_settings.get(db, "review.transcriptConfidence"))
    return transcript.confidence is None or transcript.confidence < threshold


def _transcription_minutes_today(db: Session) -> float:
    start = datetime.combine(utcnow().date(), time.min, tzinfo=timezone.utc)
    seconds = db.scalar(select(func.coalesce(func.sum(AudioAsset.duration_seconds), 0))
                        .join(Job, Job.audio_asset_id == AudioAsset.id)
                        .where(Job.job_type == "transcription", Job.created_at >= start,
                               Job.status != "cancelled"))
    return float(seconds or 0) / 60


def advance(db: Session, asset: AudioAsset, *, actor: str = "pipeline", allow_transcription: bool = False,
            start: bool = False) -> str:
    """Queue the next missing step and return the new stage.

    ``start`` brings a story into the pipeline (upload, submit, admin "prepare"); without it, stories that
    are outside the pipeline or already decided are left alone.
    """
    if not start and asset.pipeline_stage in ("none", *FINAL):
        return asset.pipeline_stage
    if asset.status == "published":
        _set_stage(db, asset, "published")
        return asset.pipeline_stage

    if asset.media_status != "ready":
        if asset.media_status == "failed" and not start:
            return asset.pipeline_stage
        _enqueue(db, asset, "media.process", actor)
        _set_stage(db, asset, "checking")
        return asset.pipeline_stage
    if (asset.qc or {}).get("verdict") == "fail":
        if asset.pipeline_stage != "needs-fix":
            _set_stage(db, asset, "needs-fix")
            tips = "; ".join(c.get("tip") or c.get("message", "") for c in asset.qc.get("checks", [])
                             if c.get("level") == "fail")
            notify(db, asset.narrator_user_id, "needs-fix", f"“{asset.title}” needs a fix before review", tips, asset.id)
        return asset.pipeline_stage
    if asset.narrator_user_id and not asset.submitted_at:
        _set_stage(db, asset, "awaiting-submit")
        return asset.pipeline_stage

    transcript = latest_transcript(db, asset.id)
    if transcript is None:
        automatic = bool(asset.narrator_user_id) and app_settings.get(db, "pipeline.autoTranscribe")
        if not (automatic or allow_transcription):
            _set_stage(db, asset, "waiting-transcript", "Transcription is paid; an admin must allow it for this story.")
            return asset.pipeline_stage
        if asset.language not in STT_LANGUAGES:
            _set_stage(db, asset, "failed")
            asset.pipeline_error = f"No speech-to-text provider for {asset.language} yet."
            return asset.pipeline_stage
        limit = float(app_settings.get(db, "pipeline.dailyTranscriptionMinutes"))
        run_after, note = None, None
        if jobs.active_job(db, asset.id, "transcription") is None and \
                _transcription_minutes_today(db) + (asset.duration_seconds or 0) / 60 > limit:
            run_after = datetime.combine(utcnow().date() + timedelta(days=1), time.min, tzinfo=timezone.utc)
            note = f"Daily transcription limit ({limit:g} min) reached; transcription starts tomorrow."
        _enqueue(db, asset, "transcription", actor, {"language": asset.language}, run_after)
        _set_stage(db, asset, "transcribing", note)
        return asset.pipeline_stage

    prepare_transcript(db, transcript, asset)
    draft = latest_draft(db, asset.id)
    if draft is None:
        _enqueue(db, asset, "teaser", actor, {"transcriptId": transcript.id})
        _set_stage(db, asset, "drafting")
        return asset.pipeline_stage

    provider = app_settings.get(db, "ai.artwork.provider")
    if not asset.artwork_key and provider != "disabled" and app_settings.get(db, "pipeline.autoArtwork"):
        if not _artwork_gave_up(db, asset.id):
            _enqueue(db, asset, "artwork", actor)
            _set_stage(db, asset, "illustrating")
            return asset.pipeline_stage

    if asset.pipeline_stage != "changes-requested" or start:
        if asset.pipeline_stage != "ready":
            asset.ready_for_review_at = utcnow()
            if asset.narrator_user_id:
                notify(db, asset.narrator_user_id, "with-editor", f"“{asset.title}” is with an editor",
                       "Everything checked out. An editor will review it soon.", asset.id)
        _set_stage(db, asset, "ready")
    return asset.pipeline_stage


def _artwork_gave_up(db: Session, asset_id: str) -> bool:
    """Artwork is nice-to-have: after a dead artwork job, go to review without it rather than getting stuck."""
    last = db.scalars(select(Job).where(Job.audio_asset_id == asset_id, Job.job_type == "artwork")
                      .order_by(Job.id.desc())).first()
    return bool(last and last.status == "dead")


def on_job_finished(db: Session, job: Job, asset: AudioAsset) -> None:
    if (job.payload or {}).get("test"):
        return
    advance(db, asset)


def on_job_dead(db: Session, job: Job, asset: AudioAsset) -> None:
    if (job.payload or {}).get("test") or asset.pipeline_stage in ("none", *FINAL):
        return
    if job.job_type == "artwork":  # optional step: continue to review without artwork
        advance(db, asset)
        return
    step = STEP_OF_JOB.get(job.job_type, job.job_type)
    _set_stage(db, asset, "failed", f"{step} failed")
    asset.pipeline_error = f"{step} failed: {(job.error or 'unknown error')[:300]}"


def narrator_timeline(db: Session, asset: AudioAsset) -> list[dict]:
    """Plain-language steps for the narrator's submission page."""
    stage = asset.pipeline_stage
    order = ["checking", "transcribing", "drafting", "ready", "published"]
    position = {"none": -1, "checking": 0, "needs-fix": 0, "awaiting-submit": 0, "transcribing": 1,
                "waiting-transcript": 1, "drafting": 2, "illustrating": 2, "ready": 3, "changes-requested": 3,
                "failed": 1, "published": 4, "rejected": 3}.get(stage, 0)
    labels = {"checking": "Sound check", "transcribing": "Transcription", "drafting": "Story details and artwork",
              "ready": "Editor review", "published": "Published"}
    steps = []
    for index, key in enumerate(order):
        state = "done" if index < position else "current" if index == position else "todo"
        if index == position and stage in ("needs-fix", "changes-requested", "failed", "rejected"):
            state = "blocked"
        if stage == "published":
            state = "done"
        steps.append({"key": key, "label": labels[key], "state": state})
    return steps
