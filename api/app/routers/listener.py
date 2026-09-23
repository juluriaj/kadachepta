"""Listener API: catalog, favorites, listening progress and stats, signed media."""

from __future__ import annotations

import re
from collections.abc import Iterator
from datetime import date, timedelta
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import and_, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, selectinload
from starlette.concurrency import run_in_threadpool

from ..auth import Identity, require, utcnow
from ..config import get_settings
from ..db import get_db
from ..models import AudioAsset, ListenerFavorite, ListeningDaily, ListeningProgress, TeaserDraft
from ..security import verify_media
from ..services.assets import artwork_url, asset_payload, iso
from ..storage import StorageError, content_type, get_storage

router = APIRouter(tags=["listener"])


def _approved_teaser_subquery():
    return (select(TeaserDraft.id).where(TeaserDraft.audio_asset_id == AudioAsset.id,
                                         TeaserDraft.status == "approved")
            .order_by(TeaserDraft.id.desc()).limit(1).correlate(AudioAsset).scalar_subquery())


@router.get("/api/catalog")
def catalog(language: str | None = None, identity: Identity = Depends(require("catalog.read")),
            db: Session = Depends(get_db)):
    query = (select(AudioAsset, TeaserDraft)
             .join(TeaserDraft, TeaserDraft.id == _approved_teaser_subquery())
             .where(AudioAsset.status == "published")
             .options(selectinload(AudioAsset.narrator_user))
             .order_by(AudioAsset.updated_at.desc()).limit(500))
    if language:
        query = query.where(AudioAsset.language == language)
    items = [asset_payload(asset, shortText=teaser.short_text, longText=teaser.long_text,
                           teaserAlternates=teaser.alternates)
             for asset, teaser in db.execute(query).all()]
    return {"items": items}


class FavoriteChange(BaseModel):
    assetId: str | None = None
    assetIds: list[str] | None = Field(default=None, max_length=200)
    saved: bool = True


def _favorite_ids(db: Session, user_id: int) -> list[str]:
    return list(db.scalars(
        select(ListenerFavorite.audio_asset_id)
        .join(AudioAsset, AudioAsset.id == ListenerFavorite.audio_asset_id)
        .where(ListenerFavorite.user_id == user_id, AudioAsset.status == "published")
        .order_by(ListenerFavorite.created_at.desc())))


@router.get("/api/me/favorites")
def get_favorites(identity: Identity = Depends(require("catalog.read")), db: Session = Depends(get_db)):
    return {"ids": _favorite_ids(db, identity.user.id)}


@router.post("/api/me/favorites")
def change_favorites(payload: FavoriteChange, identity: Identity = Depends(require("catalog.read")),
                     db: Session = Depends(get_db)):
    ids = [asset_id for asset_id in (payload.assetIds or [payload.assetId]) if asset_id]
    if not ids:
        raise HTTPException(status_code=400, detail="assetId is required.")
    if payload.saved:
        published = db.scalars(select(AudioAsset.id).where(AudioAsset.id.in_(ids), AudioAsset.status == "published"))
        rows = [{"user_id": identity.user.id, "audio_asset_id": asset_id} for asset_id in published]
        if rows:
            db.execute(insert(ListenerFavorite).values(rows).on_conflict_do_nothing())
    else:
        db.query(ListenerFavorite).filter(ListenerFavorite.user_id == identity.user.id,
                                          ListenerFavorite.audio_asset_id.in_(ids)).delete()
    db.commit()
    return {"ids": _favorite_ids(db, identity.user.id)}


class ListeningReport(BaseModel):
    assetId: str
    seconds: float = 0
    position: float = 0
    started: bool = False
    completed: bool = False
    day: str | None = None


def _local_day(value: str | None) -> date:
    try:
        return date.fromisoformat(value) if value else utcnow().date()
    except ValueError:
        return utcnow().date()


@router.post("/api/me/listening")
async def report_listening(request: Request, identity: Identity = Depends(require("catalog.read")),
                           db: Session = Depends(get_db)):
    # sendBeacon posts a Blob, so parse the body ourselves rather than relying on the content type.
    try:
        payload = ListeningReport.model_validate_json(await request.body())
    except ValueError as error:
        raise HTTPException(status_code=400, detail=f"Invalid listening report: {error}") from error
    return await run_in_threadpool(_record_listening, payload, identity, db)


def _record_listening(payload: ListeningReport, identity: Identity, db: Session) -> dict:
    # Clients flush every ~15 s; cap one report so a bad client cannot inflate stats.
    seconds = min(max(payload.seconds, 0), 120)
    position = max(payload.position, 0)
    if not db.scalar(select(AudioAsset.id).where(AudioAsset.id == payload.assetId,
                                                 AudioAsset.status == "published")):
        raise HTTPException(status_code=404, detail="Story not found.")
    now = utcnow()
    statement = insert(ListeningProgress).values(
        user_id=identity.user.id, audio_asset_id=payload.assetId, seconds_listened=seconds, last_position=position,
        play_count=int(payload.started), completed=payload.completed, first_listened_at=now, last_listened_at=now)
    db.execute(statement.on_conflict_do_update(
        index_elements=[ListeningProgress.user_id, ListeningProgress.audio_asset_id],
        set_={
            "seconds_listened": ListeningProgress.seconds_listened + statement.excluded.seconds_listened,
            "last_position": statement.excluded.last_position,
            "play_count": ListeningProgress.play_count + statement.excluded.play_count,
            "completed": ListeningProgress.completed | statement.excluded.completed,
            "last_listened_at": statement.excluded.last_listened_at,
        }))
    if seconds:
        daily = insert(ListeningDaily).values(user_id=identity.user.id, day=_local_day(payload.day), seconds=seconds)
        db.execute(daily.on_conflict_do_update(
            index_elements=[ListeningDaily.user_id, ListeningDaily.day],
            set_={"seconds": ListeningDaily.seconds + daily.excluded.seconds}))
    db.commit()
    return {"ok": True}


