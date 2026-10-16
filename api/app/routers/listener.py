"""Listener API: home shelves, stories, story sets, audiobooks, favorites, listening progress and stats (all per
profile)."""

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
from ..models import (
    AudioAsset, Collection, ListenerFavorite, ListeningDaily, ListeningProgress, Profile, TeaserDraft, Transcript,
)
from ..services import morals, pipeline, ratings, recommend, story_sets
from ..services.assets import artwork_url, asset_payload, iso, narrator_people, person_key
from ..services.households import MOMENTS, current_profile, suitable_for
from ..services.transcripts import read_along

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


def active_collections(db: Session) -> list[Collection]:
    """Published editorial shelves in season (P3-08), in the editors' order."""
    today = utcnow().date()
    return list(db.scalars(select(Collection).options(selectinload(Collection.items))
                           .where(Collection.published.is_(True), Collection.kind != story_sets.SET_KIND,
                                  (Collection.starts_on.is_(None)) | (Collection.starts_on <= today),
                                  (Collection.ends_on.is_(None)) | (Collection.ends_on >= today))
                           .order_by(Collection.position, Collection.id)))


def teaser_texts(teaser: TeaserDraft) -> dict[str, dict[str, Any]]:
    """The teaser in every language it has: {"te-IN": {"short", "long"}, "en-IN": {...}}."""
    options = {teaser.language: {"short": teaser.short_text, "long": teaser.long_text}}
    options.update({lang: value for lang, value in (teaser.alternates or {}).items() if value})
    return {lang: {"short": value.get("short"), "long": value.get("long")}
            for lang, value in options.items() if value.get("long") or value.get("short")}


def teaser_for(teaser: TeaserDraft, languages: list[str]) -> dict[str, Any]:
    """Pick the teaser in the listener's preferred language, falling back to the original."""
    options = teaser_texts(teaser)
    for language in languages:
        if language in options:
            return {"language": language, **options[language]}
    return {"language": teaser.language, "short": teaser.short_text, "long": teaser.long_text}


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
        asset, narratorId=asset.narrator_user_id, narrators=narrator_people(asset),
        teaser=teaser_for(teaser, profile.listening_languages or [asset.language]),
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


def _cards(stories: list[tuple[AudioAsset, TeaserDraft]], profile: Profile, progress: dict[str, ListeningProgress],
           favorites: set[str], books: dict[int, story_sets.Book]) -> dict[str, dict[str, Any]]:
    """Story cards by id; a chapter's card says which book it belongs to ("Chapter 3 of 12")."""
    cards = {}
    for asset, teaser in stories:
        card = story_card(asset, teaser, profile, progress.get(asset.id), asset.id in favorites)
        if asset.series_id in books:
            card["book"] = books[asset.series_id].info(asset.id)
        cards[asset.id] = card
    return cards


