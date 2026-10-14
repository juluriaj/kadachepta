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
    monkeypatch.delenv("SARVAM_API_KEY", raising=False)
    with pytest.raises(PermanentError):
        PromptsHandler().run(context(englishTitle="Crow"))
    answer = {"en-IN": ["One?", "Two?", " ", "Three?", "Four?"]}
    monkeypatch.setattr(llm, "chat_json", lambda *a, **k: (answer, {"model": "qwen"}))
    monkeypatch.setattr("kc_worker.handlers.artwork.release_pipeline", lambda: None)
    result = PromptsHandler().run(context(englishTitle="The Clever Crow", summary="A crow outwits a fox to save her chicks."))
    assert result["texts"] == {"en-IN": ["One?", "Two?", "Three?"]}  # no Sarvam key: English only


def test_prompts_name_the_story_animals_and_come_in_telugu_too(monkeypatch):
    from kc_worker.handlers import community

    asked, replies = [], [{"en-IN": ["What would you do?", "How did the crow feel?", "What if it rained?"]},
                          {"en-IN": ["What would you do?", "How did the monkey feel?", "What if it rained?"]}]

    def fake_chat(messages, schema, **_):
        asked.append(messages[1]["content"])
        return replies.pop(0), {"model": "qwen"}

    class Translation:
        def __init__(self, text):
            self.translated_text = text

    monkeypatch.setattr(llm, "chat_json", fake_chat)
    monkeypatch.setattr("kc_worker.handlers.artwork.release_pipeline", lambda: None)
    monkeypatch.setattr(community, "_translator", lambda: lambda **k: Translation(f"te: {k['input']}"))
    result = PromptsHandler().run(context(englishTitle="The Curious Monkey", summary="A monkey watches a carpenter.",
                                          transcript="ఒక కోతి వడ్రంగి పని చూసింది."))
    assert "Animals and people in this story (Telugu = English): " in asked[0] and "కోతి = monkey" in asked[0]
    assert "mentions crow but the story has no కాకి" in asked[1]
    assert result["texts"]["en-IN"][1] == "How did the monkey feel?"
    assert result["texts"]["te-IN"] == [f"te: {q}" for q in result["texts"]["en-IN"]]
    assert result["translation"] == community.TRANSLATE_MODEL and result["promptVersion"] == "starters-v2"


def test_moderation_passes_the_verdict_through(monkeypatch):
    monkeypatch.setattr(llm, "chat_json", lambda *a, **k: ({"verdict": "hold", "reasons": ["insult"], "note": "rude"},
                                                            {"model": "qwen"}))
    monkeypatch.setattr("kc_worker.handlers.artwork.release_pipeline", lambda: None)
    result = ReviewModerationHandler().run(context(reviewId=7, reviewText="The narrator is terrible", title="Crow"))
    assert result == {"reviewId": 7, "verdict": "hold", "reasons": ["insult"], "note": "rude", "model": "qwen"}


def test_prompts_explain_romanized_animal_words_in_the_teaser(monkeypatch):
    monkeypatch.delenv("SARVAM_API_KEY", raising=False)
    asked = []

    def fake_chat(messages, schema, **_):
        asked.append(messages[1]["content"])
        return {"en-IN": ["What would you do?", "How did the rabbit feel?", "What if it rained?"]}, {"model": "qwen"}

    monkeypatch.setattr(llm, "chat_json", fake_chat)
    monkeypatch.setattr("kc_worker.handlers.artwork.release_pipeline", lambda: None)
    PromptsHandler().run(context(summary="Kundelu Telivi is a story about a clever rabbit and a crocodile.",
                                 transcript="కుందేలు మొసలి"))
    assert 'Telugu words in the details, to write in English: "kundelu" means rabbit' in asked[0]


def test_prompts_reject_romanized_animal_names_and_long_questions():
    from kc_worker.handlers.community import _problems

    problems, _ = _problems(["How did kundelu feel?", "What if mosali swam away?", "What would you do?"], "కుందేలు మొసలి")
    assert problems == ["uses Telugu words instead of English: rabbit (hare), crocodile"]
    problems, _ = _problems(["One two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen?"],
                            "")
    assert problems[0] == "1 questions instead of 3" and problems[1].startswith("too long (15 words)")
