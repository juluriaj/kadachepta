"""Listener API: home shelves, stories, favorites, listening progress and stats (all per profile)."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import and_, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, selectinload
from starlette.concurrency import run_in_threadpool

from ..auth import utcnow
from ..db import get_db
from ..models import AudioAsset, ListenerFavorite, ListeningDaily, ListeningProgress, Profile, TeaserDraft
from ..services.assets import artwork_url, asset_payload, iso
from ..services.households import MOMENTS, current_profile, suitable_for

router = APIRouter(tags=["listener"])

MOMENT_WORDS = {
    "bedtime": ("bedtime", "night", "sleep", "lullaby", "calm", "soothing"),
    "drive": ("drive", "car", "travel", "road", "journey"),
    "run": ("run", "walk", "exercise", "workout", "commute"),
    "work": ("work", "focus", "study", "background"),
    "learn": ("learn", "education", "mythology", "history", "moral", "science", "values"),
}


def _approved_teaser_id():
    return (select(TeaserDraft.id).where(TeaserDraft.audio_asset_id == AudioAsset.id, TeaserDraft.status == "approved")
            .order_by(TeaserDraft.id.desc()).limit(1).correlate(AudioAsset).scalar_subquery())


def published_stories(db: Session, profile: Profile) -> list[tuple[AudioAsset, TeaserDraft]]:
    rows = db.execute(select(AudioAsset, TeaserDraft)
                      .join(TeaserDraft, TeaserDraft.id == _approved_teaser_id())
                      .where(AudioAsset.status == "published")
                      .options(selectinload(AudioAsset.narrator_user))
                      .order_by(AudioAsset.published_at.desc().nulls_last(), AudioAsset.title)).all()
    return [(asset, teaser) for asset, teaser in rows if suitable_for(profile, asset)]


def teaser_for(teaser: TeaserDraft, languages: list[str]) -> dict[str, Any]:
    """Pick the teaser in the listener's preferred language, falling back to the original."""
    options = {teaser.language: {"short": teaser.short_text, "long": teaser.long_text}}
    options.update({lang: value for lang, value in (teaser.alternates or {}).items() if value})
    for language in languages:
        if options.get(language, {}).get("long") or options.get(language, {}).get("short"):
            return {"language": language, **options[language]}
    return {"language": teaser.language, **options[teaser.language]}


def moments_of(asset: AudioAsset) -> list[str]:
    words = " ".join([*asset.listening_contexts, *asset.genres, asset.mood or ""]).lower()
    found = [moment for moment, keys in MOMENT_WORDS.items() if any(key in words for key in keys)]
    minutes = (asset.duration_seconds or 0) / 60
    if not asset.listening_contexts:  # heuristics only when editors haven't tagged contexts
        if minutes >= 10 and "drive" not in found:
            found.append("drive")
        if minutes >= 15 and "run" not in found:
            found.append("run")
    return [moment for moment in MOMENTS if moment in found]


def story_card(asset: AudioAsset, teaser: TeaserDraft, profile: Profile,
               progress: ListeningProgress | None = None, favorite: bool = False) -> dict[str, Any]:
    return asset_payload(
        asset, teaser=teaser_for(teaser, profile.listening_languages or [asset.language]),
        shortText=teaser.short_text, longText=teaser.long_text, moments=moments_of(asset), favorite=favorite,
        progress={"position": round(progress.last_position), "completed": progress.completed,
                  "lastListenedAt": iso(progress.last_listened_at)} if progress else None,
    )


def _progress_map(db: Session, profile: Profile) -> dict[str, ListeningProgress]:
    return {row.audio_asset_id: row for row in db.scalars(
        select(ListeningProgress).where(ListeningProgress.profile_id == profile.id))}


def _favorite_set(db: Session, profile: Profile) -> set[str]:
    return set(db.scalars(select(ListenerFavorite.audio_asset_id).where(ListenerFavorite.profile_id == profile.id)))


@router.get("/api/catalog")
def catalog(language: str | None = None, profile: Profile = Depends(current_profile), db: Session = Depends(get_db)):
    progress, favorites = _progress_map(db, profile), _favorite_set(db, profile)
    items = [story_card(asset, teaser, profile, progress.get(asset.id), asset.id in favorites)
             for asset, teaser in published_stories(db, profile) if not language or asset.language == language]
    return {"items": items}


