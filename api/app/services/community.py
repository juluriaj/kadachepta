"""Written reviews, reports, follows, and publish notifications (P3-03, P3-04, P3-09).

Reviews are for adults only and never shown on child profiles (Epic S). Every review gets a quick
pattern check (phone numbers, emails, links) and then the local model's check; what the model allows is
published, what it is unsure about waits for an editor, and two reports from different households hide
a review until an editor looks. Narrators can reply once per review.

Notifications are opt-in per account and never about streaks: a new story from a followed narrator, or the
next chapter of a series the family has been listening to.
"""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from .. import jobs
from ..auth import utcnow
from ..models import (
    AudioAsset, Household, Job, ListeningProgress, NarratorFollow, Notification, Profile, Review, ReviewReport, User,
)
from . import pipeline, recommend, titles
from . import settings as app_settings

PERSONAL = re.compile(r"(\+?\d[\d\s-]{8,}\d|[\w.+-]+@[\w-]+\.[a-z]{2,}|https?://|www\.)", re.I)
# A child's school or class, which the local model let through in testing: always an editor's call (Epic S).
CHILD_DETAILS = re.compile(r"\b(school|class\s*\d|grade\s*\d|std\.?\s*\d|lives? (in|at)|address)\b|స్కూల్|పాఠశాల|తరగతి", re.I)
REPORT_REASONS = ("inappropriate", "personal-info", "spam", "unkind", "other")
HIDE_AFTER_REPORTS = 2
MAX_REVIEW_CHARS = 1000
NOTIFY_KEYS = ("followed", "series")  # account preferences, all off until the parent turns them on


def submit_review(db: Session, profile: Profile, asset: AudioAsset, text: str) -> Review:
    text = " ".join(text.split())[:MAX_REVIEW_CHARS]
    review = db.scalars(select(Review).where(Review.profile_id == profile.id, Review.audio_asset_id == asset.id)).first()
    if review is None:
        review = Review(profile_id=profile.id, household_id=profile.household_id, audio_asset_id=asset.id, text=text)
        db.add(review)
    review.text, review.status, review.moderation = text, "pending", {}
    db.flush()
    if match := PERSONAL.search(text) or CHILD_DETAILS.search(text):
        review.status = "held"
        review.moderation = {"verdict": "hold", "reasons": ["personal-info"], "by": "pattern",
                             "note": f"Looks like contact details, a link, or a child's school: “{match.group(0)[:40]}”"}
        return review
    active = db.scalars(select(Job).where(Job.job_type == "review.moderate", Job.status.in_(jobs.ACTIVE_STATUSES),
                                         Job.payload["reviewId"].astext == str(review.id))).first()
    if not active:
        jobs.enqueue(db, "review.moderate", asset_id=asset.id, payload={"reviewId": review.id},
                     created_by=f"profile:{profile.id}", priority=jobs.PRIORITY_INTERACTIVE)
    return review


def apply_moderation(db: Session, review: Review, result: dict[str, Any]) -> None:
    """The local model only ever publishes: anything it doubts, or would block, goes to an editor, who alone rejects.
    (In testing the 8B model blocked merely rude reviews and listed every category as a reason when allowing.)"""
    verdict = result.get("verdict") if result.get("verdict") in ("allow", "hold", "block") else "hold"
    review.moderation = {"verdict": verdict, "reasons": [] if verdict == "allow" else result.get("reasons", []),
                         "note": result.get("note", ""), "by": f"ai:{result.get('model', 'unknown')}"}
    auto = verdict == "allow" and app_settings.get(db, "community.autoPublishReviews")
    review.status = "published" if auto else "held"


def report_review(db: Session, review: Review, household_id: int, reason: str) -> int:
    db.execute(insert(ReviewReport).values(review_id=review.id, household_id=household_id, reason=reason)
               .on_conflict_do_nothing())
    reports = db.scalar(select(func.count()).select_from(ReviewReport).where(ReviewReport.review_id == review.id)) or 0
    if reports >= HIDE_AFTER_REPORTS and review.status == "published":
        review.status = "held"
        review.moderation = {**(review.moderation or {}), "heldForReports": reports}
    return reports


