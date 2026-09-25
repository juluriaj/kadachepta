"""Content policy and age-rating rubric as data (P2-13). The prose version is docs/content-policy.md.

The same categories drive the AI safety pre-check prompt (worker/kc_worker/handlers/teaser.py), the editor's
review checklist, and the templated reasons editors give when they ask a narrator for changes.
"""

from __future__ import annotations

# Age bands a story can be rated for, with what each allows. Stories rated above a child's band never reach them.
AGE_RUBRIC = [
    {"band": "3-5", "allows": "Gentle stories. Mild peril resolved quickly; no deaths on-screen; no scary villains."},
    {"band": "6-8", "allows": "Clear right and wrong; mild peril and cartoon conflict; deaths only off-screen and "
                              "not dwelt on (as in fables)."},
    {"band": "9-12", "allows": "Adventure, battles described without gore, loss and grief handled with care, "
                               "mythological conflict."},
    {"band": "13+", "allows": "Historical fiction and epics with war, cruelty, or mature themes; no explicit content."},
]

SAFETY_CATEGORIES = {
    "fear": "Frightening scenes, ghosts, monsters, or threats",
    "violence": "Fighting, injury, weapons, or cruelty",
    "death": "Death or killing",
    "loss": "Grief, abandonment, or separation from family",
    "romance": "Romance or relationships beyond a child's understanding",
    "discrimination": "Stereotypes or demeaning language about a group (caste, religion, gender, region, disability)",
    "imitation": "Dangerous behaviour a child might copy (fire, poison, running away, talking to strangers)",
    "language": "Rude words or insults",
    "other": "Anything else a parent would want to know",
}

# What the editor confirms before publishing. Required items block publishing until ticked.
REVIEW_CHECKLIST = [
    {"id": "listened", "text": "I listened to the start, a middle section, and the end.", "required": True},
    {"id": "age", "text": "The age range matches the rubric, including the AI safety flags.", "required": True},
    {"id": "voice", "text": "It's a human narration (no AI voice presented as human).", "required": True},
    {"id": "teaser", "text": "The teaser has no spoilers and no invented facts.", "required": True},
    {"id": "artwork", "text": "The artwork suits the story and has no text or watermark.", "required": False},
]

CHANGE_REASONS = {
    "audio-noise": "Background noise makes parts hard to hear. Please record in a quieter room.",
    "audio-level": "The volume is uneven or distorted. Keep a steady distance from the microphone.",
    "audio-edit": "There are mistakes, restarts, or long pauses left in. Please re-record those parts.",
    "incomplete": "The story seems to be cut off or incomplete.",
    "age-content": "Some content isn't suitable for the audience it's meant for.",
    "rights": "We need more detail about where the story comes from, or proof you may narrate it.",
    "details": "The title or story details need correcting.",
    "language": "The recording's language doesn't match what was selected.",
    "other": "See the editor's note.",
}


# A deliberately over-inclusive word list per language (word stems). Local 8B models under-report safety
# issues, so any hit sends the story to a person; a hit never rejects anything by itself.
SAFETY_LEXICON: dict[str, dict[str, tuple[str, ...]]] = {
    "te-IN": {
        "death": ("చనిపో", "చచ్చి", "చచ్చా", "మరణ", "చావు", "శవ"),
        "violence": ("చంప", "నరిక", "కొట్టి చ", "రక్త", "కత్తి", "యుద్ధ", "హత్య"),
        "fear": ("దయ్య", "దెయ్య", "భూత", "పిశాచ", "రాక్షస", "భయంకర"),
        "loss": ("అనాథ", "విడిచిపెట్టి"),
    },
    "hi-IN": {
        "death": ("मौत", "मर गय", "मृत्यु", "लाश"),
        "violence": ("मार डाल", "हत्या", "खून", "तलवार", "युद्ध"),
        "fear": ("भूत", "चुड़ैल", "राक्षस", "डरावन"),
        "loss": ("अनाथ",),
    },
    "en-IN": {
        "death": ("died", "death", "dead", "corpse"),
        "violence": ("kill", "murder", "blood", "sword", "battle", " war "),
        "fear": ("ghost", "demon", "monster", "witch"),
        "loss": ("orphan", "abandoned"),
    },
}


def lexicon_flags(text: str, language: str, limit: int = 6) -> list[dict[str, str]]:
    flags, seen = [], set()
    lowered = text.lower()
    for category, stems in SAFETY_LEXICON.get(language, {}).items():
        for stem in stems:
            index = lowered.find(stem.lower())
            if index >= 0 and category not in seen:
                seen.add(category)
                snippet = text[max(0, index - 40): index + len(stem) + 40].replace("\n", " ").strip()
                flags.append({"category": category, "severity": "medium", "evidence": f"…{snippet}…",
                              "source": "word-list"})
                break
    return flags[:limit]


def derive_rating(model_rating: str | None, flags: list[dict[str, str]]) -> str:
    """Never trust a lower rating than the flags justify: all-ages only when nothing was flagged."""
    order = ["all-ages", "caution", "not-for-children"]
    derived = "not-for-children" if any(f.get("severity") == "high" for f in flags) else "caution" if flags else "all-ages"
    model = model_rating if model_rating in order else "caution"
    return max(model, derived, key=order.index)


def change_reason_texts(codes: list[str]) -> list[str]:
    return [CHANGE_REASONS[code] for code in codes if code in CHANGE_REASONS]


def required_checklist_ids() -> set[str]:
    return {item["id"] for item in REVIEW_CHECKLIST if item["required"]}