@router.get("/api/home")
def home(profile: Profile = Depends(current_profile), db: Session = Depends(get_db)):
    stories = published_stories(db, profile)
    progress, favorites = _progress_map(db, profile), _favorite_set(db, profile)
    cards = {asset.id: story_card(asset, teaser, profile, progress.get(asset.id), asset.id in favorites)
             for asset, teaser in stories}
    order = list(cards)
    continuing = sorted((row for row in progress.values() if row.audio_asset_id in cards and not row.completed
                         and row.last_position >= 20), key=lambda row: row.last_listened_at, reverse=True)
    shelves = []
    if continuing:
        shelves.append({"id": "continue", "items": [cards[row.audio_asset_id] for row in continuing[:10]]})
    household_moments = profile.household.moments or list(MOMENTS)
    for moment in [m for m in MOMENTS if m in household_moments] + [m for m in MOMENTS if m not in household_moments]:
        items = [cards[asset_id] for asset_id in order if moment in cards[asset_id]["moments"]]
        if items:
            shelves.append({"id": moment, "moment": moment, "items": items[:20]})
    if favorites:
        shelves.append({"id": "favorites", "items": [cards[a] for a in order if a in favorites][:20]})
    shelves.append({"id": "short", "items": [cards[a] for a in order if (cards[a]["duration"] or 0) <= 600][:20]})
    shelves.append({"id": "new", "items": [cards[a] for a in order][:20]})
    return {"profileId": profile.id, "shelves": [shelf for shelf in shelves if shelf["items"]],
            "totalStories": len(cards)}


@router.get("/api/stories/{asset_id}")
def story(asset_id: str, profile: Profile = Depends(current_profile), db: Session = Depends(get_db)):
    stories = published_stories(db, profile)
    match = next(((asset, teaser) for asset, teaser in stories if asset.id == asset_id), None)
    if not match:
        raise HTTPException(status_code=404, detail="This story isn't available for this listener.")
    asset, teaser = match
    progress, favorites = _progress_map(db, profile), _favorite_set(db, profile)
    card = story_card(asset, teaser, profile, progress.get(asset.id), asset.id in favorites)
    series = sorted(((a, t) for a, t in stories if a.album and a.album == asset.album and a.id != asset.id),
                    key=lambda pair: (_episode_key(pair[0]), pair[0].title))
    later = [pair for pair in series if _episode_key(pair[0]) > _episode_key(asset)]
    same_narrator = [(a, t) for a, t in stories if a.id != asset.id and a.narrator_user_id
                     and a.narrator_user_id == asset.narrator_user_id][:10]
    return {**card, "themes": teaser.themes, "ageSuggestion": teaser.age_suggestion,
            "waveform": (asset.renditions or {}).get("waveform", []),
            "upNext": [story_card(a, t, profile, progress.get(a.id)) for a, t in (later or series)[:10]],
            "moreFromNarrator": [story_card(a, t, profile, progress.get(a.id)) for a, t in same_narrator]}


def _episode_key(asset: AudioAsset) -> tuple[int, str]:
    for value in (asset.episode_number, asset.track_number):
        digits = "".join(ch for ch in (value or "") if ch.isdigit())
        if digits:
            return (int(digits[:6]), "")
    return (0, asset.title)


class FavoriteChange(BaseModel):
    assetId: str | None = None
    assetIds: list[str] | None = Field(default=None, max_length=200)
    saved: bool = True


def _favorite_ids(db: Session, profile: Profile) -> list[str]:
    return list(db.scalars(
        select(ListenerFavorite.audio_asset_id)
        .join(AudioAsset, AudioAsset.id == ListenerFavorite.audio_asset_id)
        .where(ListenerFavorite.profile_id == profile.id, AudioAsset.status == "published")
        .order_by(ListenerFavorite.created_at.desc())))


@router.get("/api/me/favorites")
def get_favorites(profile: Profile = Depends(current_profile), db: Session = Depends(get_db)):
    return {"ids": _favorite_ids(db, profile)}