@router.get("/api/me/stats")
def stats(today: str | None = None, identity: Identity = Depends(require("catalog.read")),
          db: Session = Depends(get_db)):
    user_id = identity.user.id
    day = _local_day(today)
    total_seconds, started, completed = db.execute(
        select(func.coalesce(func.sum(ListeningProgress.seconds_listened), 0), func.count(),
               func.count().filter(ListeningProgress.completed))
        .where(ListeningProgress.user_id == user_id)).one()
    week_seconds = db.scalar(select(func.coalesce(func.sum(ListeningDaily.seconds), 0)).where(
        ListeningDaily.user_id == user_id, ListeningDaily.day >= day - timedelta(days=6),
        ListeningDaily.day <= day))
    days = list(db.scalars(select(ListeningDaily.day).where(
        ListeningDaily.user_id == user_id, ListeningDaily.seconds >= 60, ListeningDaily.day <= day)
        .order_by(ListeningDaily.day.desc())))
    streak, expected = 0, day
    if days and days[0] != day:
        expected = day - timedelta(days=1)  # an unbroken streak may end yesterday
    for listened in days:
        if listened != expected:
            break
        streak, expected = streak + 1, expected - timedelta(days=1)
    genre_seconds: dict[str, float] = {}
    for seconds, genres, genre in db.execute(
            select(ListeningProgress.seconds_listened, AudioAsset.genres, AudioAsset.genre)
            .join(AudioAsset, AudioAsset.id == ListeningProgress.audio_asset_id)
            .where(ListeningProgress.user_id == user_id)):
        for name in genres or ([genre] if genre else ["Other"]):
            genre_seconds[name] = genre_seconds.get(name, 0) + seconds
    recent = db.execute(
        select(ListeningProgress, AudioAsset).join(AudioAsset, AudioAsset.id == ListeningProgress.audio_asset_id)
        .where(ListeningProgress.user_id == user_id, AudioAsset.status == "published")
        .order_by(ListeningProgress.last_listened_at.desc()).limit(5)).all()
    favorites = db.scalar(select(func.count()).select_from(ListenerFavorite).join(
        AudioAsset, and_(AudioAsset.id == ListenerFavorite.audio_asset_id, AudioAsset.status == "published"))
        .where(ListenerFavorite.user_id == user_id))
    return {
        "totalSeconds": round(total_seconds), "weekSeconds": round(week_seconds or 0),
        "storiesStarted": started, "storiesCompleted": completed, "favorites": favorites, "streakDays": streak,
        "genres": [{"genre": name, "seconds": round(value)}
                   for name, value in sorted(genre_seconds.items(), key=lambda item: -item[1])],
        "recent": [{
            "id": asset.id, "title": asset.title, "seconds": round(progress.seconds_listened),
            "position": round(progress.last_position), "duration": round(asset.duration_seconds or 0),
            "completed": progress.completed, "lastListenedAt": iso(progress.last_listened_at),
            "artworkUrl": artwork_url(asset),
        } for progress, asset in recent],
    }


_RANGE = re.compile(r"bytes=(\d*)-(\d*)$")


def _file_chunks(path: Path, start: int, length: int, chunk: int = 256 * 1024) -> Iterator[bytes]:
    with path.open("rb") as handle:
        handle.seek(start)
        remaining = length
        while remaining > 0:
            data = handle.read(min(chunk, remaining))
            if not data:
                break
            remaining -= len(data)
            yield data


@router.api_route("/media/{key:path}", methods=["GET", "HEAD"], include_in_schema=False)
def media(key: str, request: Request, e: int = Query(...), s: str = Query(...)):
    if not verify_media(key, e, s, get_settings().secret_key):
        raise HTTPException(status_code=403, detail="This media link has expired. Refresh the page.")
    try:
        path = get_storage().path(key)
    except StorageError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Media not found.")
    size = path.stat().st_size
    headers = {"Accept-Ranges": "bytes", "Cache-Control": f"private, max-age={max(e - int(utcnow().timestamp()), 0)}"}
    mime = content_type(key)
    range_header = request.headers.get("range")
    if range_header:
        match = _RANGE.match(range_header.strip())
        if not match or (not match.group(1) and not match.group(2)):
            return Response(status_code=416, headers={"Content-Range": f"bytes */{size}"})
        if match.group(1):
            start = int(match.group(1))
            end = min(int(match.group(2)) if match.group(2) else size - 1, size - 1)
        else:  # suffix range: last N bytes
            start, end = max(size - int(match.group(2)), 0), size - 1
        if start >= size or start > end:
            return Response(status_code=416, headers={"Content-Range": f"bytes */{size}"})
        length = end - start + 1
        headers.update({"Content-Range": f"bytes {start}-{end}/{size}", "Content-Length": str(length)})
        body = None if request.method == "HEAD" else _file_chunks(path, start, length)
        return StreamingResponse(body or iter(()), status_code=206, media_type=mime, headers=headers)
    headers["Content-Length"] = str(size)
    body = None if request.method == "HEAD" else _file_chunks(path, 0, size)
    return StreamingResponse(body or iter(()), media_type=mime, headers=headers)
