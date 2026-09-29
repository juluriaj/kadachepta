"""Ratings that can later feed narrator payouts (P3-01, P3-02), so they have to resist gaming.

- Only genuine listeners rate: the profile (or, for a parent rating on a young child's behalf, a child in the
  same household) must have listened to most of the story.
- One rating per household member per story; children tap an emoji reaction instead of stars. Reactions are
  shown to parents but kept out of the scores (a 4-year-old's taps are not a quality signal).
- Each rating carries the rater's trust weight (account age, how much the household actually listens).
- Displayed scores are Bayesian averages: a story with two 5-star ratings doesn't outrank one with two hundred
  4.6s, and a handful of fake accounts can't move an established score far.
- A sudden burst of ratings is held out of the scores until an editor looks (rating_flags).
- Narrators and staff can't rate their own work.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..auth import utcnow
from ..models import AudioAsset, ListeningProgress, Profile, RatingFlag, StoryRating, User

REACTIONS = ("love", "like", "okay", "sleepy")  # 😍 🙂 😐 😴
PRIOR_WEIGHT = 5.0  # how many "average" ratings every score starts with
DEFAULT_MEAN = 4.0  # the prior before the catalog has enough ratings of its own
MIN_WEIGHT_TO_SHOW = 3.0  # below this, show "not enough ratings yet"
LISTEN_SHARE = 0.6  # share of the story that must have been heard
SPIKE_WINDOW = timedelta(hours=48)
SPIKE_MIN_COUNT = 8


def listened_enough(row: ListeningProgress | None, duration: float) -> bool:
    """Real listening time, not a seek to the end: 60% heard, or finished with at least 30% heard."""
    if row is None or not duration:
        return False
    heard = row.seconds_listened or 0
    return heard >= LISTEN_SHARE * duration or (row.completed and heard >= 0.3 * duration)


def eligible(db: Session, profile: Profile, asset: AudioAsset) -> bool:
    """Adults may rate what they or a child in the household listened to (parents rate for young children)."""
    profile_ids = [profile.id]
    if profile.kind == "adult":
        profile_ids += [p.id for p in profile.household.profiles if p.kind == "child" and not p.deleted_at]
    rows = db.scalars(select(ListeningProgress).where(ListeningProgress.profile_id.in_(profile_ids),
                                                      ListeningProgress.audio_asset_id == asset.id))
    return any(listened_enough(row, asset.duration_seconds or 0) for row in rows)


def own_work(profile: Profile, asset: AudioAsset, owner: User | None) -> bool:
    return bool(owner and (owner.role in ("editor", "admin") or
                           (asset.narrator_user_id and owner.id == asset.narrator_user_id)))


def rater_weight(db: Session, profile: Profile) -> float:
    """0.2 for a brand-new account that has barely listened, up to 1.0 for an established listening household."""
    household = profile.household
    age_days = (utcnow() - household.created_at).total_seconds() / 86400 if household.created_at else 0
    profile_ids = [p.id for p in household.profiles]
    seconds, finished = db.execute(
        select(func.coalesce(func.sum(ListeningProgress.seconds_listened), 0),
               func.count().filter(ListeningProgress.completed))
        .where(ListeningProgress.profile_id.in_(profile_ids))).one()
    weight = 0.2 + 0.2 * min(age_days / 14, 1) + 0.3 * min(finished / 5, 1) + 0.3 * min(float(seconds) / 18000, 1)
    return round(min(weight, 1.0), 3)


def _held_since(db: Session, asset_ids: list[str]) -> dict[str, Any]:
    """Open spike flags: ratings made after the window start stay out of the score until an editor decides."""
    rows = db.execute(select(RatingFlag.audio_asset_id, func.min(RatingFlag.window_start))
                      .where(RatingFlag.audio_asset_id.in_(asset_ids), RatingFlag.status == "open")
                      .group_by(RatingFlag.audio_asset_id)).all()
    return dict(rows)


def _counted(db: Session, asset_ids: list[str]):
    held = _held_since(db, asset_ids)
    rows = db.scalars(select(StoryRating).where(StoryRating.audio_asset_id.in_(asset_ids), StoryRating.excluded.is_(False)))
    for rating in rows:
        since = held.get(rating.audio_asset_id)
        if since is None or rating.created_at < since:
            yield rating


def catalog_mean(db: Session, column) -> float:
    total, weight = db.execute(select(func.sum(column * StoryRating.weight), func.sum(StoryRating.weight))
                               .where(column.is_not(None), StoryRating.excluded.is_(False))).one()
    if not weight or weight < 20:
        return DEFAULT_MEAN
    return float(total) / float(weight)


def _score(ratings: list[tuple[int, float]], prior: float) -> dict[str, Any]:
    weight = sum(w for _, w in ratings)
    if not ratings:
        return {"score": None, "count": 0, "weight": 0.0}
    value = (PRIOR_WEIGHT * prior + sum(r * w for r, w in ratings)) / (PRIOR_WEIGHT + weight)
    return {"score": round(value, 2) if weight >= MIN_WEIGHT_TO_SHOW else None, "count": len(ratings),
            "weight": round(weight, 2)}


def story_scores(db: Session, asset_ids: list[str]) -> dict[str, dict[str, Any]]:
    """{asset_id: {"story": {score, count, weight}, "narration": {...}, "reactions": {love: n, ...}}}"""
    if not asset_ids:
        return {}
    story_prior, narration_prior = catalog_mean(db, StoryRating.story_rating), catalog_mean(db, StoryRating.narration_rating)
    collected: dict[str, dict[str, list]] = {a: {"story": [], "narration": [], "reactions": []} for a in asset_ids}
    for rating in _counted(db, asset_ids):
        bucket = collected[rating.audio_asset_id]
        if rating.story_rating:
            bucket["story"].append((rating.story_rating, rating.weight))
        if rating.narration_rating:
            bucket["narration"].append((rating.narration_rating, rating.weight))
        if rating.reaction:
            bucket["reactions"].append(rating.reaction)
    return {asset_id: {"story": _score(b["story"], story_prior), "narration": _score(b["narration"], narration_prior),
                       "reactions": {r: b["reactions"].count(r) for r in REACTIONS if r in b["reactions"]}}
            for asset_id, b in collected.items()}


def narrator_scores(db: Session, narrator_ids: list[int] | None = None) -> dict[int, dict[str, Any]]:
    """Narration quality per narrator across all their published stories: the number payouts will weight by."""
    query = select(AudioAsset.id, AudioAsset.narrator_user_id).where(
        AudioAsset.status == "published", AudioAsset.narrator_user_id.is_not(None))
    if narrator_ids is not None:
        query = query.where(AudioAsset.narrator_user_id.in_(narrator_ids))
    owner = dict(db.execute(query).all())
    prior = catalog_mean(db, StoryRating.narration_rating)
    collected: dict[int, list[tuple[int, float]]] = {}
    for rating in _counted(db, list(owner)):
        if rating.narration_rating:
            collected.setdefault(owner[rating.audio_asset_id], []).append((rating.narration_rating, rating.weight))
    narrators = set(owner.values()) if narrator_ids is None else set(narrator_ids)
    return {narrator: _score(collected.get(narrator, []), prior) for narrator in narrators}


def check_spike(db: Session, asset_id: str) -> RatingFlag | None:
    """Flag a burst: many ratings in 48 hours, far above the story's usual pace, that shift its average."""
    now = utcnow()
    window_start = now - SPIKE_WINDOW
    if db.scalar(select(RatingFlag.id).where(RatingFlag.audio_asset_id == asset_id, RatingFlag.status == "open")):
        return None
    ratings = list(db.scalars(select(StoryRating).where(
        StoryRating.audio_asset_id == asset_id, StoryRating.excluded.is_(False),
        StoryRating.created_at >= now - timedelta(days=30), StoryRating.story_rating.is_not(None))))
    recent = [r for r in ratings if r.created_at >= window_start]
    before = [r for r in ratings if r.created_at < window_start]
    if len(recent) < SPIKE_MIN_COUNT:
        return None
    usual = len(before) / 14  # ratings per 48 hours over the previous 28 days
    if len(recent) < 3 * usual + 5:
        return None
    recent_mean = sum(r.story_rating for r in recent) / len(recent)
    before_mean = sum(r.story_rating for r in before) / len(before) if before else None
    new_accounts = sum(1 for r in recent if r.weight <= 0.45)
    if before_mean is not None and abs(recent_mean - before_mean) < 0.75 and new_accounts < len(recent) / 2:
        return None  # busy but consistent with what listeners already said: a popular week, not a raid
    flag = RatingFlag(audio_asset_id=asset_id, window_start=window_start, details={
        "recent": len(recent), "usualPer48h": round(usual, 1), "recentMean": round(recent_mean, 2),
        "beforeMean": round(before_mean, 2) if before_mean is not None else None, "newAccounts": new_accounts})
    db.add(flag)
    return flag