@router.post("/api/me/favorites")
def change_favorites(payload: FavoriteChange, profile: Profile = Depends(current_profile),
                     db: Session = Depends(get_db)):
    ids = [asset_id for asset_id in (payload.assetIds or [payload.assetId]) if asset_id]
    if not ids:
        raise HTTPException(status_code=400, detail="assetId is required.")
    if payload.saved:
        published = db.scalars(select(AudioAsset.id).where(AudioAsset.id.in_(ids), AudioAsset.status == "published"))
        rows = [{"profile_id": profile.id, "user_id": profile.household.owner_user_id, "audio_asset_id": asset_id}
                for asset_id in published]
        if rows:
            db.execute(insert(ListenerFavorite).values(rows).on_conflict_do_nothing())
    else:
        db.query(ListenerFavorite).filter(ListenerFavorite.profile_id == profile.id,
                                          ListenerFavorite.audio_asset_id.in_(ids)).delete()
    db.commit()
    return {"ids": _favorite_ids(db, profile)}


class ListeningReport(BaseModel):
    assetId: str
    seconds: float = 0
    screenOffSeconds: float = 0
    position: float = 0
    started: bool = False
    completed: bool = False
    day: str | None = None


def local_day(value: str | None) -> date:
    try:
        return date.fromisoformat(value) if value else utcnow().date()
    except ValueError:
        return utcnow().date()


@router.post("/api/me/listening")
async def report_listening(request: Request, profile: Profile = Depends(current_profile),
                           db: Session = Depends(get_db)):
    # sendBeacon posts a Blob, so parse the body ourselves rather than relying on the content type.
    try:
        payload = ListeningReport.model_validate_json(await request.body())
    except ValueError as error:
        raise HTTPException(status_code=400, detail=f"Invalid listening report: {error}") from error
    return await run_in_threadpool(_record_listening, payload, profile, db)


def _record_listening(payload: ListeningReport, profile: Profile, db: Session) -> dict:
    # Clients flush every ~15 s; cap one report so a bad client cannot inflate stats.
    seconds = min(max(payload.seconds, 0), 120)
    screen_off = min(max(payload.screenOffSeconds, 0), seconds)
    position = max(payload.position, 0)
    if not db.scalar(select(AudioAsset.id).where(AudioAsset.id == payload.assetId, AudioAsset.status == "published")):
        raise HTTPException(status_code=404, detail="Story not found.")
    now, user_id = utcnow(), profile.household.owner_user_id
    statement = insert(ListeningProgress).values(
        profile_id=profile.id, user_id=user_id, audio_asset_id=payload.assetId, seconds_listened=seconds,
        screen_off_seconds=screen_off, last_position=position, play_count=int(payload.started),
        completed=payload.completed, first_listened_at=now, last_listened_at=now)
    db.execute(statement.on_conflict_do_update(
        index_elements=[ListeningProgress.profile_id, ListeningProgress.audio_asset_id],
        set_={
            "seconds_listened": ListeningProgress.seconds_listened + statement.excluded.seconds_listened,
            "screen_off_seconds": ListeningProgress.screen_off_seconds + statement.excluded.screen_off_seconds,
            "last_position": statement.excluded.last_position,
            "play_count": ListeningProgress.play_count + statement.excluded.play_count,
            "completed": ListeningProgress.completed | statement.excluded.completed,
            "last_listened_at": statement.excluded.last_listened_at,
        }))
    if seconds:
        daily = insert(ListeningDaily).values(profile_id=profile.id, user_id=user_id, day=local_day(payload.day),
                                              seconds=seconds, screen_off_seconds=screen_off)
        db.execute(daily.on_conflict_do_update(
            index_elements=[ListeningDaily.profile_id, ListeningDaily.day],
            set_={"seconds": ListeningDaily.seconds + daily.excluded.seconds,
                  "screen_off_seconds": ListeningDaily.screen_off_seconds + daily.excluded.screen_off_seconds}))
    db.commit()
    return {"ok": True}


