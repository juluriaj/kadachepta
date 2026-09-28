"""Story titles in each app language, drafted by the local LLM (LM Studio) for an editor to confirm.

One story per job: batching several titles into one request made the 8B model mix up which story was which.
The English teaser, when there is one, tells the model what the story is about, so "Garvinchina Mekalu"
comes out as "The Proud Goats" rather than a guess from the sound of the words.
"""

from __future__ import annotations

from typing import Any

from .. import gpu, llm
from . import JobContext, PermanentError, artwork

LANGUAGE_NAMES = {"te-IN": "Telugu", "en-IN": "English", "hi-IN": "Hindi"}
PROMPT_VERSION = "titles-v1"

SYSTEM = """You write titles for Telugu children's stories in a bilingual app.
Return the title in each requested language:
- te-IN: Telugu script. Write romanized Telugu phonetically with correct Telugu spelling (long vowels, retroflex \
letters) as a Telugu speaker spells the words. Translate English words into natural Telugu.
- en-IN: the meaning in natural English, in title case, like a storybook title. Translate every Telugu word; keep \
only personal names (people, gods) as names.
- hi-IN: natural Hindi in Devanagari.
Use the story summary, when given, to get the meaning right. Never add events or names that are not in the title. \
Drop catalogue codes such as "TR14.".

Examples:
"Bhale Kaaki" -> te-IN "భలే కాకి", en-IN "The Clever Crow"
"Adavi Raju" -> te-IN "అడవి రాజు", en-IN "King of the Forest"
"Tenali Ramudu Gurram" -> te-IN "తెనాలి రాముడు గుర్రం", en-IN "Tenali Raman's Horse"
"కాకి హంస కాగలదా" -> en-IN "Can a Crow Become a Swan?"
"Garvinchina Nemali" -> te-IN "గర్వించిన నెమలి", en-IN "The Proud Peacock\""""


def build_messages(title: str, languages: list[str], series: str | None, summary: str | None) -> list[dict[str, str]]:
    names = ", ".join(f"{code} ({LANGUAGE_NAMES.get(code, code)})" for code in languages)
    user = (f"Title: {title}\n" + (f"Series: {series}\n" if series else "") +
            (f"Story summary: {summary}\n" if summary else "") + f"Languages: {names}\n/no_think")
    return [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}]


def schema(languages: list[str]) -> dict[str, Any]:
    return {"type": "object", "additionalProperties": False, "required": languages,
            "properties": {code: {"type": "string"} for code in languages}}


class TitlesHandler:
    capability = "llm"

    def describe(self) -> dict[str, Any]:
        return {"llmBaseUrl": llm.base_url(), "model": llm.default_model(), "promptVersion": PROMPT_VERSION}

    def run(self, context: JobContext) -> dict[str, Any]:
        inputs = context.inputs
        languages = inputs.get("languages") or []
        title = (inputs.get("sourceTitle") or "").strip()
        if not title or not languages:
            raise PermanentError("Nothing to translate.")
        model = (inputs.get("settings") or {}).get("ai.llm.model") or llm.default_model()
        artwork.release_pipeline()  # give the GPU back to the LLM (kc_worker/gpu.py)
        gpu.llm_will_load()
        result, stats = llm.chat_json(build_messages(title, languages, inputs.get("series"), inputs.get("summary")),
                                      schema(languages), model=model, temperature=0.1, max_tokens=300)
        context.log(f"LLM {stats}")
        titles = {code: " ".join(str(result.get(code) or "").split())[:160] for code in languages}
        if not any(titles.values()):
            raise RuntimeError("The model returned no titles.")
        return {"title": inputs.get("title"), "titles": titles, "provider": "lmstudio", "model": stats["model"],
                "promptVersion": PROMPT_VERSION, "stats": stats}
