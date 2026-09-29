"""Studio tools for Phase 3: review moderation and rating spikes, collections, conversation starters, and the
catalog refresh that queues recommendations and conversation starters for published stories.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session, selectinload

from .. import jobs
from ..auth import Identity, require, utcnow
from ..db import get_db
from ..models import (
    AudioAsset, Collection, CollectionItem, EditorialEvent, Job, RatingFlag, Review, ReviewReport, StoryEmbedding, StoryRating,
)
from ..services import community, ratings, titles
from ..services.assets import artwork_url, iso
from .studio import _approve_prompts  # the same rule as the review screen

router = APIRouter(prefix="/api/studio", tags=["studio"])
EDITOR = require("content.publish")


def _event(db: Session, entity_id: str, action: str, actor: str, notes: str | None = None) -> None:
    db.add(EditorialEvent(entity_type="community", entity_id=entity_id, action=action, actor=actor, notes=notes))


# --- Moderation (P3-02, P3-03) ---

@router.get("/moderation")
def moderation(identity: Identity = Depends(EDITOR), db: Session = Depends(get_db)):
    """Reviews waiting for an editor (held, reported, or stuck waiting for the automatic check) and rating spikes."""
    stale = utcnow().timestamp() - 3600
    reports = dict(db.execute(select(ReviewReport.review_id, func.count()).group_by(ReviewReport.review_id)).all())
    reasons: dict[int, list[str]] = {}
    for review_id, reason in db.execute(select(ReviewReport.review_id, ReviewReport.reason)):
        reasons.setdefault(review_id, []).append(reason)
    rows = db.execute(select(Review, AudioAsset).options(selectinload(Review.profile))
                      .join(AudioAsset, AudioAsset.id == Review.audio_asset_id)
                      .where((Review.status.in_(("held", "pending"))) | (Review.id.in_(list(reports) or [0])))
                      .order_by(Review.created_at)).all()
    items = [{**community.review_payload(review), "status": review.status, "moderation": review.moderation,
              "reports": reports.get(review.id, 0), "reportReasons": sorted(set(reasons.get(review.id, []))),
              "waitingForCheck": review.status == "pending" and review.created_at.timestamp() < stale,
              "story": {"id": asset.id, "title": asset.title, "artworkUrl": artwork_url(asset)}}
             for review, asset in rows if review.status != "pending" or review.created_at.timestamp() < stale
             or reports.get(review.id)]
    flags = db.execute(select(RatingFlag, AudioAsset).join(AudioAsset, AudioAsset.id == RatingFlag.audio_asset_id)
                       .where(RatingFlag.status == "open").order_by(RatingFlag.created_at)).all()
    return {"reviews": items,
            "ratingFlags": [{"id": flag.id, "details": flag.details, "windowStart": iso(flag.window_start),
                             "createdAt": iso(flag.created_at),
                             "story": {"id": asset.id, "title": asset.title, "artworkUrl": artwork_url(asset)}}
                            for flag, asset in flags]}


class ReviewDecision(BaseModel):
    decision: Literal["publish", "hide", "reject"]


@router.post("/reviews/{review_id}")
def decide_review(review_id: int, payload: ReviewDecision, identity: Identity = Depends(EDITOR),
                  db: Session = Depends(get_db)):
    review = db.get(Review, review_id)
    if not review:
        raise HTTPException(status_code=404, detail="Review not found.")
    review.status = {"publish": "published", "hide": "hidden", "reject": "rejected"}[payload.decision]
    review.moderation = {**(review.moderation or {}), "editor": identity.username, "editorDecision": payload.decision}
    if payload.decision == "publish":  # reports were looked at: start counting afresh
        db.query(ReviewReport).filter(ReviewReport.review_id == review.id).delete()
    _event(db, str(review.id), f"review:{payload.decision}", identity.username)
    db.commit()
    return {"ok": True, "status": review.status}


class FlagDecision(BaseModel):
    decision: Literal["clear", "confirm"]


@router.post("/rating-flags/{flag_id}")
def decide_flag(flag_id: int, payload: FlagDecision, identity: Identity = Depends(EDITOR), db: Session = Depends(get_db)):
    """clear: the burst was genuine, count those ratings. confirm: brigading, leave them out of every score."""
    flag = db.get(RatingFlag, flag_id)
    if not flag or flag.status != "open":
        raise HTTPException(status_code=404, detail="Open rating alert not found.")
    flag.status = "cleared" if payload.decision == "clear" else "confirmed"
    flag.resolved_by, flag.resolved_at = identity.username, utcnow()
    if payload.decision == "confirm":
        db.execute(update(StoryRating).where(StoryRating.audio_asset_id == flag.audio_asset_id,
                                             StoryRating.created_at >= flag.window_start).values(excluded=True))
    _event(db, flag.audio_asset_id, f"ratings:{flag.status}", identity.username, str(flag.details))
    db.commit()
    return {"ok": True, "status": flag.status}


# --- Collections and editorial shelves (P3-08) ---

class CollectionIn(BaseModel):
    kind: Literal["festival", "theme", "age"] = "theme"
    titles: dict[str, str] = Field(default_factory=dict)
    descriptions: dict[str, str] = Field(default_factory=dict)
    startsOn: date | None = None
    endsOn: date | None = None
    position: int = 0
    published: bool = False
    assetIds: list[str] = Field(default_factory=list, max_length=200)


def _collection_payload(collection: Collection, assets: dict[str, AudioAsset]) -> dict[str, Any]:
    return {"id": collection.id, "kind": collection.kind, "titles": collection.titles,
            "descriptions": collection.descriptions, "startsOn": collection.starts_on.isoformat() if collection.starts_on else None,
            "endsOn": collection.ends_on.isoformat() if collection.ends_on else None, "position": collection.position,
            "published": collection.published,
            "stories": [{"id": item.audio_asset_id, "title": assets[item.audio_asset_id].title,
                         "status": assets[item.audio_asset_id].status,
                         "artworkUrl": artwork_url(assets[item.audio_asset_id])}
                        for item in collection.items if item.audio_asset_id in assets]}


@router.get("/collections")
def collections(identity: Identity = Depends(EDITOR), db: Session = Depends(get_db)):
    rows = list(db.scalars(select(Collection).options(selectinload(Collection.items))
                           .order_by(Collection.position, Collection.id)))
    ids = {item.audio_asset_id for collection in rows for item in collection.items}
    assets = {a.id: a for a in db.scalars(select(AudioAsset).where(AudioAsset.id.in_(ids or {""})))}
    published = db.execute(select(AudioAsset.id, AudioAsset.title).where(AudioAsset.status == "published")
                           .order_by(AudioAsset.title)).all()
    return {"items": [_collection_payload(c, assets) for c in rows],
            "stories": [{"id": asset_id, "title": title} for asset_id, title in published]}


def _save_collection(db: Session, collection: Collection, payload: CollectionIn) -> None:
    clean = {lang: text.strip()[:120] for lang, text in payload.titles.items() if lang in titles.UI_LANGUAGES and text.strip()}
    if not clean:
        raise HTTPException(status_code=422, detail="Give the collection a title (Telugu, English, or both).")
    if payload.startsOn and payload.endsOn and payload.endsOn < payload.startsOn:
        raise HTTPException(status_code=422, detail="The collection ends before it starts.")
    collection.kind, collection.titles, collection.position, collection.published = (
        payload.kind, clean, payload.position, payload.published)
    collection.descriptions = {lang: text.strip()[:400] for lang, text in payload.descriptions.items()
                               if lang in titles.UI_LANGUAGES and text.strip()}
    collection.starts_on, collection.ends_on = payload.startsOn, payload.endsOn
    unique = list(dict.fromkeys(payload.assetIds))
    known = set(db.scalars(select(AudioAsset.id).where(AudioAsset.id.in_(unique or [""]))))
    collection.items = [CollectionItem(audio_asset_id=asset_id, position=index)
                        for index, asset_id in enumerate(a for a in unique if a in known)]


@router.post("/collections", status_code=201)
def create_collection(payload: CollectionIn, identity: Identity = Depends(EDITOR), db: Session = Depends(get_db)):
    collection = Collection(created_by=identity.username)
    db.add(collection)
    _save_collection(db, collection, payload)
    db.flush()
    _event(db, f"collection:{collection.id}", "collection:created", identity.username)
    db.commit()
    return {"id": collection.id}


@router.post("/collections/{collection_id}")
def update_collection(collection_id: int, payload: CollectionIn, identity: Identity = Depends(EDITOR),
                      db: Session = Depends(get_db)):
    collection = db.get(Collection, collection_id)
    if not collection:
        raise HTTPException(status_code=404, detail="Collection not found.")
    _save_collection(db, collection, payload)
    _event(db, f"collection:{collection.id}", "collection:updated", identity.username)
    db.commit()
    return {"id": collection.id}


@router.delete("/collections/{collection_id}")
def delete_collection(collection_id: int, identity: Identity = Depends(EDITOR), db: Session = Depends(get_db)):
    collection = db.get(Collection, collection_id)
    if collection:
        db.delete(collection)
        _event(db, f"collection:{collection_id}", "collection:deleted", identity.username)
        db.commit()
    return {"ok": True}


# --- Conversation starters (P3-07) ---

@router.get("/prompts")
def prompts(identity: Identity = Depends(EDITOR), db: Session = Depends(get_db)):
    rows = db.scalars(select(AudioAsset).where(AudioAsset.status == "published").order_by(AudioAsset.title)).all()
    pending = set(db.scalars(select(AudioAsset.id).join(Job, Job.audio_asset_id == AudioAsset.id)
                             .where(Job.job_type == "prompts", Job.status.in_(jobs.ACTIVE_STATUSES))))
    return {"languages": list(titles.UI_LANGUAGES), "items": [
        {"id": a.id, "title": a.title, "titles": titles.confirmed_titles(a), "prompts": a.imagination_prompts or {},
         "pending": a.id in pending} for a in rows]}


class PromptsIn(BaseModel):
    texts: dict[str, list[str]]


@router.post("/prompts/{asset_id}")
def save_prompts(asset_id: str, payload: PromptsIn, identity: Identity = Depends(EDITOR), db: Session = Depends(get_db)):
    asset = db.get(AudioAsset, asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail="Story not found.")
    _approve_prompts(asset, payload.texts, identity.username)
    _event(db, asset.id, "prompts:approved", identity.username)
    db.commit()
    return {"prompts": asset.imagination_prompts}


# --- Catalog refresh: recommendations and conversation starters for what's already published ---

@router.post("/community/refresh", status_code=202)
def refresh(identity: Identity = Depends(EDITOR), db: Session = Depends(get_db)):
    queued: dict[str, int] = {}
    for asset in db.scalars(select(AudioAsset).where(AudioAsset.status == "published")):
        for job_type in community.ensure_ai_extras(db, asset, identity.username, priority=jobs.PRIORITY_BULK):
            queued[job_type] = queued.get(job_type, 0) + 1
    embedded = db.scalar(select(func.count()).select_from(StoryEmbedding)) or 0
    _event(db, "catalog", "community:refresh", identity.username, str(queued))
    db.commit()
    return {"queued": queued, "embedded": embedded}


@router.get("/ratings")
def rating_overview(identity: Identity = Depends(EDITOR), db: Session = Depends(get_db)):
    """Scores per published story and per narrator, as listeners see them (and as payouts will use them)."""
    stories = db.execute(select(AudioAsset.id, AudioAsset.title, AudioAsset.narrator_user_id)
                         .where(AudioAsset.status == "published")).all()
    scores = ratings.story_scores(db, [row[0] for row in stories])
    return {"stories": [{"id": asset_id, "title": title, **scores[asset_id]} for asset_id, title, _ in stories]}
