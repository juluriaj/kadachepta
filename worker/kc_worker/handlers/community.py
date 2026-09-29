"""Phase 3 jobs on the local models (LM Studio): recommendation embeddings, conversation starters for parents,
and the first check on written reviews. All three are drafts or signals that people confirm or override:
editors approve conversation starters, and a review the model isn't sure about waits for an editor.
"""

from __future__ import annotations

from typing import Any

from .. import gpu, llm
from . import JobContext, PermanentError, artwork

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


PROMPTS_SYSTEM = """You help parents talk with their children after a bedtime or car-ride story.
Write 3 short open questions a parent can ask after the story: about choices ("What would you have done?"),
feelings, or imagining something new ("What if ...?"). No right answers, no quizzes about facts, nothing
frightening, at most 18 words each, warm and simple for ages 4 to 10. Use only what is in the story details.
Write them in English. (Telugu is written by editors: the 8B local model's Telugu questions were ungrammatical.)"""


class PromptsHandler:
    capability = "llm"

    def describe(self) -> dict[str, Any]:
        return {"llmBaseUrl": llm.base_url(), "model": llm.default_model()}

    def run(self, context: JobContext) -> dict[str, Any]:
        inputs = context.inputs
        details = "\n".join(f"{label}: {inputs[key]}" for key, label in (
            ("englishTitle", "Title"), ("summary", "Story"), ("moral", "Moral"), ("themes", "Themes"),
            ("excerpt", "Opening of the story (Telugu)")) if inputs.get(key))
        if len(details) < 40:
            raise PermanentError("Not enough about the story yet (needs the English teaser or transcript).")
        schema = {"type": "object", "additionalProperties": False, "required": ["en-IN"],
                  "properties": {"en-IN": {"type": "array", "items": {"type": "string"}}}}
        model = (inputs.get("settings") or {}).get("ai.llm.model") or llm.default_model()
        artwork.release_pipeline()
        gpu.llm_will_load()
        result, stats = llm.chat_json([{"role": "system", "content": PROMPTS_SYSTEM},
                                       {"role": "user", "content": details + "\n/no_think"}],
                                      schema, model=model, temperature=0.4, max_tokens=700)
        context.log(f"LLM {stats}")
        texts = {"en-IN": [" ".join(str(q).split())[:200] for q in result.get("en-IN", []) if str(q).strip()][:3]}
        if not texts["en-IN"]:
            raise RuntimeError("The model returned no questions.")
        return {"texts": texts, "model": stats["model"], "stats": stats}


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
