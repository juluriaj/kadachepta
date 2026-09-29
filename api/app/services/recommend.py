"""Recommendations v1 (P3-06): "Because you finished …" and "More like this".

Two signals, blended:
- meaning: a local embedding model (LM Studio) reads each story's English title, teaser, themes, and moral,
  so a Telugu fable about a clever crow sits near other clever-animal fables whatever the language;
- listening: families who finished this story also finished that one (co-occurrence).

Embeddings are made by the "embed" job whenever a story's description changes; similarity is a pgvector
cosine query. Stories without an embedding yet still get the listening signal.
"""

from __future__ import annotations

import hashlib
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from ..models import AudioAsset, ListeningProgress, StoryEmbedding, TeaserDraft
from . import titles

MEANING, LISTENING = 0.7, 0.3


def embedding_text(asset: AudioAsset, teaser: TeaserDraft | None) -> str:
    english = ((teaser.alternates or {}).get("en-IN") or {}) if teaser else {}
    confirmed = titles.confirmed_titles(asset)
    parts = [
        confirmed.get("en-IN") or asset.title,
        english.get("long") or english.get("short") or "",
        "Themes: " + ", ".join(teaser.themes or []) if teaser and teaser.themes else "",
        "Genres: " + ", ".join(asset.genres or []) if asset.genres else "",
        f"Moral: {asset.moral_takeaway}" if asset.moral_takeaway else "",
        "Keywords: " + ", ".join(asset.keywords or []) if asset.keywords else "",
    ]
    return "\n".join(part for part in parts if part).strip()


def source_hash(model: str, value: str) -> str:
    return hashlib.sha256(f"{model}\n{value}".encode()).hexdigest()


def needs_embedding(db: Session, asset: AudioAsset, teaser: TeaserDraft | None, model: str) -> bool:
    value = embedding_text(asset, teaser)
    if len(value) < 20:  # nothing meaningful to embed yet (no teaser)
        return False
    current = db.get(StoryEmbedding, asset.id)
    return current is None or current.source_hash != source_hash(model, value)


def similar(db: Session, asset_id: str, candidates: set[str], limit: int = 10) -> list[tuple[str, float]]:
    """Stories closest in meaning (cosine similarity 0-1) among the candidates."""
    if not candidates:
        return []
    rows = db.execute(text(
        "SELECT other.audio_asset_id, 1 - (other.embedding <=> base.embedding) AS similarity "
        "FROM story_embeddings base JOIN story_embeddings other "
        "  ON other.audio_asset_id <> base.audio_asset_id AND other.model = base.model "
        " AND vector_dims(other.embedding) = vector_dims(base.embedding) "
        "WHERE base.audio_asset_id = :asset_id AND other.audio_asset_id = ANY(:candidates) "
        "ORDER BY other.embedding <=> base.embedding LIMIT :limit"),
        {"asset_id": asset_id, "candidates": list(candidates), "limit": limit}).all()
    return [(row[0], max(0.0, float(row[1]))) for row in rows]


def finished_together(db: Session, asset_id: str, candidates: set[str]) -> dict[str, int]:
    """How many listeners who finished this story also finished each candidate."""
    finishers = select(ListeningProgress.profile_id).where(ListeningProgress.audio_asset_id == asset_id,
                                                           ListeningProgress.completed.is_(True))
    rows = db.execute(select(ListeningProgress.audio_asset_id, func.count(func.distinct(ListeningProgress.profile_id)))
                      .where(ListeningProgress.completed.is_(True), ListeningProgress.profile_id.in_(finishers),
                             ListeningProgress.audio_asset_id.in_(candidates), ListeningProgress.audio_asset_id != asset_id)
                      .group_by(ListeningProgress.audio_asset_id)).all()
    return dict(rows)


def related(db: Session, asset_id: str, candidates: set[str], limit: int = 10) -> list[str]:
    candidates = candidates - {asset_id}
    meaning = dict(similar(db, asset_id, candidates, limit=40))
    together = finished_together(db, asset_id, candidates)
    top = max(together.values(), default=0)
    scores: dict[str, float] = {}
    for story in set(meaning) | set(together):
        scores[story] = MEANING * meaning.get(story, 0) + LISTENING * (together.get(story, 0) / top if top else 0)
    return [story for story, value in sorted(scores.items(), key=lambda item: -item[1]) if value > 0.2][:limit]


def because_you_finished(db: Session, profile_id: int, available: set[str], limit: int = 10) -> dict[str, Any] | None:
    """A shelf built from the story this listener finished most recently that has good neighbours."""
    progress = {row.audio_asset_id: row for row in db.scalars(
        select(ListeningProgress).where(ListeningProgress.profile_id == profile_id))}
    finished = sorted((row for row in progress.values() if row.completed and row.audio_asset_id in available),
                      key=lambda row: row.last_listened_at, reverse=True)
    heard = {asset_id for asset_id, row in progress.items() if row.completed or row.seconds_listened > 120}
    for row in finished[:3]:
        items = related(db, row.audio_asset_id, available - heard, limit)
        if len(items) >= 2:
            return {"basedOn": row.audio_asset_id, "items": items}
    return None
