"""Story sets and audiobooks: the two ways stories belong together, presented differently to listeners.

A story set is a collection of kind "set": standalone stories about one character or from one source (Tenali
Ramakrishna, Akbar Birbal, Panchatantra). Families browse a set and shuffle it; any story can be heard first.
Sets started as the catalog's free-text `collection` field (migration 0011); a story joins the set named by its
`collection` when it is published, and editors can add or remove stories in the studio.

An audiobook is a `Series`: one work heard in order over many sessions. Its chapters never appear as stories of
their own on Home or in search; the book appears once, and resumes where the listener left off.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..models import AudioAsset, Collection, CollectionItem, ListeningProgress, Series, TeaserDraft
from .assets import artwork_url, iso, narrator_people, person_key, series_cover_url

SET_KIND = "set"
MIN_SET_STORIES = 2  # one story is not a set: smaller sets are kept for editors but not listed
NEAR_END_SECONDS = 15  # a chapter stopped this close to its end counts as finished

Pair = tuple[AudioAsset, TeaserDraft]


def name_key(text: str | None) -> str:
    return " ".join((text or "").split()).casefold()


def episode_key(asset: AudioAsset) -> tuple[int, str]:
    """Chapter order: the series position, else the number in the episode or track field, else the title."""
    if asset.series_position:
        return (asset.series_position, "")
    for value in (asset.episode_number, asset.track_number):
        digits = "".join(ch for ch in (value or "") if ch.isdigit())
        if digits:
            return (int(digits[:6]), "")
    return (0, asset.title)


# --- Story sets ---

def join_set(db: Session, asset: AudioAsset) -> Collection | None:
    """Add a newly published story to the set its `collection` names, starting the set if there is none yet.
    Only ever adds: editors decide removals. Audiobook chapters belong to their book, not to a set."""
    if asset.series_id or not name_key(asset.collection):
        return None
    key = name_key(asset.collection)
    sets = db.scalars(select(Collection).where(Collection.kind == SET_KIND).options(selectinload(Collection.items))
                      .order_by(Collection.id)).all()
    match = next((c for c in sets if key in {name_key(name) for name in c.source_names}), None)
    if match is None:
        name = " ".join(asset.collection.split())
        match = Collection(kind=SET_KIND, titles={"en-IN": name}, source_names=[name], published=True,
                           created_by="auto")
        db.add(match)
        db.flush()
    if not any(item.audio_asset_id == asset.id for item in match.items):
        position = max((item.position for item in match.items), default=-1) + 1
        match.items.append(CollectionItem(audio_asset_id=asset.id, position=position))
    return match


def listed_sets(db: Session, stories: list[Pair]) -> list[tuple[Collection, list[Pair]]]:
    """Published sets with at least MIN_SET_STORIES stories this profile can hear, each with those stories in the
    set's order. Editors' positions come first, then bigger sets."""
    by_id = {asset.id: (asset, teaser) for asset, teaser in stories if not asset.series_id}
    rows = db.scalars(select(Collection).options(selectinload(Collection.items))
                      .where(Collection.kind == SET_KIND, Collection.published.is_(True))).all()
    found = [(c, [by_id[item.audio_asset_id] for item in c.items if item.audio_asset_id in by_id]) for c in rows]
    found = [(c, members) for c, members in found if len(members) >= MIN_SET_STORIES]
    return sorted(found, key=lambda pair: (pair[0].position, -len(pair[1]), set_title(pair[0]).casefold()))


def set_title(collection: Collection) -> str:
    return collection.titles.get("en-IN") or next(iter(collection.titles.values()), "") or f"#{collection.id}"


def set_summary(collection: Collection, members: list[Pair], progress: dict[str, ListeningProgress]) -> dict[str, Any]:
    cover = next((asset for asset, _ in members if asset.artwork_key), None)
    return {
        "id": collection.id, "kind": collection.kind, "titles": collection.titles,
        "descriptions": collection.descriptions, "artworkUrl": artwork_url(cover) if cover else None,
        "storyCount": len(members),
        "heard": sum(1 for asset, _ in members if asset.id in progress and progress[asset.id].completed),
        "duration": round(sum(asset.duration_seconds or 0 for asset, _ in members)),
    }


def next_in_set(members: list[Pair], asset_id: str, progress: dict[str, ListeningProgress],
                limit: int = 20) -> list[Pair]:
    """What plays after a story from a set: the stories after it, wrapping round, those not yet heard first."""
    index = next((i for i, (asset, _) in enumerate(members) if asset.id == asset_id), -1)
    rotated = members[index + 1:] + members[:max(index, 0)]
    heard = {asset.id for asset, _ in rotated if asset.id in progress and progress[asset.id].completed}
    return ([pair for pair in rotated if pair[0].id not in heard] + [pair for pair in rotated if pair[0].id in heard])[:limit]


# --- Audiobooks ---

@dataclass
class Book:
    series: Series
    chapters: list[Pair]  # the chapters this profile can hear, in order

    def number(self, asset_id: str) -> int:
        return next(i for i, (asset, _) in enumerate(self.chapters) if asset.id == asset_id) + 1

    def info(self, asset_id: str) -> dict[str, Any]:
        """What a chapter's card carries so the app shows "Chapter N of M" and opens the book."""
        return {"id": self.series.id, "title": self.series.title, "chapter": self.number(asset_id),
                "chapters": len(self.chapters)}