@router.get("/api/home")
def home(profile: Profile = Depends(current_profile), db: Session = Depends(get_db)):
    stories = published_stories(db, profile)
    progress, favorites = _progress_map(db, profile), _favorite_set(db, profile)
    books = story_sets.books_of(db, stories)
    cards = _cards(stories, profile, progress, favorites, books)
    # Chapters are heard through their book: never shelved one by one as if they were stories.
    order = [asset.id for asset, _ in stories if not asset.series_id]
    standalone = set(order)
    continuing = [(row.last_listened_at, cards[row.audio_asset_id]) for row in progress.values()
                  if row.audio_asset_id in standalone and not row.completed and row.last_position >= 20]
    for book in books.values():  # one card per book: the chapter it resumes at
        summary = story_sets.book_summary(book, progress)
        if summary["resume"]["state"] == "continue":
            continuing.append((story_sets.last_listened(book, progress), cards[summary["resume"]["chapterId"]]))
    continuing.sort(key=lambda pair: pair[0], reverse=True)
    shelves = []
    if continuing:
        shelves.append({"id": "continue", "items": [card for _, card in continuing[:10]]})
    because = recommend.because_you_finished(db, profile.id, standalone)
    if because:
        shelves.append({"id": "because", "basedOn": cards[because["basedOn"]], "items": [cards[a] for a in because["items"]]})
    for collection in active_collections(db):
        items = [cards[item.audio_asset_id] for item in collection.items if item.audio_asset_id in cards]
        if items:
            shelves.append({"id": f"collection-{collection.id}", "collection": {
                "id": collection.id, "kind": collection.kind, "titles": collection.titles,
                "descriptions": collection.descriptions}, "items": items[:20]})
    sets = story_sets.listed_sets(db, stories)
    if sets:  # one tile per set, not a row of its stories
        shelves.append({"id": "sets", "items": [],
                        "sets": [story_sets.set_summary(c, members, progress) for c, members in sets]})
    if books:
        listed = sorted(books.values(), key=lambda b: (b.series.title.casefold(), b.series.id))
        shelves.append({"id": "books", "items": [], "books": [story_sets.book_summary(b, progress) for b in listed]})
    narrators = ratings.narrator_list(db, profile, [asset for asset, _ in stories])
    if narrators:  # the voices behind the stories, as a way in next to sets and books (search lists them all)
        shelves.append({"id": "narrators", "items": [], "narrators": narrators[:20]})
    household_moments = profile.household.moments or list(MOMENTS)
    for moment in [m for m in MOMENTS if m in household_moments] + [m for m in MOMENTS if m not in household_moments]:
        items = [cards[asset_id] for asset_id in order if moment in cards[asset_id]["moments"]]
        if items:
            shelves.append({"id": moment, "moment": moment, "items": items[:20]})
    if favorites:
        shelves.append({"id": "favorites", "items": [cards[a] for a in cards if a in favorites][:20]})
    shelves.append({"id": "short", "items": [cards[a] for a in order if (cards[a]["duration"] or 0) <= 600][:20]})
    shelves.append({"id": "new", "items": [cards[a] for a in order][:20]})
    return {"profileId": profile.id,
            "shelves": [shelf for shelf in shelves
                        if shelf["items"] or shelf.get("sets") or shelf.get("books") or shelf.get("narrators")],
            "totalStories": len(order) + len(books)}


# --- Story sets (standalone stories of one character or series) and audiobooks (chapters in order) ---

@router.get("/api/collections")
def story_set_list(profile: Profile = Depends(current_profile), db: Session = Depends(get_db)):
    progress = _progress_map(db, profile)
    return {"items": [story_sets.set_summary(c, members, progress)
                      for c, members in story_sets.listed_sets(db, published_stories(db, profile))]}


@router.get("/api/collections/{collection_id}")
def collection_page(collection_id: int, profile: Profile = Depends(current_profile), db: Session = Depends(get_db)):
    """A story set, or an editorial shelf that is in season: every story in it this profile can hear."""
    collection = db.scalar(select(Collection).options(selectinload(Collection.items)).where(Collection.id == collection_id))
    listed = collection and collection.published and (
        collection.kind == story_sets.SET_KIND or any(c.id == collection.id for c in active_collections(db)))
    stories = published_stories(db, profile)
    by_id = {asset.id: (asset, teaser) for asset, teaser in stories}
    members = [by_id[item.audio_asset_id] for item in collection.items if item.audio_asset_id in by_id] if listed else []
    if not members:
        raise HTTPException(status_code=404, detail="This collection isn't available for this listener.")
    progress, favorites = _progress_map(db, profile), _favorite_set(db, profile)
    cards = _cards(members, profile, progress, favorites, story_sets.books_of(db, stories))
    return {**story_sets.set_summary(collection, members, progress), "stories": list(cards.values())}


@router.get("/api/books")
def book_list(profile: Profile = Depends(current_profile), db: Session = Depends(get_db)):
    progress = _progress_map(db, profile)
    books = sorted(story_sets.books_of(db, published_stories(db, profile)).values(),
                   key=lambda b: (b.series.title.casefold(), b.series.id))
    return {"items": [story_sets.book_summary(book, progress) for book in books]}


@router.get("/api/books/{book_id}")
def book_page(book_id: int, profile: Profile = Depends(current_profile), db: Session = Depends(get_db)):
    """An audiobook: where this profile left off, and every chapter with its finished or partial mark."""
    stories = published_stories(db, profile)
    books = story_sets.books_of(db, [(a, t) for a, t in stories if a.series_id == book_id])
    if book_id not in books:
        raise HTTPException(status_code=404, detail="This audiobook isn't available for this listener.")
    book = books[book_id]
    progress, favorites = _progress_map(db, profile), _favorite_set(db, profile)
    return {**story_sets.book_summary(book, progress),
            "chapters": list(_cards(book.chapters, profile, progress, favorites, books).values())}


