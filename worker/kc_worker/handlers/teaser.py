"""Teaser and story-label drafting with a local LLM (LM Studio)."""

from __future__ import annotations

import os
from typing import Any

from .. import llm
from . import JobContext, PermanentError

PROMPT_VERSION = "teaser-v3"
LANGUAGE_NAMES = {
    "te-IN": "Telugu", "hi-IN": "Hindi", "en-IN": "English", "ta-IN": "Tamil", "kn-IN": "Kannada",
    "ml-IN": "Malayalam", "mr-IN": "Marathi", "bn-IN": "Bengali", "gu-IN": "Gujarati", "pa-IN": "Punjabi",
    "od-IN": "Odia", "ur-IN": "Urdu",
}
# Indic scripts cost ~1.4 tokens per character, and LM Studio loads models with an 8k context by default.
MAX_TRANSCRIPT_CHARS = int(os.environ.get("KC_LLM_MAX_TRANSCRIPT_CHARS", "4200"))


def fit_transcript(text: str, budget: int = MAX_TRANSCRIPT_CHARS) -> tuple[str, bool]:
    """Keep the opening (what a teaser may use) and the ending (needed for the moral and warnings)."""
    text = text.strip()
    if len(text) <= budget:
        return text, False
    head, tail = int(budget * 0.7), int(budget * 0.3)
    return f"{text[:head].rstrip()}\n\n[... middle of the story omitted ...]\n\n{text[-tail:].lstrip()}", True

SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["texts", "themes", "mood", "ageSuggestion", "contentWarnings", "moralTakeaway"],
    "properties": {
        "texts": {
            "type": "array",
            "items": {
                "type": "object", "additionalProperties": False, "required": ["language", "short", "long"],
                "properties": {"language": {"type": "string"}, "short": {"type": "string"}, "long": {"type": "string"}},
            },
        },
        "themes": {"type": "array", "items": {"type": "string"}},
        "mood": {"type": "array", "items": {"type": "string"}},
        "ageSuggestion": {"type": "string"},
        "contentWarnings": {"type": "array", "items": {"type": "string"}},
        "moralTakeaway": {"type": "string"},
    },
}


def build_messages(title: str, transcript: str, languages: list[str]) -> list[dict[str, str]]:
    names = ", ".join(f"{LANGUAGE_NAMES.get(code, code)} ({code})" for code in languages)
    story, trimmed = fit_transcript(transcript)
    note = ("The middle of the transcript is omitted. The ending is included only so you can judge the moral and "
            "content warnings: never mention or hint at it in the teasers.\n") if trimmed else ""
    system = (
        "You are a careful children's audio-story editor. You write teasers that make families want to listen, "
        "without spoilers. Use only facts present in the transcript; never invent names, places, or events. "
        "Do not reveal the ending or the twist. Keep language warm, simple, and suitable for children. "
        "Ignore channel intros, website names, sponsor messages, and greetings at the start or end of the "
        "recording; never mention them. Translate animal and character names exactly (for example కాకి is "
        "a crow, హంస is a swan). /no_think"
    )
    user = (
        f"Story title: {title}\n"
        f"Write teasers in: {names}. For each language give `short` (one sentence, at most 20 words) and "
        "`long` (35 to 60 words), written natively in that language and script, not transliterated.\n"
        "Also give: 2-4 `themes` (English, lowercase, e.g. 'honesty'), 1-3 `mood` words (English, e.g. 'calm', "
        "'funny', 'adventurous'), `ageSuggestion` as an age band like '4-8', `contentWarnings` (English; empty if "
        "none; mention fear, violence, death, or loss if present), and `moralTakeaway` (one English sentence).\n\n"
        f"{note}TRANSCRIPT:\n{story}"
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


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


class TeaserHandler:
    capability = "llm"

    def describe(self) -> dict[str, Any]:
        return {"llmBaseUrl": llm.base_url(), "model": llm.default_model(), "promptVersion": PROMPT_VERSION}

    def run(self, context: JobContext) -> dict[str, Any]:
        inputs = context.inputs
        transcript = (inputs.get("transcript") or "").strip()
        if not transcript:
            raise PermanentError("The approved transcript is empty.")
        languages = inputs.get("outputLanguages") or [inputs.get("language") or "te-IN"]
        messages = build_messages(inputs.get("title") or "Untitled", transcript, languages)
        last_problems: list[str] = []
        for attempt in range(2):  # one repair attempt if the model skips a language
            result, stats = llm.chat_json(messages, SCHEMA, temperature=0.2 + 0.2 * attempt)
            context.log(f"LLM {stats}")
            last_problems = validate(result, languages)
            if not last_problems:
                break
            context.log(f"Draft rejected: {last_problems}")
        if last_problems:
            raise RuntimeError(f"Model output failed validation: {'; '.join(last_problems)}")
        return {
            "language": languages[0],
            "texts": {item["language"]: {"short": item["short"].strip(), "long": item["long"].strip()}
                      for item in result["texts"] if item.get("language") in languages},
            "themes": result.get("themes", []), "mood": result.get("mood", []),
            "ageSuggestion": result.get("ageSuggestion"), "contentWarnings": result.get("contentWarnings", []),
            "moralTakeaway": result.get("moralTakeaway"), "provider": "lmstudio", "model": stats["model"],
            "promptVersion": PROMPT_VERSION, "stats": stats,
        }
