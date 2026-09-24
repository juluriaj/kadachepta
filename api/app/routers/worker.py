"""Pull-based worker API.

Workers (the media worker in Docker, the GPU/LLM worker on the desktop, or a
future cloud worker) authenticate with ``Authorization: Worker <token>``, lease
jobs they have capabilities for, upload output files, and report results. All
database writes happen here, so workers stay stateless and can run anywhere
with HTTPS access to the API.
"""

from __future__ import annotations

import re
import tempfile
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select, update
from starlette.concurrency import run_in_threadpool
from sqlalchemy.orm import Session

from .. import jobs
from ..auth import utcnow
from ..config import get_settings
from ..db import get_db
from ..models import AudioAsset, EditorialEvent, Job, TeaserDraft, Transcript, Worker
from ..security import token_hash
from ..services import pipeline, policy
from ..services import settings as app_settings
from ..services.assets import as_list, normalize_language
from ..storage import get_storage, media_url

router = APIRouter(prefix="/api/worker", tags=["worker"])

FILE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,80}$")


def current_worker(authorization: str = Header(""), db: Session = Depends(get_db)) -> Worker:
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "worker" or not token:
        raise HTTPException(status_code=401, detail="Worker token required (Authorization: Worker <token>).")
    worker = db.scalars(select(Worker).where(Worker.token_hash == token_hash(token.strip()))).first()
    if not worker or worker.disabled_at:
        raise HTTPException(status_code=401, detail="Unknown or disabled worker token.")
    # Several worker processes can share one identity: record "last seen" in its own short transaction
    # (and at most every 20 s) so no request holds the worker row lock while it does other work.
    now = utcnow()
    if not worker.last_seen_at or (now - worker.last_seen_at).total_seconds() > 20:
        db.execute(update(Worker).where(Worker.id == worker.id).values(last_seen_at=now))
        db.commit()
    return worker


def _job_for(db: Session, worker: Worker, job_id: int) -> Job:
    job = db.get(Job, job_id)
    if not job or job.leased_by != worker.name or job.status != "leased":
        raise HTTPException(status_code=409, detail=f"Job {job_id} is not leased by worker {worker.name!r}.")
    return job


def _absolute(request: Request, path: str | None) -> str | None:
    if not path:
        return None
    return str(request.base_url).rstrip("/") + path


def _inputs(db: Session, job: Job, request: Request) -> dict[str, Any]:
    asset = db.get(AudioAsset, job.audio_asset_id) if job.audio_asset_id else None
    if not asset:
        return {}
    base = {"assetId": asset.id, "title": asset.title, "language": asset.language,
            "versionNumber": asset.version_number, "checksum": asset.checksum_sha256,
            "sourceUrl": _absolute(request, media_url(asset.source_key)),
            "sourceFilename": asset.source_filename,
            # Admin settings (models, providers, prompt versions) travel with every job: no worker restarts.
            "settings": app_settings.for_job(db, job.job_type, asset.language, job.payload.get("settings"))}
    if job.job_type == "media.process" and job.payload.get("parts"):
        # A recording made in several takes: the worker joins the parts before processing.
        base["parts"] = [{"url": _absolute(request, media_url(key)), "filename": key.rsplit("/", 1)[-1]}
                         for key in job.payload["parts"]]
    if job.job_type == "teaser":
        transcript_id = job.payload.get("transcriptId")
        transcript = db.get(Transcript, transcript_id) if transcript_id else None
        if transcript:
            pipeline.prepare_transcript(db, transcript, asset)
            db.commit()
        base.update(transcriptId=transcript.id if transcript else None,
                    transcript=transcript.text if transcript else "",
                    outputLanguages=[asset.language, "en-IN"] if asset.language != "en-IN" else ["en-IN"],
                    series=asset.series.title if asset.series else None)
    if job.job_type == "artwork":
        draft = pipeline.latest_draft(db, asset.id)
        english = (draft.alternates or {}).get("en-IN", {}) if draft else {}
        base.update(album=asset.album, genres=asset.genres, mood=asset.mood, moralTakeaway=asset.moral_takeaway,
                    audienceAgeRange=asset.audience_age_range, hasArtwork=bool(asset.artwork_key),
                    englishTitle=(draft.suggestions or {}).get("englishTitle") if draft else None,
                    englishTeaser=english.get("long") or english.get("short"),
                    themes=draft.themes if draft else [])
    return base


