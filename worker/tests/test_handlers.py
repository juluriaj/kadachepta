import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from kc_worker.handlers.media import MediaHandler  # noqa: E402
from kc_worker.handlers.teaser import build_messages, fit_transcript, validate  # noqa: E402
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
