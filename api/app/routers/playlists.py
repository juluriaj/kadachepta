"""Listener playlists: named, ordered lists of stories per profile.

A playlist only ever shows stories the profile may hear right now: a story that is unpublished, or not
suitable for a child's age band, stays in the list but is left out until it is available again.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from ..db import get_db
from ..models import Playlist, PlaylistItem, Profile
from ..services.assets import iso
from ..services.households import current_profile
from .listener import _favorite_set, _progress_map, published_stories, story_card

router = APIRouter(prefix="/api/me/playlists", tags=["playlists"])
MAX_PLAYLISTS, MAX_ITEMS = 50, 200


class PlaylistIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)


class ItemIn(BaseModel):
    assetId: str


class OrderIn(BaseModel):
    assetIds: list[str] = Field(max_length=MAX_ITEMS)


def _playlist(db: Session, profile: Profile, playlist_id: int) -> Playlist:
    playlist = db.scalars(select(Playlist).options(selectinload(Playlist.items))
                          .where(Playlist.id == playlist_id, Playlist.profile_id == profile.id)).first()
    if not playlist:
        raise HTTPException(status_code=404, detail="Playlist not found.")
    return playlist


def _summary(playlist: Playlist, available: dict[str, Any]) -> dict[str, Any]:
    ids = [item.audio_asset_id for item in playlist.items if item.audio_asset_id in available]
    return {"id": playlist.id, "name": playlist.name, "count": len(ids), "storyIds": ids,
            "duration": round(sum(available[a][0].duration_seconds or 0 for a in ids)),
            "covers": [available[a][0].id for a in ids[:4]], "updatedAt": iso(playlist.updated_at)}


def _detail(db: Session, profile: Profile, playlist: Playlist) -> dict[str, Any]:
    available = {a.id: (a, t) for a, t in published_stories(db, profile)}
    progress, favorites = _progress_map(db, profile), _favorite_set(db, profile)
    stories = [story_card(*available[item.audio_asset_id], profile, progress.get(item.audio_asset_id),
                          item.audio_asset_id in favorites)
               for item in playlist.items if item.audio_asset_id in available]
    return {**_summary(playlist, available), "stories": stories}


@router.get("")
def list_playlists(profile: Profile = Depends(current_profile), db: Session = Depends(get_db)):
    available = {a.id: (a, t) for a, t in published_stories(db, profile)}
    rows = db.scalars(select(Playlist).options(selectinload(Playlist.items)).where(Playlist.profile_id == profile.id)
                      .order_by(Playlist.updated_at.desc())).all()
    return {"items": [_summary(p, available) for p in rows]}


@router.post("", status_code=201)
def create(payload: PlaylistIn, profile: Profile = Depends(current_profile), db: Session = Depends(get_db)):
    count = db.scalar(select(func.count()).select_from(Playlist).where(Playlist.profile_id == profile.id)) or 0
    if count >= MAX_PLAYLISTS:
        raise HTTPException(status_code=409, detail=f"You can have up to {MAX_PLAYLISTS} playlists. Delete one first.")
    playlist = Playlist(profile_id=profile.id, name=" ".join(payload.name.split()))
    db.add(playlist)
    db.commit()
    return _detail(db, profile, _playlist(db, profile, playlist.id))


@router.get("/{playlist_id}")
def get(playlist_id: int, profile: Profile = Depends(current_profile), db: Session = Depends(get_db)):
    return _detail(db, profile, _playlist(db, profile, playlist_id))


@router.post("/{playlist_id}")
def rename(playlist_id: int, payload: PlaylistIn, profile: Profile = Depends(current_profile), db: Session = Depends(get_db)):
    playlist = _playlist(db, profile, playlist_id)
    playlist.name = " ".join(payload.name.split())
    db.commit()
    return _detail(db, profile, playlist)


@router.delete("/{playlist_id}")
def delete(playlist_id: int, profile: Profile = Depends(current_profile), db: Session = Depends(get_db)):
    db.delete(_playlist(db, profile, playlist_id))
    db.commit()
    return {"ok": True}


@router.post("/{playlist_id}/items")
def add(playlist_id: int, payload: ItemIn, profile: Profile = Depends(current_profile), db: Session = Depends(get_db)):
    playlist = _playlist(db, profile, playlist_id)
    if not any(a.id == payload.assetId for a, _ in published_stories(db, profile)):
        raise HTTPException(status_code=404, detail="This story isn't available for this listener.")
    if any(item.audio_asset_id == payload.assetId for item in playlist.items):
        return _detail(db, profile, playlist)  # already there: adding twice is harmless
    if len(playlist.items) >= MAX_ITEMS:
        raise HTTPException(status_code=409, detail=f"A playlist holds up to {MAX_ITEMS} stories.")
    last = max((item.position for item in playlist.items), default=-1)
    playlist.items.append(PlaylistItem(audio_asset_id=payload.assetId, position=last + 1))
    playlist.updated_at = func.now()
    db.commit()
    db.refresh(playlist)
    return _detail(db, profile, playlist)


@router.delete("/{playlist_id}/items/{asset_id}")
def remove(playlist_id: int, asset_id: str, profile: Profile = Depends(current_profile), db: Session = Depends(get_db)):
    playlist = _playlist(db, profile, playlist_id)
    playlist.items = [item for item in playlist.items if item.audio_asset_id != asset_id]
    playlist.updated_at = func.now()
    db.commit()
    db.refresh(playlist)
    return _detail(db, profile, playlist)


@router.post("/{playlist_id}/order")
def reorder(playlist_id: int, payload: OrderIn, profile: Profile = Depends(current_profile), db: Session = Depends(get_db)):
    """The new order of the stories shown; stories not listed (hidden for now) keep their place at the end."""
    playlist = _playlist(db, profile, playlist_id)
    rank = {asset_id: index for index, asset_id in enumerate(dict.fromkeys(payload.assetIds))}
    for item in playlist.items:
        item.position = rank.get(item.audio_asset_id, len(rank) + item.position)
    playlist.updated_at = func.now()
    db.commit()
    db.expire(playlist)
    return _detail(db, profile, _playlist(db, profile, playlist_id))
