"""AI drafts with a local LLM (LM Studio): teasers, metadata suggestions, and the safety pre-check.

Prompt versions (chosen in the studio's AI settings, sent with each job):
  drafts-v5  drafts-v4 plus a glossary of the story's animals and people, and a check that the English names
             only animals the transcript mentions (drafts-v4's "కాకి is a crow" example turned monkeys into crows)
  drafts-v4  teasers + genres, keywords, listening moments, English title, and a content-policy safety check
  teaser-v3  teasers, themes, mood, age, warnings, moral (the Phase 0 prompt)
"""

from __future__ import annotations

import os
from typing import Any

from .. import glossary, gpu, llm
from . import JobContext, PermanentError, artwork

LANGUAGE_NAMES = {
    "te-IN": "Telugu", "hi-IN": "Hindi", "en-IN": "English", "ta-IN": "Tamil", "kn-IN": "Kannada",
    "ml-IN": "Malayalam", "mr-IN": "Marathi", "bn-IN": "Bengali", "gu-IN": "Gujarati", "pa-IN": "Punjabi",
    "od-IN": "Odia", "ur-IN": "Urdu",
}
# Indic scripts cost ~1.4 tokens per character, and LM Studio loads models with an 8k context by default.
MAX_TRANSCRIPT_CHARS = int(os.environ.get("KC_LLM_MAX_TRANSCRIPT_CHARS", "4200"))
DEFAULT_PROMPT = "drafts-v5"

# Kept in step with api/app/services/policy.py and docs/content-policy.md.
GENRES = ["Folklore", "Fable", "Mythology", "History", "Adventure", "Fantasy", "Humor", "Family", "Science",
          "Moral", "Biography", "Mystery", "Poetry", "Devotional", "Nature"]
CONTEXTS = ["bedtime", "drive", "run", "work", "learn"]
SAFETY_CATEGORIES = ["fear", "violence", "death", "loss", "romance", "discrimination", "imitation", "language", "other"]


def fit_transcript(text: str, budget: int = MAX_TRANSCRIPT_CHARS) -> tuple[str, bool]:
    """Keep the opening (what a teaser may use) and the ending (needed for the moral and warnings)."""
    text = text.strip()
    if len(text) <= budget:
        return text, False
    head, tail = int(budget * 0.7), int(budget * 0.3)
    return f"{text[:head].rstrip()}\n\n[... middle of the story omitted ...]\n\n{text[-tail:].lstrip()}", True


_TEXTS = {
    "type": "array",
    "items": {
        "type": "object", "additionalProperties": False, "required": ["language", "short", "long"],
        "properties": {"language": {"type": "string"}, "short": {"type": "string"}, "long": {"type": "string"}},
    },
}
SCHEMA_V3 = {
    "type": "object",
    "additionalProperties": False,
    "required": ["texts", "themes", "mood", "ageSuggestion", "contentWarnings", "moralTakeaway"],
    "properties": {
        "texts": _TEXTS,
        "themes": {"type": "array", "items": {"type": "string"}},
        "mood": {"type": "array", "items": {"type": "string"}},
        "ageSuggestion": {"type": "string"},
        "contentWarnings": {"type": "array", "items": {"type": "string"}},
        "moralTakeaway": {"type": "string"},
    },
}
SCHEMA_V4 = {
    "type": "object",
    "additionalProperties": False,
    "required": [*SCHEMA_V3["required"], "englishTitle", "genres", "keywords", "listeningContexts", "safety"],
    "properties": {
        **SCHEMA_V3["properties"],
        "englishTitle": {"type": "string"},
        "genres": {"type": "array", "items": {"type": "string", "enum": GENRES}},
        "keywords": {"type": "array", "items": {"type": "string"}},
        "listeningContexts": {"type": "array", "items": {"type": "string", "enum": CONTEXTS}},
        "safety": {
            # Flags come first so the model lists evidence before it commits to a rating.
            "type": "object", "additionalProperties": False, "required": ["flags", "summary", "minAge", "rating"],
            "properties": {
                "flags": {"type": "array", "items": {
                    "type": "object", "additionalProperties": False, "required": ["category", "severity", "evidence"],
                    "properties": {"category": {"type": "string", "enum": SAFETY_CATEGORIES},
                                   "severity": {"type": "string", "enum": ["low", "medium", "high"]},
                                   "evidence": {"type": "string"}}}},
                "summary": {"type": "string"},
                "minAge": {"type": "integer"},
                "rating": {"type": "string", "enum": ["all-ages", "caution", "not-for-children"]},
            },
        },
    },
}