class LeaseRequest(BaseModel):
    capabilities: list[str] | None = None
    info: dict[str, Any] = Field(default_factory=dict)
    preferType: str | None = None  # the worker's last job type: keeps models loaded on a shared GPU


@router.post("/lease")
def lease(payload: LeaseRequest, request: Request, worker: Worker = Depends(current_worker),
          db: Session = Depends(get_db)):
    capabilities = [c for c in (payload.capabilities or worker.capabilities) if c in worker.capabilities]
    if payload.info and payload.info != worker.info:
        db.execute(update(Worker).where(Worker.id == worker.id).values(info=payload.info))
        db.commit()
    job = jobs.lease(db, worker.name, capabilities, get_settings().job_lease_seconds, prefer=payload.preferType)
    if not job:
        return Response(status_code=204)
    return {"id": job.id, "type": job.job_type, "attempt": job.attempts, "payload": job.payload,
            "leaseSeconds": get_settings().job_lease_seconds, "inputs": _inputs(db, job, request)}


@router.post("/jobs/{job_id}/heartbeat")
def heartbeat(job_id: int, worker: Worker = Depends(current_worker), db: Session = Depends(get_db)):
    jobs.heartbeat(db, _job_for(db, worker, job_id), get_settings().job_lease_seconds)
    return {"ok": True}


def _output_key(job: Job, asset: AudioAsset, name: str) -> str:
    if job.job_type == "media.process" and name.startswith("original."):
        return f"originals/{asset.id}/joined-{job.id}-{name}"
    if job.job_type == "media.process":
        return f"renditions/{asset.id}/v{asset.version_number}/{name}"
    if job.job_type == "artwork":
        return f"artworks/{asset.id}/{int(utcnow().timestamp())}-{name}"
    if job.job_type == "transcription":
        return f"transcripts/{asset.id}/job{job.id}-{name}"
    raise HTTPException(status_code=400, detail=f"Job type {job.job_type} does not accept files.")


@router.post("/jobs/{job_id}/files")
async def upload_file(job_id: int, name: str, request: Request, worker: Worker = Depends(current_worker),
                      db: Session = Depends(get_db)):
    if not FILE_NAME.match(name):
        raise HTTPException(status_code=400, detail="Invalid file name.")
    # Receive the body before touching the database: blocking DB calls must never run on the event loop.
    with tempfile.SpooledTemporaryFile(max_size=8 * 1024 * 1024) as buffer:
        async for chunk in request.stream():
            buffer.write(chunk)
        buffer.seek(0)

        def store() -> dict[str, Any]:
            job = _job_for(db, worker, job_id)
            key = _output_key(job, db.get(AudioAsset, job.audio_asset_id), name)
            db.rollback()  # end the read transaction before the (slow) file write
            return {"key": key, "bytes": get_storage().put_stream(key, buffer)}

        return await run_in_threadpool(store)


class Completion(BaseModel):
    result: dict[str, Any] = Field(default_factory=dict)
    logTail: str | None = None


class Failure(BaseModel):
    error: str
    retryable: bool = True
    logTail: str | None = None


def _require_key(asset: AudioAsset, key: str | None, prefix: str) -> str:
    if not key or not key.startswith(f"{prefix}/{asset.id}/") or not get_storage().exists(key):
        raise HTTPException(status_code=400, detail=f"Result references a missing or foreign file: {key!r}.")
    return key


