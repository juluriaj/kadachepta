import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from kc_worker.handlers.media import (MediaHandler, background_profile, choose_level, mastering_chain,  # noqa: E402
                                      trim_points)
from kc_worker.handlers.artwork import build_prompt  # noqa: E402
from kc_worker.handlers.teaser import SCHEMA_V3, SCHEMA_V4, build_messages, fit_transcript, validate  # noqa: E402
from kc_worker.llm import THINK_BLOCK  # noqa: E402


def test_short_transcripts_are_sent_whole():
    text, trimmed = fit_transcript("ఒక కథ", budget=100)
    assert text == "ఒక కథ" and not trimmed


def test_long_transcripts_keep_opening_and_ending():
    story = "A" * 700 + "M" * 1000 + "Z" * 300
    text, trimmed = fit_transcript(story, budget=1000)
    assert trimmed and text.startswith("A" * 700) and text.endswith("Z" * 300) and "M" * 50 not in text
    assert "never mention or hint" in build_messages("t", story * 3, ["te-IN"])[1]["content"]


def test_validate_requires_every_language():
    result = {"texts": [{"language": "te-IN", "short": "a", "long": "b"}]}
    assert validate(result, ["te-IN", "en-IN"]) == ["missing en-IN teaser"]
    assert validate(result, ["te-IN"]) == []


def test_think_blocks_are_stripped():
    assert THINK_BLOCK.sub("", '<think>hmm</think>{"a": 1}') == '{"a": 1}'


def qc(**analysis_overrides):
    analysis = {"loudness": {"input_i": "-18", "input_tp": "-2", "input_lra": "6"}, "silenceSeconds": 5,
                "noiseFloorDb": -65, "peakDb": -1.0, "peakCount": 2, "flatFactor": 0}
    analysis.update(analysis_overrides)
    return MediaHandler()._qc({"duration": 300, "sampleRate": 44100, "codec": "mp3"}, analysis)


def test_clean_recording_passes():
    result = qc()
    assert result["verdict"] == "pass" and result["checks"] == []


def test_quiet_recording_fails_with_a_tip():
    result = qc(loudness={"input_i": "-40", "input_tp": "-20", "input_lra": "5"})
    assert result["verdict"] == "fail" and "closer to the microphone" in result["checks"][0]["tip"]


def test_loud_master_is_not_called_clipping_but_pinned_samples_are():
    assert qc(peakDb=-0.05, peakCount=3)["verdict"] == "pass"
    assert [c["code"] for c in qc(peakDb=0.0, peakCount=400)["checks"]] == ["clipping"]


def test_background_sound_and_long_pauses_warn():
    codes = {c["code"] for c in qc(noiseFloorDb=-40, silenceSeconds=120)["checks"]}
    assert codes == {"background-sound", "long-pauses"}


def test_mostly_silent_recording_fails():
    assert [c["code"] for c in qc(silenceSeconds=250)["checks"]] == ["mostly-silence"]
    assert qc(silenceSeconds=250)["verdict"] == "fail"


def test_drafts_v4_asks_for_safety_and_metadata_but_v3_does_not():
    v4 = build_messages("కాకి", "ఒక కాకి.", ["te-IN", "en-IN"], "drafts-v4", series="పంచతంత్రం")[1]["content"]
    assert "safety" in v4 and "listeningContexts" in v4 and "Part of the series: పంచతంత్రం" in v4
    assert "safety" not in build_messages("కాకి", "ఒక కాకి.", ["te-IN"], "teaser-v3")[1]["content"]
    assert set(SCHEMA_V4["required"]) - set(SCHEMA_V3["required"]) == {
        "englishTitle", "genres", "keywords", "listeningContexts", "safety"}


def test_artwork_prompt_leads_with_the_story_and_stays_short():
    prompt = build_prompt({"assetId": "a" * 16, "title": "కాకి", "englishTitle": "The Clever Crow",
                           "englishTeaser": "A thirsty crow finds a pot with little water. " * 10,
                           "themes": ["cleverness", "patience"], "mood": "funny"})
    assert prompt.startswith("Children's storybook illustration for \"The Clever Crow\". A thirsty crow")
    assert len(prompt) < 600 and "no text" in prompt


def features(**overrides):
    base = {"gapDb": -35.0, "gapSpread": 2.0, "gapFlatness": 0.5, "digitalSilence": 0.0, "topHz": 200,
            "stablePeaks": 0.07}
    return {**base, **overrides}


def test_background_profiles_match_the_catalog_calibration():
    # Values measured on real seed-catalog tracks (2017 raw recordings, edited voice tracks, music-bed productions).
    assert background_profile(features())[0] == "noise"                                       # 104.mp3, fan hiss
    assert background_profile(features(gapFlatness=0.3, topHz=47, stablePeaks=0.15))[0] == "hum"   # 85.mp3
    assert background_profile(features(gapDb=-45.3, gapSpread=10.4, gapFlatness=0.13))[0] == "music"  # "Musical" mix
    assert background_profile(features(gapDb=-14.1, gapFlatness=0.18))[0] == "music"         # Sundarakanda drone bed
    assert background_profile(features(gapDb=-25.6, gapSpread=14.3, digitalSilence=0.08))[0] == "edited"
    assert background_profile(features(gapDb=-56.3))[0] == "clean"                          # Lekka Tappu
    assert background_profile(features(gapDb=-27.4, gapFlatness=0.03, topHz=86, stablePeaks=0.131))[0] == "tonal"
    assert background_profile({})[0] == "unknown"


def test_editor_choice_beats_setting_beats_profile():
    assert choose_level("noise", "auto", None) == "full"
    assert choose_level("edited", "auto", None) == "light"
    assert choose_level("music", "auto", None) == "none"
    assert choose_level("noise", "off", None) == "none"
    assert choose_level("music", "off", "full") == "full"


def test_mastering_chain_limits_peaks_and_compresses_only_wide_recordings():
    full = mastering_chain("full", "standard", -30.0, 6.0)
    assert "volume=10.0dB" in full and "arnndn=m=" in full and ":mix=0.85" in full and "acompressor" not in full
    assert full.index("volume") < full.index("arnndn") < full.index("alimiter")
    light = mastering_chain("light", "gentle", -12.0, 14.0)
    assert "arnndn" not in light and "volume=-8.0dB" in light and "ratio=2.0" in light
    assert light.index("acompressor") < light.index("alimiter")


def test_trim_keeps_a_little_quiet_at_both_ends():
    log = "\n".join(["silence_start: 0", "silence_end: 4.2 | silence_duration: 4.2", "silence_start: 60.1",
                     "silence_end: 61.3 | silence_duration: 1.2", "silence_start: 118.0"])
    assert trim_points(log, 125.0) == (3.9, 118.8)
    assert trim_points("silence_start: 30\nsilence_end: 31.5", 120.0) == (0.0, 120.0)  # nothing at the ends
    assert trim_points("silence_start: 0.01\nsilence_end: 0.4", 60.0) == (0.0, 60.0)    # too short to bother


def test_qc_does_not_call_music_or_edited_pauses_background_noise():
    assert qc(noiseFloorDb=-40, profile="music")["checks"] == []
    assert qc(noiseFloorDb=-40, profile="edited")["checks"] == []
    assert [c["code"] for c in qc(noiseFloorDb=-40, profile="noise", mastered=True)["checks"]] == ["background-sound"]
    assert [c["code"] for c in qc(profile="tonal")["checks"]] == ["tonal-background"]