SYSTEM = (
    "You are a careful children's audio-story editor. You write teasers that make families want to listen, "
    "without spoilers. Use only facts present in the transcript; never invent names, places, or events. "
    "Do not reveal the ending or the twist. Keep language warm, simple, and suitable for children. "
    "Ignore channel intros, website names, sponsor messages, and greetings at the start or end of the "
    "recording; never mention them. Name every animal and person exactly as the transcript does: use the "
    "glossary's English word for each Telugu word it lists, and never swap one animal for another. /no_think"
)
SAFETY_RUBRIC = (
    "Safety check, for parents: list every content flag with category (fear, violence, death, loss, romance, "
    "discrimination, imitation = dangerous behaviour a child might copy, language, other), severity (low, "
    "medium, high), and a short English quote or paraphrase as evidence. Rating: 'all-ages' only when there is "
    "nothing a parent of a 3-year-old would want to know; 'caution' for mild peril, off-screen deaths as in "
    "fables, or sadness; 'not-for-children' for war, cruelty, or mature themes. minAge is the youngest age the "
    "story suits (3 for gentle stories, 6 for fables with mild peril, 9 for battles and grief, 13 for mature "
    "epics). Ghosts, demons, and monsters are fear; any killing or dying, of people or animals, is death or "
    "violence. Traditional fables where a villain is punished are normal: flag them honestly but calmly."
)


def story_glossary(title: str, transcript: str) -> str:
    """The animals and people in this story (from the whole transcript, even the part the model doesn't see)."""
    entries = [entry for entry, _ in glossary.find(f"{title} {transcript}").most_common(14)]
    return glossary.describe(entries + [entry for entry in glossary.find_roman(title) if entry not in entries])


def build_messages(title: str, transcript: str, languages: list[str], version: str = DEFAULT_PROMPT,
                   series: str | None = None, correction: str = "") -> list[dict[str, str]]:
    names = ", ".join(f"{LANGUAGE_NAMES.get(code, code)} ({code})" for code in languages)
    story, trimmed = fit_transcript(transcript)
    note = ("The middle of the transcript is omitted. The ending is included only so you can judge the moral and "
            "content warnings: never mention or hint at it in the teasers.\n") if trimmed else ""
    words = story_glossary(title, transcript)
    if words:
        note += f"Glossary of animals and people in this story: {words}.\n"
    if correction:
        note += f"{correction}\n"
    extra = ""
    if version != "teaser-v3":
        extra = (f"Also give: `englishTitle` (a natural English title), `genres` (1-3 from the allowed list), "
                 f"`keywords` (3-8 English search words), `listeningContexts` (which of bedtime, drive, run, work, "
                 f"learn suit this story: bedtime only for calm stories), and `safety`.\n{SAFETY_RUBRIC}\n")
    user = (
        f"Story title: {title}\n" + (f"Part of the series: {series}\n" if series else "") +
        f"Write teasers in: {names}. For each language give `short` (one sentence, at most 20 words) and "
        "`long` (35 to 60 words), written natively in that language and script, not transliterated.\n"
        "Also give: 2-4 `themes` (English, lowercase, e.g. 'honesty'), 1-3 `mood` words (English, e.g. 'calm', "
        "'funny', 'adventurous'), `ageSuggestion` as an age band like '4-8', `contentWarnings` (English; empty if "
        "none; mention fear, violence, death, or loss if present), and `moralTakeaway` (one English sentence).\n"
        f"{extra}\n{note}TRANSCRIPT:\n{story}"
    )
    return [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}]


