"""Phase 3 jobs on the local models (LM Studio): recommendation embeddings, conversation starters for parents,
and the first check on written reviews. All three are drafts or signals that people confirm or override:
editors approve conversation starters, and a review the model isn't sure about waits for an editor.
"""

from __future__ import annotations

import os
import re
from typing import Any

from .. import glossary, gpu, llm
from . import JobContext, PermanentError, artwork
from .transcription import with_backoff

# nomic-embed-text expects a task prefix; "clustering" suits story-to-story similarity.
EMBED_PREFIX = {"nomic": "clustering: "}


class EmbedHandler:
    capability = "llm"

    def describe(self) -> dict[str, Any]:
        return {"llmBaseUrl": llm.base_url()}

    def run(self, context: JobContext) -> dict[str, Any]:
        inputs = context.inputs
        value = (inputs.get("text") or "").strip()
        model = (inputs.get("settings") or {}).get("ai.embeddings.model") or "text-embedding-nomic-embed-text-v1.5"
        if not value:
            raise PermanentError("Nothing to embed: the story has no English teaser or details yet.")
        prefix = next((p for key, p in EMBED_PREFIX.items() if key in model), "")
        vectors, stats = llm.embed([prefix + value], model=model)
        context.log(f"embeddings {stats}")
        return {"vector": vectors[0], "model": model, "sourceHash": inputs.get("sourceHash"), "stats": stats}


# starters-v2: shorter questions, one each about a choice, a feeling and a what-if; the story's animals and people
# from the glossary (starters-v1 asked "How did you feel when the crow took the bread?" in a monkey story); Telugu
# translated by Sarvam (the 8B local model's own Telugu questions were ungrammatical). The Telugu uses మీరు: the
# familiar నువ్వు forms change with the child's gender (చేసేవాడివి / చేసేదానివి).
PROMPTS_VERSION = "starters-v2"
PROMPTS_SYSTEM = """You help parents talk with their children after a story.
Write 3 short open questions a parent can ask the child: one about a choice ("What would you do if you were
...?"), one about how a character felt ("How did ... feel when ...?"), and one that imagines something new
("What if ...?"). One short clause each, at most 10 words, simple words for ages 4 to 10, no right answers, no
quizzes about facts, nothing frightening. Use plain, literal words (no idioms such as "turned on": they are
translated word for word). Use only what is in the story details. Call animals by their English names, name every
other character exactly as the details do, and use the name again instead of he, she, or they."""
MAX_WORDS = 14  # the prompt asks for 10; longer ones are rejected (long clauses also translate badly)
# Compared on real starters (2026-10-13): mayura's formal mode keeps "he" and names right (sarvam-translate:v1
# turned "he" into ఆమె and Ramu into రామువు; the colloquial modes mix in English words).
TRANSLATE_MODEL = os.environ.get("KC_TRANSLATE_MODEL", "mayura:v1")
TRANSLATE_MODE = os.environ.get("KC_TRANSLATE_MODE", "formal")


def _translator():
    """Sarvam's translate call, or None where this worker has no Sarvam key (English starters only)."""
    key = os.environ.get("SARVAM_API_KEY")
    if not key:
        return None
    try:
        from sarvamai import SarvamAI
    except ImportError:
        return None
    return SarvamAI(api_subscription_key=key).text.translate


def _problems(questions: list[str], transcript: str) -> tuple[list[str], list[str]]:
    problems = [f"{len(questions)} questions instead of 3"] if len(questions) != 3 else []
    problems += [f"too long ({len(q.split())} words): {q}" for q in questions if len(q.split()) > MAX_WORDS]
    animals = glossary.unsupported_animals(" ".join(questions), transcript)
    if animals:
        problems.append("mentions " + ", ".join(f"{a} but the story has no {glossary.telugu_word_for(a)}" for a in animals))
    romanized = glossary.find_roman(" ".join(questions))  # "kundelu" for the rabbit
    if romanized:
        problems.append("uses Telugu words instead of English: " + ", ".join(e.gloss for e in romanized))
    return problems, animals or [e.gloss for e in romanized]


