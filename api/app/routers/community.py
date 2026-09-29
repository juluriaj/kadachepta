"""Listener community API (Phase 3): ratings, reviews, narrator pages and follows, search, and updates.

Child profiles only ever see and send an emoji reaction: no reviews, no follows, no updates (Epic S).
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from ..auth import Identity, require, utcnow
from ..db import get_db
from ..models import (
    AudioAsset, NarratorFollow, NarratorProfile, Notification, Profile, Review, StoryRating, User,
)
from ..services import community, ratings, search
from ..services.assets import iso
from ..services.households import current_profile
from .listener import _favorite_set, _progress_map, published_stories, story_card

router = APIRouter(tags=["community"])


def _story(db: Session, profile: Profile, asset_id: str):
    match = next(((a, t) for a, t in published_stories(db, profile) if a.id == asset_id), None)
    if not match:
        raise HTTPException(status_code=404, detail="This story isn't available for this listener.")
    return match


def _owner(db: Session, profile: Profile) -> User | None:
    return db.get(User, profile.household.owner_user_id)


def community_payload(db: Session, profile: Profile, asset: AudioAsset) -> dict[str, Any]:
    scores = ratings.story_scores(db, [asset.id])[asset.id]
    mine = db.scalars(select(StoryRating).where(StoryRating.profile_id == profile.id,
                                                StoryRating.audio_asset_id == asset.id)).first()
    child = profile.kind == "child"
    own = ratings.own_work(profile, asset, _owner(db, profile))
    payload: dict[str, Any] = {
        "kind": profile.kind,
        "eligible": ratings.eligible(db, profile, asset) and not own,
        "ownWork": own,
        "mine": {"story": mine.story_rating, "narration": mine.narration_rating, "reaction": mine.reaction} if mine else None,
        "reactions": scores["reactions"],
    }
    if child:
        return payload
    reviews = db.scalars(select(Review).options(selectinload(Review.profile))
                         .where(Review.audio_asset_id == asset.id, Review.status == "published")
                         .order_by(Review.created_at.desc()).limit(50)).all()
    my_review = db.scalars(select(Review).options(selectinload(Review.profile))
                           .where(Review.profile_id == profile.id, Review.audio_asset_id == asset.id)).first()
    payload.update(story=scores["story"], narration=scores["narration"],
                   reviews=[community.review_payload(r, mine=r.profile_id == profile.id) for r in reviews],
                   myReview=community.review_payload(my_review, mine=True) if my_review else None)
    return payload


@router.get("/api/stories/{asset_id}/community")
def story_community(asset_id: str, profile: Profile = Depends(current_profile), db: Session = Depends(get_db)):
    asset, _ = _story(db, profile, asset_id)
    return community_payload(db, profile, asset)


class RatingIn(BaseModel):
    story: int | None = Field(default=None, ge=1, le=5)
    narration: int | None = Field(default=None, ge=1, le=5)
    reaction: Literal["love", "like", "okay", "sleepy"] | None = None


@router.post("/api/stories/{asset_id}/rating")
def rate(asset_id: str, payload: RatingIn, profile: Profile = Depends(current_profile), db: Session = Depends(get_db)):
    asset, _ = _story(db, profile, asset_id)
    if ratings.own_work(profile, asset, _owner(db, profile)):
        raise HTTPException(status_code=403, detail="You can't rate your own narration or stories you edited.")
    if not ratings.eligible(db, profile, asset):
        raise HTTPException(status_code=409, detail="Listen to most of the story first, then rate it.")
    if profile.kind == "child" and (payload.story or payload.narration):
        raise HTTPException(status_code=422, detail="Children share how the story felt with a reaction.")
    if profile.kind == "adult" and payload.reaction:
        raise HTTPException(status_code=422, detail="Reactions are for children's profiles.")
    if not (payload.story or payload.narration or payload.reaction):
        raise HTTPException(status_code=422, detail="Choose a rating.")
    rating = db.scalars(select(StoryRating).where(StoryRating.profile_id == profile.id,
                                                  StoryRating.audio_asset_id == asset.id)).first()
    if rating is None:
        rating = StoryRating(profile_id=profile.id, household_id=profile.household_id, audio_asset_id=asset.id)
        db.add(rating)
    for field, value in (("story_rating", payload.story), ("narration_rating", payload.narration),
                         ("reaction", payload.reaction)):
        if value is not None:
            setattr(rating, field, value)
    rating.weight = ratings.rater_weight(db, profile)
    db.flush()
    ratings.check_spike(db, asset.id)
    db.commit()
    return community_payload(db, profile, asset)


class ReviewIn(BaseModel):
    text: str = Field(min_length=3, max_length=community.MAX_REVIEW_CHARS)


def _adult(profile: Profile) -> None:
    if profile.kind != "adult":
        raise HTTPException(status_code=403, detail="Reviews and follows are for grown-ups' profiles.")


@router.post("/api/stories/{asset_id}/review")
def write_review(asset_id: str, payload: ReviewIn, profile: Profile = Depends(current_profile),
                 db: Session = Depends(get_db)):
    _adult(profile)
    asset, _ = _story(db, profile, asset_id)
    if ratings.own_work(profile, asset, _owner(db, profile)):
        raise HTTPException(status_code=403, detail="You can't review your own narration.")
    if not ratings.eligible(db, profile, asset):
        raise HTTPException(status_code=409, detail="Listen to most of the story first, then review it.")
    community.submit_review(db, profile, asset, payload.text)
    db.commit()
    return community_payload(db, profile, asset)


@router.delete("/api/stories/{asset_id}/review")
def delete_review(asset_id: str, profile: Profile = Depends(current_profile), db: Session = Depends(get_db)):
    asset, _ = _story(db, profile, asset_id)
    db.query(Review).filter(Review.profile_id == profile.id, Review.audio_asset_id == asset.id).delete()
    db.commit()
    return community_payload(db, profile, asset)


class ReportIn(BaseModel):
    reason: Literal["inappropriate", "personal-info", "spam", "unkind", "other"]


@router.post("/api/reviews/{review_id}/report")
def report(review_id: int, payload: ReportIn, profile: Profile = Depends(current_profile), db: Session = Depends(get_db)):
    _adult(profile)
    review = db.get(Review, review_id)
    if not review or review.status != "published":
        raise HTTPException(status_code=404, detail="Review not found.")
    community.report_review(db, review, profile.household_id, payload.reason)
    db.commit()
    return {"ok": True}


# --- Narrator pages and follows (P3-04) ---

@router.get("/api/narrators/{user_id}")
def narrator_page(user_id: int, profile: Profile = Depends(current_profile), db: Session = Depends(get_db)):
    user = db.get(User, user_id)
    narrator = db.get(NarratorProfile, user_id)
    if not user or not narrator or user.role != "narrator":
        raise HTTPException(status_code=404, detail="Narrator not found.")
    stories = [(a, t) for a, t in published_stories(db, profile) if a.narrator_user_id == user_id]
    progress, favorites = _progress_map(db, profile), _favorite_set(db, profile)
    followers = db.scalar(select(func.count()).select_from(NarratorFollow).where(NarratorFollow.narrator_user_id == user_id))
    following = db.get(NarratorFollow, (profile.household.owner_user_id, user_id)) is not None
    score = ratings.narrator_scores(db, [user_id])[user_id]
    return {
        "id": user_id, "name": narrator.display_name or user.display_name or user.username,
        "biography": narrator.biography, "languages": narrator.languages, "since": iso(narrator.onboarded_at),
        "stories": [story_card(a, t, profile, progress.get(a.id), a.id in favorites) for a, t in stories],
        "narration": score if profile.kind == "adult" else None,
        "followers": followers or 0, "following": following, "canFollow": profile.kind == "adult",
    }


class FollowIn(BaseModel):
    following: bool


@router.post("/api/narrators/{user_id}/follow")
def follow(user_id: int, payload: FollowIn, profile: Profile = Depends(current_profile), db: Session = Depends(get_db)):
    _adult(profile)
    user = db.get(User, user_id)
    if not user or user.role != "narrator":
        raise HTTPException(status_code=404, detail="Narrator not found.")
    account = profile.household.owner_user_id
    current = db.get(NarratorFollow, (account, user_id))
    if payload.following and not current and account != user_id:
        db.add(NarratorFollow(user_id=account, narrator_user_id=user_id))
    elif not payload.following and current:
        db.delete(current)
    db.commit()
    return {"following": payload.following and account != user_id}


# --- Search (P3-05) ---

@router.get("/api/search")
def find(q: str = "", language: str | None = None, profile: Profile = Depends(current_profile),
         db: Session = Depends(get_db)):
    stories = [(a, t) for a, t in published_stories(db, profile) if not language or a.language == language]
    if not q.strip():
        return {"query": q, "items": []}
    progress, favorites = _progress_map(db, profile), _favorite_set(db, profile)
    results = search.search(q, stories)
    return {"query": q, "items": [{**story_card(a, t, profile, progress.get(a.id), a.id in favorites),
                                   "match": round(value, 2)} for a, t, value in results]}


# --- Updates for listeners (P3-09): opt-in, never for children, never about streaks ---

LISTENER_KINDS = ("new-from-followed", "series-next")


@router.get("/api/me/updates")
def updates(profile: Profile = Depends(current_profile), db: Session = Depends(get_db)):
    if profile.kind != "adult":
        return {"items": [], "unread": 0, "settings": None}
    account = profile.household.owner_user_id
    rows = db.scalars(select(Notification).where(Notification.user_id == account, Notification.kind.in_(LISTENER_KINDS))
                      .order_by(Notification.created_at.desc()).limit(50)).all()
    available = {a.id: (a, t) for a, t in published_stories(db, profile)}
    items = []
    for row in rows:
        if row.audio_asset_id not in available:
            continue
        asset, teaser = available[row.audio_asset_id]
        items.append({"id": row.id, "kind": row.kind, "read": row.read_at is not None, "createdAt": iso(row.created_at),
                      "story": story_card(asset, teaser, profile)})
    return {"items": items, "unread": sum(1 for item in items if not item["read"]),
            "settings": community.preferences(db.get(User, account))}


@router.post("/api/me/updates/read")
def read_updates(profile: Profile = Depends(current_profile), db: Session = Depends(get_db)):
    db.query(Notification).filter(Notification.user_id == profile.household.owner_user_id,
                                  Notification.kind.in_(LISTENER_KINDS), Notification.read_at.is_(None)
                                  ).update({"read_at": utcnow()}, synchronize_session=False)
    db.commit()
    return {"ok": True}


class NotifySettings(BaseModel):
    followed: bool | None = None
    series: bool | None = None


@router.post("/api/me/notification-settings")
def notification_settings(payload: NotifySettings, profile: Profile = Depends(current_profile),
                          db: Session = Depends(get_db)):
    _adult(profile)
    user = db.get(User, profile.household.owner_user_id)
    preferences = dict(user.contact_preferences or {})
    current = dict(preferences.get("notifications") or {})
    current.update({k: v for k, v in payload.model_dump().items() if v is not None})
    preferences["notifications"] = current
    user.contact_preferences = preferences
    db.commit()
    return community.preferences(user)


# --- Narrators: reviews of their stories and the right of reply (P3-03) ---

@router.get("/api/narrator/reviews")
def my_reviews(identity: Identity = Depends(require("narrator.upload")), db: Session = Depends(get_db)):
    rows = db.execute(select(Review, AudioAsset).options(selectinload(Review.profile))
                      .join(AudioAsset, AudioAsset.id == Review.audio_asset_id)
                      .where(AudioAsset.narrator_user_id == identity.user.id, Review.status == "published")
                      .order_by(Review.created_at.desc()).limit(200)).all()
    score = ratings.narrator_scores(db, [identity.user.id])[identity.user.id]
    stories = ratings.story_scores(db, list({asset.id for _, asset in rows}))
    return {"narration": score, "items": [{**community.review_payload(review), "storyId": asset.id,
                                           "storyTitle": asset.title, "story": stories[asset.id]["story"]}
                                          for review, asset in rows]}


class ReplyIn(BaseModel):
    text: str = Field(default="", max_length=community.MAX_REVIEW_CHARS)


@router.post("/api/narrator/reviews/{review_id}/reply")
def reply(review_id: int, payload: ReplyIn, identity: Identity = Depends(require("narrator.upload")),
          db: Session = Depends(get_db)):
    review = db.get(Review, review_id)
    asset = db.get(AudioAsset, review.audio_asset_id) if review else None
    if not review or not asset or asset.narrator_user_id != identity.user.id or review.status != "published":
        raise HTTPException(status_code=404, detail="Review not found.")
    if community.PERSONAL.search(payload.text):
        raise HTTPException(status_code=422, detail="Replies can't include phone numbers, emails, or links.")
    community.mark_reply(review, payload.text)
    db.commit()
    return community.review_payload(review)
