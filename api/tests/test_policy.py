from app.routers.worker import _safety
from app.services.policy import derive_rating, lexicon_flags
from app.services.transcripts import assess, strip_intro
from app.services.settings import DEFAULT_INTRO_PATTERNS


def test_word_list_catches_what_small_models_miss():
    flags = lexicon_flags("రాత్రి ఒక దయ్యం వచ్చింది. జమీందారు జంతువులను చంపాడు.", "te-IN")
    assert {flag["category"] for flag in flags} == {"fear", "violence"}
    assert all(flag["source"] == "word-list" and "…" in flag["evidence"] for flag in flags)
    assert lexicon_flags("ఒక కాకి నీళ్ల కోసం వెతికింది.", "te-IN") == []


def test_rating_never_goes_below_what_the_flags_justify():
    assert derive_rating("all-ages", []) == "all-ages"
    assert derive_rating("all-ages", [{"severity": "low"}]) == "caution"
    assert derive_rating("caution", [{"severity": "high"}]) == "not-for-children"
    assert derive_rating("not-for-children", []) == "not-for-children"  # the model may be stricter
    assert derive_rating("nonsense", []) == "caution"


def test_ai_all_ages_is_overridden_by_the_transcript():
    safety = _safety({"rating": "all-ages", "minAge": 3, "flags": [], "summary": "Gentle."},
                     "ఆ దయ్యం పాపన్నను సహాయం అడిగింది.", "te-IN")
    assert safety["rating"] == "caution" and safety["modelRating"] == "all-ages" and safety["minAge"] == 6


def test_every_spoken_variant_of_the_channel_intro_is_removed():
    variants = ["కథచెప్తా.కామ్ అడవి.", "కథ చెప్తా డాట్ కామ్. రాజుగారి కోతి.", "కథచెపుతా.కామ్ కాకి హంస",
                "కథ చెబుతా డాట్ కామ్ నేను చెప్పబోయే కథ", "కథ చెప్తాడు.కామ్ ఇప్పుడు", "కథచెప్తా.కామ్ కి స్వాగతం. నేను మీ కల్పన."]
    for text in variants:
        cleaned, removed = strip_intro(text, "te-IN", DEFAULT_INTRO_PATTERNS)
        assert removed and "కామ్" not in cleaned, text
    assert strip_intro("హేమలత కథ.", "te-IN", DEFAULT_INTRO_PATTERNS) == ("హేమలత కథ.", None)
    cleaned, removed = strip_intro("కథచెపుతా.కామ్ కాకి హంస కాగలదా? అసూయపడడం మానేసింది. కథచెపుతా.కామ్.", "te-IN",
                                   DEFAULT_INTRO_PATTERNS)
    assert cleaned == "కాకి హంస కాగలదా? అసూయపడడం మానేసింది." and removed.count("కామ్") == 2


def test_confidence_drops_for_loops_and_early_stops():
    good = " ".join(f"వాక్యం సంఖ్య {i} ఇక్కడ ఉంది." for i in range(60))
    confidence, quality = assess(good, 120, language_probability=0.95)
    assert confidence == 0.95 and quality["reasons"] == []
    looped, quality = assess("ఒకే వాక్యం మళ్లీ మళ్లీ వస్తోంది. " * 60, 120, language_probability=0.95)
    assert looped < 0.6 and any("repeat" in reason for reason in quality["reasons"])
    stopped, quality = assess(good, 120, segments={"end_time_seconds": [10, 30]})
    assert stopped < 0.6 and any("stops" in reason for reason in quality["reasons"])


def test_read_along_without_timings_is_plain_passages():
    from app.services.transcripts import read_along

    assert read_along("One. Two.", {}) == [{"start": None, "end": None, "text": "One."},
                                           {"start": None, "end": None, "text": "Two."}]
    assert read_along("", {"words": ["x"], "start_time_seconds": [0], "end_time_seconds": [1]}) == []