def apply_media(db: Session, job: Job, asset: AudioAsset, result: dict[str, Any]) -> None:
    if result.get("sourceKey"):  # the worker joined several takes into one original
        asset.source_key = _require_key(asset, result["sourceKey"], "originals")
        asset.source_filename = result["sourceKey"].rsplit("/", 1)[-1]
        if result.get("sourceChecksum"):
            asset.checksum_sha256 = str(result["sourceChecksum"])[:64]
    renditions = {}
    for name in ("standard", "datasaver"):
        entry = result.get("renditions", {}).get(name)
        if entry:
            renditions[name] = {**entry, "key": _require_key(asset, entry.get("key"), "renditions")}
    renditions["waveform"] = [round(float(v), 3) for v in result.get("waveform", [])][:400]
    asset.renditions = renditions
    asset.qc = result.get("qc", {})
    asset.media_status = "ready" if renditions.get("standard") else "failed"
    for field, column in (("durationSeconds", "duration_seconds"), ("bitrate", "bitrate"),
                          ("sampleRate", "sample_rate"), ("channels", "channels")):
        if result.get(field) is not None:
            setattr(asset, column, result[field])


def apply_transcription(db: Session, job: Job, asset: AudioAsset, result: dict[str, Any]) -> None:
    version = (db.scalar(select(func.max(Transcript.version)).where(Transcript.audio_asset_id == asset.id)) or 0) + 1
    raw_key = result.get("rawKey")
    if raw_key:
        _require_key(asset, raw_key, "transcripts")
    probability = result.get("languageProbability")
    transcript = Transcript(audio_asset_id=asset.id, version=version,
                            language=normalize_language(result.get("language") or asset.language),
                            text=result.get("text") or "", segments=result.get("segments") or [], raw_key=raw_key,
                            provider=result.get("provider"), model=result.get("model"),
                            source_audio_checksum=asset.checksum_sha256, status="needs-review",
                            quality={"languageProbability": float(probability)} if probability is not None else {})
    db.add(transcript)
    db.flush()
    pipeline.prepare_transcript(db, transcript, asset)


GENRES = ("Folklore", "Fable", "Mythology", "History", "Adventure", "Fantasy", "Humor", "Family", "Science",
          "Moral", "Biography", "Mystery", "Poetry", "Devotional", "Nature")
CONTEXTS = ("bedtime", "drive", "run", "work", "learn")


def _safety(value: Any, transcript: str, language: str) -> dict[str, Any]:
    """The model's safety check plus the word list; the rating follows the flags, not the model's say-so."""
    value = value if isinstance(value, dict) else {}
    flags = [{"category": str(flag.get("category", ""))[:40], "severity": str(flag.get("severity", ""))[:12],
              "evidence": str(flag.get("evidence", ""))[:300], "source": "ai"}
             for flag in value.get("flags") or [] if isinstance(flag, dict)][:10]
    ai_categories = {flag["category"] for flag in flags}
    flags += [flag for flag in policy.lexicon_flags(transcript, language) if flag["category"] not in ai_categories]
    try:
        min_age = max(0, min(int(value.get("minAge")), 18))
    except (TypeError, ValueError):
        min_age = None
    if any(flag["source"] == "word-list" for flag in flags) and (min_age or 0) < 6:
        min_age = 6  # a death, ghost, or fight in the text: not for the youngest until a person decides
    return {"rating": policy.derive_rating(value.get("rating"), flags), "modelRating": value.get("rating"),
            "minAge": min_age, "flags": flags, "summary": str(value.get("summary") or "")[:400]}


def _transcript_text(db: Session, job: Job) -> str:
    transcript = db.get(Transcript, job.payload.get("transcriptId")) if job.payload.get("transcriptId") else None
    return transcript.text or "" if transcript else ""


