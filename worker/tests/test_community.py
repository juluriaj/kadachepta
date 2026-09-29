import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402

from kc_worker import llm  # noqa: E402
from kc_worker.handlers import JobContext, PermanentError  # noqa: E402
from kc_worker.handlers.community import EmbedHandler, PromptsHandler, ReviewModerationHandler  # noqa: E402


def context(**inputs):
    return JobContext(client=None, job={"inputs": inputs}, scratch=Path("."))


def test_embeddings_use_the_nomic_task_prefix_and_echo_the_source_hash(monkeypatch):
    sent = {}

    def fake_embed(texts, *, model):
        sent.update(texts=texts, model=model)
        return [[0.5, 0.25]], {"model": model, "dimensions": 2}

    monkeypatch.setattr(llm, "embed", fake_embed)
    result = EmbedHandler().run(context(text="The Clever Crow", sourceHash="abc",
                                        settings={"ai.embeddings.model": "text-embedding-nomic-embed-text-v1.5"}))
    assert sent["texts"] == ["clustering: The Clever Crow"]
    assert result["vector"] == [0.5, 0.25] and result["sourceHash"] == "abc"
    with pytest.raises(PermanentError):
        EmbedHandler().run(context(text=" "))


def test_prompts_need_something_to_go_on_and_keep_three_questions(monkeypatch):
    with pytest.raises(PermanentError):
        PromptsHandler().run(context(englishTitle="Crow"))
    answer = {"en-IN": ["One?", "Two?", " ", "Three?", "Four?"]}
    monkeypatch.setattr(llm, "chat_json", lambda *a, **k: (answer, {"model": "qwen"}))
    monkeypatch.setattr("kc_worker.handlers.artwork.release_pipeline", lambda: None)
    result = PromptsHandler().run(context(englishTitle="The Clever Crow", summary="A crow outwits a fox to save her chicks."))
    assert result["texts"] == {"en-IN": ["One?", "Two?", "Three?"]}


def test_moderation_passes_the_verdict_through(monkeypatch):
    monkeypatch.setattr(llm, "chat_json", lambda *a, **k: ({"verdict": "hold", "reasons": ["insult"], "note": "rude"},
                                                            {"model": "qwen"}))
    monkeypatch.setattr("kc_worker.handlers.artwork.release_pipeline", lambda: None)
    result = ReviewModerationHandler().run(context(reviewId=7, reviewText="The narrator is terrible", title="Crow"))
    assert result == {"reviewId": 7, "verdict": "hold", "reasons": ["insult"], "note": "rude", "model": "qwen"}
