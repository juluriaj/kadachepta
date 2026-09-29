"""Story search that finds Telugu stories typed in English letters (P3-05, Epic L).

Every story and every query is reduced to one "loose Latin" form: Telugu script is transliterated, and
spellings that people type differently are merged (aa/a, ee/i, th/t, doubled letters, m/n before a
consonant). "kaki hamsa", "Kaaki Hamsa" and "కాకి హంస" all become "kaki hansa", and trigram similarity
then forgives the remaining typos. English words (translated titles, keywords, genres, teasers) are
searched the same way, and a small synonym list links common English and Telugu story words (crow ↔ kaaki).

The catalog is searched in memory: a few thousand published stories take milliseconds. Normalized documents
are cached per story and refreshed when the story changes (updated_at).
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

# --- Telugu script → Latin (a simple ISO 15919-like scheme; exact enough for matching) ---

_VOWELS = {"అ": "a", "ఆ": "aa", "ఇ": "i", "ఈ": "ee", "ఉ": "u", "ఊ": "oo", "ఋ": "ru", "ఎ": "e", "ఏ": "e",
           "ఐ": "ai", "ఒ": "o", "ఓ": "o", "ఔ": "au"}
_SIGNS = {"ా": "aa", "ి": "i", "ీ": "ee", "ు": "u", "ూ": "oo", "ృ": "ru", "ె": "e", "ే": "e", "ై": "ai",
          "ొ": "o", "ో": "o", "ౌ": "au"}
_CONSONANTS = {"క": "k", "ఖ": "kh", "గ": "g", "ఘ": "gh", "ఙ": "n", "చ": "ch", "ఛ": "chh", "జ": "j", "ఝ": "jh",
               "ఞ": "n", "ట": "t", "ఠ": "th", "డ": "d", "ఢ": "dh", "ణ": "n", "త": "t", "థ": "th", "ద": "d",
               "ధ": "dh", "న": "n", "ప": "p", "ఫ": "ph", "బ": "b", "భ": "bh", "మ": "m", "య": "y", "ర": "r",
               "ఱ": "r", "ల": "l", "ళ": "l", "వ": "v", "శ": "sh", "ష": "sh", "స": "s", "హ": "h"}
_VIRAMA, _ANUSVARA, _VISARGA = "్", "ం", "ః"
_TELUGU = re.compile(r"[ఀ-౿]")


def transliterate(text: str) -> str:
    """Telugu script to Latin letters; other characters pass through."""
    out: list[str] = []
    pending = False  # a consonant waiting for its vowel (inherent "a" unless a sign or virama follows)
    for char in text:
        if char in _CONSONANTS:
            if pending:
                out.append("a")
            out.append(_CONSONANTS[char])
            pending = True
            continue
        if char in _SIGNS:
            out.append(_SIGNS[char])
            pending = False
            continue
        if char == _VIRAMA:
            pending = False
            continue
        if pending:
            out.append("a")
            pending = False
        if char == _ANUSVARA:
            out.append("m")
        elif char == _VISARGA:
            out.append("h")
        elif char in _VOWELS:
            out.append(_VOWELS[char])
        else:
            out.append(char)
    if pending:
        out.append("a")
    return "".join(out)


# --- Loose Latin: merge the spellings people use for the same Telugu sound ---

_MERGE = [("aa", "a"), ("ee", "i"), ("ii", "i"), ("oo", "u"), ("uu", "u"), ("ou", "u"), ("w", "v"), ("z", "j"),
          ("q", "k"), ("x", "ks"), ("ph", "p"), ("f", "p"), ("chh", "c"), ("ch", "c"), ("sh", "s"),
          ("th", "t"), ("dh", "d"), ("kh", "k"), ("gh", "g"), ("bh", "b"), ("jh", "j"), ("y", "i")]
_DOUBLE = re.compile(r"([a-z])\1+")
_M_BEFORE = re.compile(r"m(?=[^aeiou\s])")


def loose(text: str) -> str:
    text = transliterate(text) if _TELUGU.search(text) else text
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    for old, new in _MERGE:
        text = text.replace(old, new)
    text = _DOUBLE.sub(r"\1", text)
    text = _M_BEFORE.sub("n", text)
    return " ".join(text.split())


# English ↔ Telugu words that appear in children's story titles.
_SYNONYM_WORDS = {
    "crow": "kaki", "monkey": "koti", "lion": "simham", "fox": "nakka", "jackal": "nakka", "king": "raju",
    "queen": "rani", "ghost": "dayyam", "demon": "rakshasudu", "elephant": "enugu", "tiger": "puli",
    "rabbit": "kundelu", "hare": "kundelu", "frog": "kappa", "snake": "paamu", "parrot": "chiluka", "deer": "jinka",
    "cow": "aavu", "dog": "kukka", "cat": "pilli", "bird": "pakshi", "tree": "chettu", "forest": "adavi",
    "story": "katha", "stories": "kathalu", "grandma": "bamma", "god": "devudu", "clever": "telivaina",
    "friend": "nestam", "moral": "neeti", "swan": "hansa", "goat": "meka", "peacock": "nemali", "eagle": "gradda",
    "boar": "pandi", "mango": "mamidi", "sparrow": "pichhuka", "fish": "chepa", "horse": "gurram",
}
SYNONYMS = {english: loose(telugu) for english, telugu in _SYNONYM_WORDS.items()}
_REVERSE = {value: key for key, value in SYNONYMS.items()}


def expand(query: str) -> list[set[str]]:
    """Each query word in loose form, with its synonyms: "crow" → {"crov", "kaki"}, "kaaki" → {"kaki", "crov"}.
    Synonyms are looked up on the words as typed (loosening "crow" gives "crov")."""
    groups = []
    for word in (transliterate(query) if _TELUGU.search(query) else query).lower().split():
        word = re.sub(r"[^a-z0-9]", "", unicodedata.normalize("NFKD", word).encode("ascii", "ignore").decode())
        if not word:
            continue
        token = loose(word)
        group = {token}
        if word in SYNONYMS:
            group.add(SYNONYMS[word])
        if token in _REVERSE:
            group.add(loose(_REVERSE[token]))
        groups.append(group)
    return groups


def trigrams(word: str) -> set[str]:
    padded = f"  {word} "
    return {padded[i:i + 3] for i in range(len(padded) - 2)}


def similarity(a: str, b: str) -> float:
    ta, tb = trigrams(a), trigrams(b)
    return len(ta & tb) / len(ta | tb) if ta and tb else 0.0


# --- Documents ---

FIELD_WEIGHTS = {"title": 1.0, "series": 0.8, "narrator": 0.7, "keywords": 0.6, "text": 0.4}
_cache: dict[str, tuple[Any, dict[str, list[str]]]] = {}


def document(asset: Any, teaser: Any = None) -> dict[str, list[str]]:
    """Loose-Latin words per field for one story (cached until the story changes)."""
    stamp = (asset.updated_at, asset.title, id(teaser) if teaser is None else teaser.id)
    cached = _cache.get(asset.id)
    if cached and cached[0] == stamp:
        return cached[1]
    translations = [entry.get("text", "") for entry in (asset.title_translations or {}).values()]
    narrator = asset.narrator_user.display_name if getattr(asset, "narrator_user", None) else asset.narrator_name
    english = ((teaser.alternates or {}).get("en-IN") or {}) if teaser is not None else {}
    fields = {
        "title": " ".join([asset.title, *translations]),
        "series": " ".join(filter(None, [asset.album, asset.collection])),
        "narrator": narrator or "",
        "keywords": " ".join([*(asset.keywords or []), *(asset.genres or []), *(asset.listening_contexts or [])]),
        "text": " ".join(filter(None, [english.get("short"), asset.moral_takeaway,
                                       teaser.short_text if teaser is not None else None])),
    }
    doc = {field: loose(value).split() for field, value in fields.items()}
    _cache[asset.id] = (stamp, doc)
    return doc


def score(query: str, doc: dict[str, list[str]]) -> float:
    """0-1: how well every query word is found somewhere in the story, best field first."""
    groups = expand(query)
    if not groups:
        return 0.0
    total = 0.0
    for group in groups:
        best = 0.0
        for field, words in doc.items():
            weight = FIELD_WEIGHTS[field]
            for word in words:
                for token in group:
                    if word == token:
                        match = 1.0
                    elif len(token) >= 3 and word.startswith(token):
                        match = 0.9  # typing in progress: "kak" finds "kaki"
                    else:
                        match = similarity(token, word)
                    best = max(best, match * weight)
        total += best
    return total / len(groups)


def search(query: str, stories: list[tuple[Any, Any]], limit: int = 30, threshold: float = 0.42) -> list[tuple[Any, Any, float]]:
    ranked = [(asset, teaser, score(query, document(asset, teaser))) for asset, teaser in stories]
    ranked = [item for item in ranked if item[2] >= threshold]
    ranked.sort(key=lambda item: (-item[2], item[0].title))
    return ranked[:limit]
