"""Batch review for the seed catalog: many ready stories on one page, each approved with one action.

Same rules as the full review screen (studio.publish does the work): the editor listens to the start, a middle
section, and the end, checks the age band against the safety flags, and confirms the titles and teaser. Stories
that need more than that (a transcript to read, a safety flag, a sound-check failure) open in the full review.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from ..auth import Identity, require
from ..db import get_db
from ..models import AssetRights, AudioAsset, TeaserDraft, Transcript
from ..services import pipeline, policy, titles
from ..services.assets import artwork_url, audio_urls
from .studio import PublishRequest, TeaserText, TranscriptDecision, _latest_by_asset
from .studio import publish as publish_story

router = APIRouter(prefix="/api/studio/batch", tags=["studio"])
EDITOR = require("content.publish")


def _ready_catalog():
    return select(AudioAsset).where(AudioAsset.narrator_user_id.is_(None), AudioAsset.pipeline_stage == "ready",
                                    AudioAsset.status != "published")


def full_review_reasons(db: Session, asset: AudioAsset, draft: TeaserDraft | None,
                        transcript: Transcript | None) -> list[str]:
    """What needs the full review screen instead of a batch approval."""
    reasons = []
    if not draft:
        reasons.append("no AI drafts")
    elif (draft.safety or {}).get("rating") not in ("all-ages", "caution") or any(
            f.get("severity") == "high" for f in (draft.safety or {}).get("flags", [])):
        reasons.append("safety check needs a closer look")
    if (asset.qc or {}).get("verdict") == "fail":
        reasons.append("sound check failed")
    if transcript is None:
        reasons.append("no transcript")
    return reasons


@router.get("")
def batch(group: str | None = None, limit: int = 20, offset: int = 0, identity: Identity = Depends(EDITOR),
          db: Session = Depends(get_db)):
    """Ready catalog stories, a page at a time, grouped by catalog collection (series chapters in order)."""
    groups = [{"name": name, "count": count} for name, count in db.execute(
        _ready_catalog().with_only_columns(AudioAsset.collection, func.count())
        .group_by(AudioAsset.collection).order_by(func.count().desc())).all()]
    query = _ready_catalog().options(selectinload(AudioAsset.series))
    if group:
        query = query.where(AudioAsset.collection == group)
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    assets = db.scalars(query.order_by(AudioAsset.collection, AudioAsset.series_position.nulls_last(), AudioAsset.title)
                        .offset(max(offset, 0)).limit(min(max(limit, 1), 50))).all()
    ids = [a.id for a in assets]
    drafts = _latest_by_asset(db, TeaserDraft, ids, ("needs-review", "approved"))
    transcripts = _latest_by_asset(db, Transcript, ids, pipeline.USABLE)
    items = []
    for asset in assets:
        draft, transcript = drafts.get(asset.id), transcripts.get(asset.id)
        if transcript:
            pipeline.prepare_transcript(db, transcript, asset)
        teasers: dict[str, dict[str, str]] = {}
        if draft:
            teasers[draft.language] = {"short": draft.short_text or "", "long": draft.long_text or ""}
            for language, value in (draft.alternates or {}).items():
                teasers[language] = {"short": value.get("short") or "", "long": value.get("long") or ""}
        entries = titles.entries(asset)
        suggestions = (draft.suggestions or {}) if draft else {}
        items.append({
            "id": asset.id, "title": asset.title, "collection": asset.collection, "language": asset.language,
            "series": {"title": asset.series.title, "position": asset.series_position} if asset.series else None,
            "duration": asset.duration_seconds, "audioUrl": audio_urls(asset)["audioUrl"], "artworkUrl": artwork_url(asset),
            "qcVerdict": (asset.qc or {}).get("verdict"),
            "titles": {lang: entries[lang]["text"] if lang in entries else
                       (suggestions.get("englishTitle") or "" if lang == "en-IN" else "") for lang in titles.UI_LANGUAGES},
            "teasers": teasers, "draftLanguage": draft.language if draft else None,
            "age": asset.audience_age_range or (draft.age_suggestion if draft else None),
            "moral": asset.moral_takeaway, "genres": asset.genres,
            "safety": {"rating": (draft.safety or {}).get("rating"), "summary": (draft.safety or {}).get("summary"),
                       "flags": (draft.safety or {}).get("flags", [])} if draft else None,
            "warnings": draft.warnings if draft else [],
            "prompts": ((asset.imagination_prompts or {}).get("texts") or {}).get("en-IN") or [],
            "transcript": {"text": transcript.text, "confidence": transcript.confidence,
                           "reviewRequired": pipeline.transcript_review_required(db, asset, transcript)}
            if transcript else None,
            "fullReview": full_review_reasons(db, asset, draft, transcript),
        })
    db.commit()  # prepare_transcript may have cleaned a transcript once
    return {"groups": groups, "total": total, "items": items, "ageRanges": policy.AGE_RUBRIC}


class BatchApproval(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    titles: dict[str, str] = Field(default_factory=dict)
    teasers: dict[str, str] = Field(default_factory=dict)  # short teaser by language; the long one is kept
    age: str = Field(min_length=1, max_length=20)
    moral: str = Field(min_length=1, max_length=500)
    keepPrompts: bool = True
    transcriptChecked: bool = False  # the editor read the transcript: captions can be shown
    checked: bool = False  # listened to start, middle and end; age, voice and teaser confirmed


@router.post("/{asset_id}/publish")
def approve(asset_id: str, payload: BatchApproval, identity: Identity = Depends(EDITOR), db: Session = Depends(get_db)):
    if not payload.checked:
        raise HTTPException(status_code=409, detail={"error": "Not ready to publish.",
                                                     "problems": ["Listen to the start, middle and end, then tick the checks."]})
    asset = db.get(AudioAsset, asset_id)
    if not asset or asset.narrator_user_id:
        raise HTTPException(status_code=404, detail="Catalog story not found.")
    draft, transcript = pipeline.latest_draft(db, asset.id), pipeline.latest_transcript(db, asset.id)
    reasons = full_review_reasons(db, asset, draft, transcript)
    if reasons:
        raise HTTPException(status_code=409, detail={"error": "Open the full review.", "problems": reasons})
    teasers = {}
    for language, short in payload.teasers.items():
        current = (draft.alternates or {}).get(language, {}) if language != draft.language else \
            {"long": draft.long_text}
        teasers[language] = TeaserText(short=short, long=current.get("long") or "")
    rights = db.get(AssetRights, asset.id)
    request = PublishRequest(
        metadata={"title": payload.title.strip(), "audienceAgeRange": payload.age, "moralTakeaway": payload.moral.strip(),
                  "sourceAdaptation": asset.source_adaptation or "KathaChepta"},
        teaser=teasers, transcript=TranscriptDecision(reviewed=payload.transcriptChecked),
        rights=None if rights and rights.status == "approved" else "owned",
        checklist=sorted(policy.required_checklist_ids()), captionsEnabled=payload.transcriptChecked,
        titles=payload.titles,
        prompts=((asset.imagination_prompts or {}).get("texts") or {}) if payload.keepPrompts else
        {lang: [] for lang in titles.UI_LANGUAGES},
        notes="Batch review",
    )
    return publish_story(asset_id, request, identity, db)