def review_payload(review: Review, *, mine: bool = False) -> dict[str, Any]:
    payload = {"id": review.id, "text": review.text, "author": review.profile.name.split()[0] if review.profile else "",
               "createdAt": review.created_at.isoformat(), "reply": review.reply,
               "replyAt": review.reply_at.isoformat() if review.reply_at else None, "mine": mine}
    if mine:
        payload["status"] = review.status
    return payload


def preferences(user: User) -> dict[str, bool]:
    stored = (user.contact_preferences or {}).get("notifications") or {}
    return {key: bool(stored.get(key, False)) for key in NOTIFY_KEYS}


def _wants(db: Session, user_ids: set[int], key: str) -> set[int]:
    if not user_ids:
        return set()
    return {user.id for user in db.scalars(select(User).where(User.id.in_(user_ids))) if preferences(user)[key]}


def notify_published(db: Session, asset: AudioAsset) -> int:
    """Opt-in listener notifications when a story is published. Returns how many were sent."""
    sent: set[int] = set()
    title = titles.confirmed_titles(asset).get("en-IN") or asset.title
    if asset.narrator_user_id:
        followers = set(db.scalars(select(NarratorFollow.user_id).where(
            NarratorFollow.narrator_user_id == asset.narrator_user_id)))
        for user_id in _wants(db, followers, "followed") - {asset.narrator_user_id}:
            db.add(Notification(user_id=user_id, kind="new-from-followed", title=f"New story: {title}",
                                audio_asset_id=asset.id))
            sent.add(user_id)
    same_series = (AudioAsset.series_id == asset.series_id) if asset.series_id else (
        AudioAsset.album == asset.album if asset.album else None)
    if same_series is not None:
        earlier = select(AudioAsset.id).where(same_series, AudioAsset.id != asset.id, AudioAsset.status == "published")
        owners = set(db.scalars(select(Household.owner_user_id).join(Profile, Profile.household_id == Household.id)
                                .join(ListeningProgress, ListeningProgress.profile_id == Profile.id)
                                .where(ListeningProgress.audio_asset_id.in_(earlier),
                                       or_(ListeningProgress.completed.is_(True), ListeningProgress.seconds_listened >= 300))))
        for user_id in _wants(db, owners, "series") - sent - {asset.narrator_user_id}:
            db.add(Notification(user_id=user_id, kind="series-next", title=f"Next in the series: {title}",
                                audio_asset_id=asset.id))
            sent.add(user_id)
    return len(sent)


def ensure_ai_extras(db: Session, asset: AudioAsset, actor: str, priority: int = jobs.PRIORITY_DEFAULT) -> list[str]:
    """Queue what a published story still needs from the local models: its recommendation embedding (whenever
    its description changed) and conversation starters (once). Returns the job types queued."""
    queued = []
    draft = pipeline.latest_draft(db, asset.id)
    model = app_settings.get(db, "ai.embeddings.model")
    if recommend.needs_embedding(db, asset, draft, model) and not jobs.active_job(db, asset.id, "embed"):
        jobs.enqueue(db, "embed", asset_id=asset.id, created_by=actor, priority=priority)
        queued.append("embed")
    if not (asset.imagination_prompts or {}).get("texts") and not jobs.active_job(db, asset.id, "prompts") \
            and not pipeline.tried_once(db, asset.id, "prompts"):
        jobs.enqueue(db, "prompts", asset_id=asset.id, created_by=actor, priority=priority)
        queued.append("prompts")
    return queued


def mark_reply(review: Review, text: str) -> None:
    review.reply = " ".join(text.split())[:MAX_REVIEW_CHARS] or None
    review.reply_at = utcnow() if review.reply else None