class PromptsHandler:
    capability = "llm"

    def describe(self) -> dict[str, Any]:
        return {"llmBaseUrl": llm.base_url(), "model": llm.default_model(), "promptVersion": PROMPTS_VERSION,
                "translation": TRANSLATE_MODEL if os.environ.get("SARVAM_API_KEY") else None}

    def run(self, context: JobContext) -> dict[str, Any]:
        inputs = context.inputs
        transcript = inputs.get("transcript") or ""
        # A romanized Telugu title ("Batuku Teruvu") reads like a name to the model; send only a real English one.
        english_title = inputs.get("englishTitle") if inputs.get("englishTitle") != inputs.get("title") else None
        details = "\n".join(f"{label}: {value}" for value, label in (
            (english_title, "Title"), (inputs.get("summary"), "Story"), (inputs.get("moral"), "Moral")) if value)
        if len(details) < 40:
            raise PermanentError("Not enough about the story yet (needs the English teaser).")
        cast = glossary.glossary_for(transcript)
        if cast:
            details += f"\nAnimals and people in this story (Telugu = English): {cast}"
        # Teasers sometimes keep the Telugu word ("Kundelu is a story about a rabbit"), which the model copies.
        spelled = re.findall(r"[a-z]+", details.lower())
        romanized = [f'"{next(w for w in spelled if w in entry.roman)}" means {entry.gloss.split(" (")[0]}'
                     for entry in glossary.find_roman(details)]
        if romanized:
            details += "\nTelugu words in the details, to write in English: " + "; ".join(romanized)
        schema = {"type": "object", "additionalProperties": False, "required": ["en-IN"],
                  "properties": {"en-IN": {"type": "array", "items": {"type": "string"}}}}
        model = (inputs.get("settings") or {}).get("ai.llm.model") or llm.default_model()
        artwork.release_pipeline()
        gpu.llm_will_load()
        correction, problems, questions, stats = "", [], [], {}
        for attempt in range(2):  # one retry, told what was wrong
            result, stats = llm.chat_json([{"role": "system", "content": PROMPTS_SYSTEM},
                                           {"role": "user", "content": f"{details}{correction}\n/no_think"}],
                                          schema, model=model, temperature=0.3 + 0.2 * attempt, max_tokens=500)
            context.log(f"LLM {stats}")
            questions = [" ".join(str(q).split())[:200] for q in result.get("en-IN", []) if str(q).strip()][:3]
            problems, animals = _problems(questions, transcript)
            if not problems:
                break
            context.log(f"Questions rejected: {problems}")
            correction = ("\nA previous attempt was wrong: " + "; ".join(problems) + ". Write exactly 3 questions of "
                          "at most 10 words" +(f", naming only these characters: {cast}" if animals and cast else "")
                          + ".")
        if problems:
            raise RuntimeError(f"The questions failed checks twice: {'; '.join(problems)}. Glossary sent: "
                               f"{cast or '(none)'}. Retry, or write the starters by hand.")
        texts = {"en-IN": questions}
        translate = _translator()
        if translate:
            texts["te-IN"] = [with_backoff(context, translate, input=q, source_language_code="en-IN",
                                           target_language_code="te-IN", model=TRANSLATE_MODEL,
                                           mode=TRANSLATE_MODE).translated_text.strip()
                              for q in questions]
            context.log(f"Translated to Telugu with Sarvam {TRANSLATE_MODEL} ({TRANSLATE_MODE})")
        else:
            context.log("No SARVAM_API_KEY on this worker: English starters only")
        return {"texts": texts, "model": stats.get("model"), "translation": TRANSLATE_MODEL if translate else None,
                "promptVersion": PROMPTS_VERSION, "stats": stats}


class TranslateHandler:
    """The idea behind a story (its English moral) in the other app languages, with the starters' Sarvam setup."""
    capability = "stt"  # the Sarvam key lives with the speech-to-text worker

    def describe(self) -> dict[str, Any]:
        return {"provider": "sarvam", "model": TRANSLATE_MODEL, "mode": TRANSLATE_MODE,
                "configured": bool(os.environ.get("SARVAM_API_KEY"))}

    def run(self, context: JobContext) -> dict[str, Any]:
        text = " ".join(str(context.inputs.get("text") or "").split())
        languages = [code for code in context.inputs.get("languages") or [] if code != "en-IN"]
        if not text or not languages:
            raise PermanentError("Nothing to translate: the story has no English moral yet.")
        translate = _translator()
        if not translate:
            raise PermanentError("SARVAM_API_KEY is not configured on this worker (or sarvamai is missing).")
        texts = {}
        for code in languages:
            texts[code] = with_backoff(context, translate, input=text, source_language_code="en-IN",
                                       target_language_code=code, model=TRANSLATE_MODEL,
                                       mode=TRANSLATE_MODE).translated_text.strip()
            context.log(f"{code}: {texts[code]}")
        # "source" lets the API drop the result if an editor changed the moral while this ran.
        return {"texts": texts, "source": context.inputs.get("text"), "model": TRANSLATE_MODEL}


MODERATION_SYSTEM = """You check listener reviews of children's audio stories before they are shown to other parents.
Return verdict:
- "block": hate or harassment, sexual content, threats, personal details (phone numbers, emails, addresses,
  a child's full name or school), links or advertising, or nonsense/spam.
- "hold": insulting the narrator personally, very harsh language, off-topic, or anything you are unsure about.
- "allow": an honest opinion about the story or narration, including criticism said politely.
Reviews may be in Telugu, English, or a mix. List the reasons (short English phrases) and a one-line note."""
REASONS = ["hate", "harassment", "sexual", "threat", "personal-info", "spam", "insult", "harsh-language", "off-topic",
           "unsure"]


class ReviewModerationHandler:
    capability = "llm"

    def describe(self) -> dict[str, Any]:
        return {"llmBaseUrl": llm.base_url(), "model": llm.default_model()}

    def run(self, context: JobContext) -> dict[str, Any]:
        inputs = context.inputs
        review = (inputs.get("reviewText") or "").strip()
        if not review:
            raise PermanentError("The review is empty.")
        schema = {"type": "object", "additionalProperties": False, "required": ["verdict", "reasons", "note"],
                  "properties": {"verdict": {"type": "string", "enum": ["allow", "hold", "block"]},
                                 "reasons": {"type": "array", "items": {"type": "string", "enum": REASONS}},
                                 "note": {"type": "string"}}}
        model = (inputs.get("settings") or {}).get("ai.llm.model") or llm.default_model()
        artwork.release_pipeline()
        gpu.llm_will_load()
        result, stats = llm.chat_json([{"role": "system", "content": MODERATION_SYSTEM},
                                       {"role": "user", "content": f"Story: {inputs.get('title')}\nReview: {review}\n/no_think"}],
                                      schema, model=model, temperature=0.0, max_tokens=200)
        context.log(f"LLM {stats} verdict={result.get('verdict')}")
        return {"reviewId": inputs.get("reviewId"), "verdict": result.get("verdict", "hold"),
                "reasons": result.get("reasons", []), "note": str(result.get("note", ""))[:300], "model": stats["model"]}