def books_of(db: Session, stories: list[Pair]) -> dict[int, Book]:
    chapters: dict[int, list[Pair]] = {}
    for asset, teaser in stories:
        if asset.series_id:
            chapters.setdefault(asset.series_id, []).append((asset, teaser))
    if not chapters:
        return {}
    series = {s.id: s for s in db.scalars(select(Series).where(Series.id.in_(chapters)))}
    return {series_id: Book(series[series_id], sorted(pairs, key=lambda p: (episode_key(p[0]), p[0].title)))
            for series_id, pairs in chapters.items() if series_id in series}


def _finished(asset: AudioAsset, row: ListeningProgress | None) -> bool:
    if not row:
        return False
    return row.completed or bool(asset.duration_seconds and row.last_position >= asset.duration_seconds - NEAR_END_SECONDS)


def book_resume(chapters: list[AudioAsset], progress: dict[str, ListeningProgress]) -> dict[str, Any]:
    """Where the book picks up: the chapter last listened to if it isn't finished, otherwise the next unfinished
    chapter after it (then any unfinished one). "start" before any listening, "finished" when every chapter is."""
    heard = [(index, progress[asset.id]) for index, asset in enumerate(chapters) if asset.id in progress]
    if not heard:
        return {"state": "start", "index": 0, "position": 0.0}
    last_index, last = max(heard, key=lambda pair: pair[1].last_listened_at)
    if not _finished(chapters[last_index], last):
        return {"state": "continue", "index": last_index, "position": last.last_position}
    unfinished = [i for i, asset in enumerate(chapters) if not _finished(asset, progress.get(asset.id))]
    index = next((i for i in unfinished if i > last_index), unfinished[0] if unfinished else None)
    if index is None:
        return {"state": "finished", "index": 0, "position": 0.0}
    row = progress.get(chapters[index].id)
    return {"state": "continue", "index": index, "position": row.last_position if row else 0.0}


def last_listened(book: Book, progress: dict[str, ListeningProgress]) -> datetime | None:
    times = [progress[asset.id].last_listened_at for asset, _ in book.chapters if asset.id in progress]
    return max(times) if times else None


def book_summary(book: Book, progress: dict[str, ListeningProgress]) -> dict[str, Any]:
    chapters = [asset for asset, _ in book.chapters]
    resume = book_resume(chapters, progress)
    current = chapters[resume["index"]]
    cover = next((asset for asset in chapters if asset.artwork_key), None)
    narrators: dict[str, dict[str, Any]] = {}
    for asset in chapters:
        for person in narrator_people(asset):
            narrators.setdefault(person_key(person), person)
    return {
        "id": book.series.id, "title": book.series.title, "description": book.series.description,
        "language": book.series.language, "narrators": list(narrators.values()),
        "narrator": ", ".join(person["name"] for person in narrators.values()) or "KathaChepta",
        "artworkUrl": series_cover_url(book.series) or (artwork_url(cover) if cover else None),
        "chapterCount": len(chapters),
        "duration": round(sum(asset.duration_seconds or 0 for asset in chapters)),
        "finished": sum(1 for asset in chapters if _finished(asset, progress.get(asset.id))),
        "lastListenedAt": iso(last_listened(book, progress)),
        "resume": {"state": resume["state"], "chapterId": current.id, "chapter": resume["index"] + 1,
                   "position": round(resume["position"]),
                   "remaining": round(max(0.0, (current.duration_seconds or 0) - resume["position"]))},
    }