def apply_teaser(db: Session, job: Job, asset: AudioAsset, result: dict[str, Any]) -> None:
    primary = normalize_language(result.get("language") or asset.language)
    texts = result.get("texts") or {}
    main = texts.get(primary) or {}
    if not (main.get("short") or main.get("long")):
        raise HTTPException(status_code=422, detail=f"Teaser result has no text for {primary}.")
    if job.payload.get("test"):
        return  # "test on one story" from the settings page: the result stays on the job only
    suggestions = {
        "genres": [g for g in as_list(result.get("genres")) if g in GENRES][:4],
        "keywords": [k[:40] for k in as_list(result.get("keywords"))][:10],
        "listeningContexts": [c for c in as_list(result.get("listeningContexts")) if c in CONTEXTS],
        "englishTitle": str(result.get("englishTitle") or "")[:120] or None,
    }
    db.add(TeaserDraft(
        audio_asset_id=asset.id, transcript_id=job.payload.get("transcriptId"), language=primary,
        short_text=main.get("short"), long_text=main.get("long"),
        alternates={lang: value for lang, value in texts.items() if lang != primary},
        themes=result.get("themes") or [], mood=result.get("mood") or [],
        age_suggestion=str(result.get("ageSuggestion") or "") or None,
        warnings=result.get("contentWarnings") or [], provider=result.get("provider"),
        safety=_safety(result.get("safety"), _transcript_text(db, job), asset.language), suggestions=suggestions,
        model=result.get("model"), prompt_version=result.get("promptVersion"), status="needs-review"))
    for column, key in (("genres", "genres"), ("keywords", "keywords"), ("listening_contexts", "listeningContexts")):
        if not getattr(asset, column) and suggestions[key]:
            setattr(asset, column, suggestions[key])
            if column == "genres":
                asset.genre = suggestions[key][0]
    # Pre-fill empty metadata with the AI suggestions so editors confirm instead of typing.
    # These stay unapproved until an editor reviews the metadata.
    if not asset.moral_takeaway and result.get("moralTakeaway"):
        asset.moral_takeaway = str(result["moralTakeaway"])[:500]
    if not asset.audience_age_range and result.get("ageSuggestion"):
        asset.audience_age_range = str(result["ageSuggestion"])[:20]
    if not asset.mood and result.get("mood"):
        asset.mood = ", ".join(map(str, result["mood"]))[:120]
    if not asset.content_warnings and result.get("contentWarnings"):
        asset.content_warnings = [str(item)[:80] for item in result["contentWarnings"]][:8]


def apply_artwork(db: Session, job: Job, asset: AudioAsset, result: dict[str, Any]) -> None:
    key = _require_key(asset, result.get("key"), "artworks")
    if job.payload.get("test"):
        return
    asset.artwork_key = key
    asset.artwork_updated_at = utcnow()
    db.add(EditorialEvent(entity_type="audio_asset", entity_id=asset.id, action="artwork:generated",
                          actor=f"ai:{result.get('provider', 'unknown')}",
                          notes=f"model={result.get('model')} seed={result.get('seed')}"))


APPLIERS = {"media.process": apply_media, "transcription": apply_transcription,
            "teaser": apply_teaser, "artwork": apply_artwork}


@router.post("/jobs/{job_id}/complete")
def complete(job_id: int, payload: Completion, worker: Worker = Depends(current_worker),
             db: Session = Depends(get_db)):
    job = _job_for(db, worker, job_id)
    asset = db.get(AudioAsset, job.audio_asset_id) if job.audio_asset_id else None
    if asset:
        try:
            APPLIERS[job.job_type](db, job, asset, payload.result)
        except HTTPException as error:
            db.rollback()
            job = _job_for(db, worker, job_id)
            jobs.fail(db, job, f"Result rejected by API: {error.detail}", retryable=False, log_tail=payload.logTail)
            pipeline.on_job_dead(db, job, db.get(AudioAsset, job.audio_asset_id))
            db.commit()
            raise
    jobs.complete(db, job, payload.result, payload.logTail)
    if asset:
        pipeline.on_job_finished(db, job, asset)
    db.commit()
    return {"ok": True}


@router.post("/jobs/{job_id}/fail")
def fail(job_id: int, payload: Failure, worker: Worker = Depends(current_worker), db: Session = Depends(get_db)):
    job = _job_for(db, worker, job_id)
    jobs.fail(db, job, payload.error, retryable=payload.retryable, log_tail=payload.logTail)
    asset = db.get(AudioAsset, job.audio_asset_id) if job.audio_asset_id else None
    if job.status == "dead" and asset:
        if job.job_type == "media.process":
            asset.media_status = "failed"
        pipeline.on_job_dead(db, job, asset)
    db.commit()
    return {"ok": True, "status": job.status, "runAfter": job.run_after.isoformat()}