@router.get("/api/stories/{asset_id}")
def story(asset_id: str, profile: Profile = Depends(current_profile), db: Session = Depends(get_db)):
    stories = published_stories(db, profile)
    match = next(((asset, teaser) for asset, teaser in stories if asset.id == asset_id), None)
    if not match:
        raise HTTPException(status_code=404, detail="This story isn't available for this listener.")
    asset, teaser = match
    progress, favorites = _progress_map(db, profile), _favorite_set(db, profile)
    books = story_sets.books_of(db, [(a, t) for a, t in stories if asset.series_id and a.series_id == asset.series_id])
    card = _cards([match], profile, progress, favorites, books)[asset.id]
    story_set = next(((c, members) for c, members in story_sets.listed_sets(db, stories)
                      if any(a.id == asset.id for a, _ in members)), None) if not asset.series_id else None
    if asset.series_id in books:  # an audiobook chapter: the chapters after it, in order
        chapters = books[asset.series_id].chapters
        up_next = chapters[books[asset.series_id].number(asset.id):][:20]
    elif story_set:  # a story set: the rest of the set, not yet heard first
        up_next = story_sets.next_in_set(story_set[1], asset.id, progress)
    else:
        same = [(a, t) for a, t in stories if a.album and a.album == asset.album and a.id != asset.id and not a.series_id]
        series = sorted(same, key=lambda pair: (story_sets.episode_key(pair[0]), pair[0].title))
        up_next = ([pair for pair in series if story_sets.episode_key(pair[0]) > story_sets.episode_key(asset)]
                   or series)[:10]
    narrators = {person_key(person) for person in narrator_people(asset)}
    same_narrator = [(a, t) for a, t in stories if a.id != asset.id and not a.series_id
                     and narrators & {person_key(person) for person in narrator_people(a)}][:10]
    by_id = {a.id: (a, t) for a, t in stories if not a.series_id}
    shown = {asset.id, *(a.id for a, _ in up_next[:10]), *(a.id for a, _ in same_narrator)}
    alike = recommend.related(db, asset.id, set(by_id) - shown, limit=10)
    prompts = asset.imagination_prompts or {}
    return {**card, "themes": teaser.themes, "ageSuggestion": teaser.age_suggestion,
            # Every language, so the app shows the teaser and moral in its own language as soon as it switches.
            "teasers": teaser_texts(teaser), "morals": morals.morals(asset),
            "readAlong": _read_along_transcript(db, asset) is not None,
            "waveform": (asset.renditions or {}).get("waveform", []),
            "storySet": {"id": story_set[0].id, "titles": story_set[0].titles, "storyCount": len(story_set[1])}
            if story_set else None,
            "upNext": list(_cards(up_next, profile, progress, set(), books).values()),
            "moreFromNarrator": [story_card(a, t, profile, progress.get(a.id)) for a, t in same_narrator],
            "moreLikeThis": [story_card(*by_id[a], profile, progress.get(a)) for a in alike],
            # Conversation starters are for parents (P3-07): never on a child's profile.
            "prompts": prompts.get("texts") if prompts.get("status") == "approved" and profile.kind == "adult" else None}


def _read_along_transcript(db: Session, asset: AudioAsset) -> Transcript | None:
    """Only when an editor turned captions on, which requires them to have read and approved the transcript."""
    if not asset.captions_enabled:
        return None
    transcript = pipeline.latest_transcript(db, asset.id)
    return transcript if transcript and transcript.status == "approved" and transcript.text else None


@router.get("/api/stories/{asset_id}/read-along")
def read_along_text(asset_id: str, profile: Profile = Depends(current_profile), db: Session = Depends(get_db)):
    """The story's text in passages timed to the listening copy (P2-19)."""
    asset = next((a for a, _ in published_stories(db, profile) if a.id == asset_id), None)
    if not asset:
        raise HTTPException(status_code=404, detail="This story isn't available for this listener.")
    transcript = _read_along_transcript(db, asset)
    if not transcript:
        raise HTTPException(status_code=404, detail="There's no read-along text for this story.")
    trimmed = float(((asset.qc or {}).get("mastering") or {}).get("trimmedStart") or 0)
    passages = read_along(transcript.text, transcript.segments, intro_removed=transcript.intro_removed, offset=trimmed)
    return {"language": transcript.language, "timed": any(p["start"] is not None for p in passages),
            "passages": passages}


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