def validate(result: dict[str, Any], languages: list[str]) -> list[str]:
    problems = []
    texts = {item.get("language"): item for item in result.get("texts", [])}
    for code in languages:
        item = texts.get(code)
        if not item or not item.get("short") or not item.get("long"):
            problems.append(f"missing {code} teaser")
            continue
        words = len(item["long"].split())
        if words > 90:
            problems.append(f"{code} long teaser has {words} words")
    return problems


def wrong_animals(result: dict[str, Any], transcript: str) -> list[str]:
    """English animal words in the draft that the transcript never mentions, e.g. "crow" in a monkey story."""
    english = [item.get("short", "") + " " + item.get("long", "")
               for item in result.get("texts", []) if item.get("language") == "en-IN"]
    english += [str(result.get(key) or "") for key in ("englishTitle", "moralTakeaway")]
    english += [str(word) for word in result.get("keywords") or []]
    return glossary.unsupported_animals(" ".join(english), transcript)


def animal_correction(animals: list[str], words: str) -> str:
    named = ", ".join(f"{animal} ({glossary.telugu_word_for(animal)})" for animal in animals)
    return (f"A previous draft was wrong: it mentioned {named}, but this story has no such animal. "
            + (f"The animals and people in this story are: {words}." if words else
               "Name only animals that the transcript mentions."))


class TeaserHandler:
    capability = "llm"

    def describe(self) -> dict[str, Any]:
        return {"llmBaseUrl": llm.base_url(), "model": llm.default_model(), "promptVersion": DEFAULT_PROMPT,
                "availableModels": llm.list_models()}

    def run(self, context: JobContext) -> dict[str, Any]:
        inputs = context.inputs
        settings = inputs.get("settings") or {}
        model = settings.get("ai.llm.model") or llm.default_model()
        version = settings.get("ai.drafts.promptVersion") or DEFAULT_PROMPT
        transcript = (inputs.get("transcript") or "").strip()
        if not transcript:
            raise PermanentError("The transcript is empty.")
        languages = inputs.get("outputLanguages") or [inputs.get("language") or "te-IN"]
        title = inputs.get("title") or "Untitled"
        schema = SCHEMA_V3 if version == "teaser-v3" else SCHEMA_V4
        words = story_glossary(title, transcript)
        context.log(f"model={model} prompt={version} glossary={words or '(none)'}")
        artwork.release_pipeline()  # give the GPU back to the LLM (kc_worker/gpu.py)
        gpu.llm_will_load()
        last_problems: list[str] = []
        correction = ""
        for attempt in range(2):  # one repair attempt if the model skips a language or swaps an animal
            messages = build_messages(title, transcript, languages, version, inputs.get("series"), correction)
            result, stats = llm.chat_json(messages, schema, model=model, temperature=0.2 + 0.2 * attempt,
                                          max_tokens=1500 if version == "teaser-v3" else 2500)
            context.log(f"LLM {stats}")
            last_problems = validate(result, languages)
            animals = wrong_animals(result, transcript) if "en-IN" in languages else []
            if animals:
                last_problems.append("the English draft mentions " + ", ".join(
                    f"{animal} but the transcript has no {glossary.telugu_word_for(animal)}" for animal in animals))
                correction = animal_correction(animals, words)
            if not last_problems:
                break
            context.log(f"Draft rejected: {last_problems}")
        if last_problems:
            raise RuntimeError(f"Model output failed validation twice: {'; '.join(last_problems)}. "
                               f"Glossary sent: {words or '(none)'}. Retry the drafts, or write the teaser by hand.")
        output = {
            "language": languages[0],
            "texts": {item["language"]: {"short": item["short"].strip(), "long": item["long"].strip()}
                      for item in result["texts"] if item.get("language") in languages},
            "themes": result.get("themes", []), "mood": result.get("mood", []),
            "ageSuggestion": result.get("ageSuggestion"), "contentWarnings": result.get("contentWarnings", []),
            "moralTakeaway": result.get("moralTakeaway"), "provider": "lmstudio", "model": stats["model"],
            "promptVersion": version, "stats": stats,
        }
        if version != "teaser-v3":
            output.update({key: result.get(key) for key in
                           ("englishTitle", "genres", "keywords", "listeningContexts", "safety")})
        return output