@router.get("/api/me/progress")
def progress(profile: Profile = Depends(current_profile), db: Session = Depends(get_db)):
    return {"items": {asset_id: {"position": round(row.last_position), "completed": row.completed,
                                 "lastListenedAt": iso(row.last_listened_at)}
                      for asset_id, row in _progress_map(db, profile).items()}}


def profile_stats(db: Session, profile_id: int, today: date) -> dict[str, Any]:
    total_seconds, screen_off, started, completed = db.execute(
        select(func.coalesce(func.sum(ListeningProgress.seconds_listened), 0),
               func.coalesce(func.sum(ListeningProgress.screen_off_seconds), 0), func.count(),
               func.count().filter(ListeningProgress.completed))
        .where(ListeningProgress.profile_id == profile_id)).one()
    week_seconds, week_screen_off = db.execute(
        select(func.coalesce(func.sum(ListeningDaily.seconds), 0), func.coalesce(func.sum(ListeningDaily.screen_off_seconds), 0))
        .where(ListeningDaily.profile_id == profile_id, ListeningDaily.day >= today - timedelta(days=6),
               ListeningDaily.day <= today)).one()
    days = list(db.scalars(select(ListeningDaily.day).where(
        ListeningDaily.profile_id == profile_id, ListeningDaily.seconds >= 60, ListeningDaily.day <= today)
        .order_by(ListeningDaily.day.desc())))
    streak, expected = 0, today
    if days and days[0] != today:
        expected = today - timedelta(days=1)  # an unbroken streak may end yesterday
    for listened in days:
        if listened != expected:
            break
        streak, expected = streak + 1, expected - timedelta(days=1)
    daily = {row.day: row.seconds for row in db.scalars(select(ListeningDaily).where(
        ListeningDaily.profile_id == profile_id, ListeningDaily.day >= today - timedelta(days=6)))}
    genre_seconds: dict[str, float] = {}
    for seconds, genres, genre in db.execute(
            select(ListeningProgress.seconds_listened, AudioAsset.genres, AudioAsset.genre)
            .join(AudioAsset, AudioAsset.id == ListeningProgress.audio_asset_id)
            .where(ListeningProgress.profile_id == profile_id)):
        for name in genres or ([genre] if genre else ["Other"]):
            genre_seconds[name] = genre_seconds.get(name, 0) + seconds
    recent = db.execute(
        select(ListeningProgress, AudioAsset).join(AudioAsset, AudioAsset.id == ListeningProgress.audio_asset_id)
        .where(ListeningProgress.profile_id == profile_id, AudioAsset.status == "published")
        .order_by(ListeningProgress.last_listened_at.desc()).limit(5)).all()
    favorites = db.scalar(select(func.count()).select_from(ListenerFavorite).join(
        AudioAsset, and_(AudioAsset.id == ListenerFavorite.audio_asset_id, AudioAsset.status == "published"))
        .where(ListenerFavorite.profile_id == profile_id))
    return {
        "totalSeconds": round(total_seconds), "weekSeconds": round(week_seconds),
        "screenOffShare": round(screen_off / total_seconds, 3) if total_seconds else None,
        "weekScreenOffShare": round(week_screen_off / week_seconds, 3) if week_seconds else None,
        "storiesStarted": started, "storiesCompleted": completed, "favorites": favorites, "streakDays": streak,
        "lastSevenDays": [{"day": (today - timedelta(days=offset)).isoformat(),
                           "seconds": round(daily.get(today - timedelta(days=offset), 0))} for offset in range(6, -1, -1)],
        "genres": [{"genre": name, "seconds": round(value)}
                   for name, value in sorted(genre_seconds.items(), key=lambda item: -item[1])],
        "recent": [{"id": asset.id, "title": asset.title, "seconds": round(row.seconds_listened),
                    "position": round(row.last_position), "duration": round(asset.duration_seconds or 0),
                    "completed": row.completed, "lastListenedAt": iso(row.last_listened_at),
                    "artworkUrl": artwork_url(asset)} for row, asset in recent],
    }


@router.get("/api/me/stats")
def stats(today: str | None = None, profile: Profile = Depends(current_profile), db: Session = Depends(get_db)):
    return profile_stats(db, profile.id, local_day(today))
