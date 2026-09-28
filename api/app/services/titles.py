"""Story titles in each app language (Epic L).

``audio_assets.title_translations`` holds one entry per BCP 47 language:
    {"te-IN": {"text": "...", "by": "ai:qwen/qwen3-8b" | "editor:<name>" | "original",
               "from": "<the title it was made from>", "confirmed": bool}}

Listeners only see confirmed entries: the local AI model drafts, an editor confirms or corrects. An entry is
tied to the title it was made from, so renaming a story makes the old translations stale without any
bookkeeping. A title already written in a language's script (or a plain "Chapter 12") needs no confirmation.
"""

from __future__ import annotations

import re
from typing import Any

from ..models import AudioAsset

# App (UI) languages that listeners can switch between; titles are prepared for each of them.
UI_LANGUAGES = ("te-IN", "en-IN")
# Unicode blocks: Telugu U+0C00–U+0C7F, Devanagari U+0900–U+097F
SCRIPTS = {"te-IN": re.compile(r"[ఀ-౿]"), "hi-IN": re.compile(r"[ऀ-ॿ]")}
# Catalogue prefixes in seed-catalog titles, e.g. "TR14.Mamidi Pallu"
CATALOGUE_CODE = re.compile(r"^[A-Z]{1,3}\d+[.\-_ ]\s*")
# "Chapter 12" / "Part 3" (series chapters in the seed catalog) need no AI: this is the whole translation.
NUMBERED = re.compile(r"(chapter|part|episode)\s*[-.:]?\s*(\d+)", re.IGNORECASE)
NUMBERED_WORDS = {"te-IN": {"chapter": "అధ్యాయం", "part": "భాగం", "episode": "భాగం"},
                  "en-IN": {"chapter": "Chapter", "part": "Part", "episode": "Episode"}}


def automatic(title: str, language: str) -> str | None:
    """The title in ``language`` when no judgement is needed, else None.

    A title already in that language's script is kept as is. Latin-script titles are not assumed to be
    English: most seed-catalog titles are romanized Telugu ("Bhale Kaaki").
    """
    numbered = NUMBERED.fullmatch(clean_source(title))
    if numbered and language in NUMBERED_WORDS:
        return f"{NUMBERED_WORDS[language][numbered.group(1).lower()]} {numbered.group(2)}"
    pattern = SCRIPTS.get(language)
    return title if pattern and pattern.search(title) else None


def _valid(asset: AudioAsset, entry: dict[str, Any]) -> bool:
    return bool(entry.get("text")) and entry.get("from") == asset.title


def entries(asset: AudioAsset) -> dict[str, dict[str, Any]]:
    """Current (not stale) entries, including the original title where it is already in the right script."""
    result = {lang: entry for lang, entry in (asset.title_translations or {}).items() if _valid(asset, entry)}
    for language in UI_LANGUAGES:
        text = None if language in result else automatic(asset.title, language)
        if text:
            result[language] = {"text": text, "by": "original", "from": asset.title, "confirmed": True}
    return result


def confirmed_titles(asset: AudioAsset) -> dict[str, str]:
    """What listeners see: {"te-IN": "...", "en-IN": "..."} for confirmed titles only."""
    return {lang: entry["text"] for lang, entry in entries(asset).items() if entry.get("confirmed")}


def missing(asset: AudioAsset) -> list[str]:
    """Languages with neither a confirmed title nor an AI suggestion for the current title."""
    current = entries(asset)
    return [language for language in UI_LANGUAGES if language not in current]


def record(asset: AudioAsset, language: str, text: str, by: str, *, confirmed: bool) -> None:
    text = " ".join(text.split())[:160]
    translations = dict(asset.title_translations or {})
    if text:
        translations[language] = {"text": text, "by": by, "from": asset.title, "confirmed": confirmed}
    else:
        translations.pop(language, None)
    asset.title_translations = translations  # reassign so SQLAlchemy sees the JSONB change


def clean_source(title: str) -> str:
    return CATALOGUE_CODE.sub("", title).strip() or title
