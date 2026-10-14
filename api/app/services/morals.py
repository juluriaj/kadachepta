"""The idea behind a story (its moral) in each app language.

Editors approve the moral in English (``audio_assets.moral_takeaway``). The worker that holds the Sarvam key
translates it, as it does the Telugu conversation starters, and editors can correct the translation on the review
page. ``audio_assets.moral_translations`` holds one entry per language:
    {"te-IN": {"text": "...", "by": "ai:mayura:v1" | "editor:<name>", "from": "<the English it translates>"}}
An entry belongs to the English it was made from, so editing the moral makes the old translation stale (and queues a
new one) without any bookkeeping.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import jobs
from ..models import AudioAsset, Job
from .titles import UI_LANGUAGES

# The English is the moral itself; these are translated from it.
LANGUAGES = tuple(language for language in UI_LANGUAGES if language != "en-IN")


def entries(asset: AudioAsset) -> dict[str, dict[str, Any]]:
    """Current (not stale) translations."""
    return {lang: entry for lang, entry in (asset.moral_translations or {}).items()
            if entry.get("text") and asset.moral_takeaway and entry.get("from") == asset.moral_takeaway}


def morals(asset: AudioAsset) -> dict[str, str]:
    """What listeners see: {"en-IN": "...", "te-IN": "..."}, only where there is a current text."""
    if not asset.moral_takeaway:
        return {}
    return {"en-IN": asset.moral_takeaway, **{lang: entry["text"] for lang, entry in entries(asset).items()}}


def missing(asset: AudioAsset) -> list[str]:
    current = entries(asset)
    return [language for language in LANGUAGES if language not in current] if asset.moral_takeaway else []


def record(asset: AudioAsset, language: str, text: str, by: str) -> None:
    text = " ".join(text.split())[:500]
    translations = dict(asset.moral_translations or {})
    if text and asset.moral_takeaway:
        translations[language] = {"text": text, "by": by, "from": asset.moral_takeaway}
    else:
        translations.pop(language, None)
    asset.moral_translations = translations  # reassign so SQLAlchemy sees the JSONB change


def record_editor(asset: AudioAsset, texts: dict[str, str], actor: str) -> None:
    """The editor's translations from the review page. A text the editor left as it was is not re-recorded, so an
    old translation shown next to a newly edited English moral goes stale and is translated again."""
    for language, text in texts.items():
        stored = (asset.moral_translations or {}).get(language) or {}
        if language in LANGUAGES and " ".join(text.split()) != stored.get("text", ""):
            record(asset, language, text, f"editor:{actor}")


def request(db: Session, asset: AudioAsset, actor: str, priority: int = jobs.PRIORITY_DEFAULT) -> bool:
    """Queue a translation of the current moral where one is missing. Returns whether a job was queued."""
    languages = missing(asset)
    if not languages:
        return False
    last = db.scalars(select(Job).where(Job.audio_asset_id == asset.id, Job.job_type == "translate")
                      .order_by(Job.id.desc())).first()
    if last and (last.payload or {}).get("text") == asset.moral_takeaway and last.status != "cancelled":
        return False  # once per text: already on its way, done, or failed (retry it from the activity page)
    jobs.enqueue(db, "translate", asset_id=asset.id, payload={"text": asset.moral_takeaway, "languages": languages},
                 created_by=actor, priority=priority)
    return True
