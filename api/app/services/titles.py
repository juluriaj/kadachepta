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
from difflib import SequenceMatcher
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


# Telugu titles from the recording itself. Narrators almost always say the title in the first sentence or two
# ("నేను చెప్పబోయే కథ కోతి చేష్టలు."), and the transcript spells it correctly, where the local 8B model spelled
# romanized titles letter by letter ("Koti Chestalu" -> "కొటీ చెస్టలు"). Measured on 142 editor-confirmed titles:
# 135 found, 118 spelled exactly as the editor did, most of the rest better (2026-10-13).
_CONSONANTS = dict(zip("కఖగఘఙచఛజఝఞటఠడఢణతథదధనపఫబభమయరఱలళవశషసహ",
                       "k kh g gh n ch chh j jh n t th d dh n t th d dh n p ph b bh m y r r l l v sh sh s h".split(), strict=True))
_VOWELS = dict(zip("అఆఇఈఉఊఋఎఏఐఒఓఔ", "a aa i ee u oo ru e e ai o o au".split(), strict=True))
_VOWEL_SIGNS = dict(zip("ాిీుూృెేైొోౌ",
                        "aa i ee u oo ru e e ai o o au".split(), strict=True))
_VIRAMA, _ANUSVARA = "్", "ం"
_TELUGU = re.compile(r"[ఀ-౿]")
_FOLD = (("aa", "a"), ("ee", "i"), ("ii", "i"), ("oo", "u"), ("uu", "u"), ("th", "t"), ("dh", "d"), ("sh", "s"),
         ("ch", "c"), ("kh", "k"), ("gh", "g"), ("ph", "p"), ("bh", "b"), ("jh", "j"), ("w", "v"), ("z", "j"))
TRANSCRIPT_MATCH = 0.8  # similarity needed between the spoken title and the catalogue title


def romanize(text: str) -> str:
    """Rough Latin spelling of Telugu, enough to compare with a romanized title (కోతి -> "kooti")."""
    out, i = [], 0
    while i < len(text):
        char, following = text[i], text[i + 1] if i + 1 < len(text) else ""
        if char in _CONSONANTS:
            out.append(_CONSONANTS[char])
            if following == _VIRAMA:
                i += 1
            elif following in _VOWEL_SIGNS:
                out.append(_VOWEL_SIGNS[following])
                i += 1
            else:
                out.append("a")
        elif char in _VOWELS:
            out.append(_VOWELS[char])
        elif char == _ANUSVARA:
            out.append("m")
        elif char.isspace():
            out.append(" ")
        i += 1
    return "".join(out)


def _skeleton(latin: str) -> str:
    """Spelling-insensitive form: "Kothi" and "kooti" both become "koti"."""
    text = re.sub(r"[^a-z]", "", latin.lower())
    for long, short in _FOLD:
        text = text.replace(long, short)
    text = re.sub(r"m(?=[^aeiou])", "n", text)
    return re.sub(r"(.)\1+", r"\1", text)


def from_transcript(title: str, transcript: str, max_words: int = 45) -> str | None:
    """The Telugu title as the narrator says it near the start of the recording, if it matches ``title``."""
    source = re.split(r"\s+by\s+", clean_source(title), flags=re.IGNORECASE)[0]
    target = _skeleton(source)
    if not target or _TELUGU.search(source):
        return None
    size = len(source.split())
    raw = (transcript or "").split()[:max_words]
    words = [word.strip(".,?!:;\"'“”‘’-") for word in raw]
    ends = [bool(re.search(r"[.?!]$", word)) for word in raw]
    starts = [i == 0 or ends[i - 1] or words[i - 1] in ("కథ", "పేరు") for i in range(len(raw))]
    best, best_score, best_match = None, 0.0, 0.0
    for length in range(max(1, size - 2), size + 3):
        for start in range(len(words) - length + 1):
            span = words[start:start + length]
            if not all(word and _TELUGU.search(word) for word in span):
                continue
            match = SequenceMatcher(None, _skeleton(romanize(" ".join(span))), target).ratio()
            # A whole sentence, or the words after "...కథ", is more likely the title than a phrase inside one.
            score = match + 0.04 * starts[start] + 0.04 * ends[start + length - 1]
            if score > best_score + 1e-9:
                best, best_score, best_match = " ".join(span), score, match
    return best if best and best_match >= TRANSCRIPT_MATCH else None


def suggest_from_transcript(asset: AudioAsset, transcript: str | None) -> bool:
    """Fill a missing Telugu title from the transcript, for an editor to confirm. True when one was found."""
    if "te-IN" not in missing(asset) or not transcript:
        return False
    text = from_transcript(asset.title, transcript)
    if text:
        record(asset, "te-IN", text, "transcript", confirmed=False)
    return bool(text)
