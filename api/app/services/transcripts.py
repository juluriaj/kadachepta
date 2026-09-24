"""Transcript clean-up and confidence scoring.

Sarvam doesn't return word confidences, so confidence is estimated from signals that catch the failures
we have actually seen: wrong language detection, hallucinated repetition loops, and transcripts that
stop early or are far too short or long for the audio.
"""

from __future__ import annotations

import re
from typing import Any

# Characters (without spaces) per second of audio for normal narration. Telugu catalog stories measure 10-13.
NORMAL_RATE = (5.0, 22.0)


def strip_intro(text: str, language: str, patterns: dict[str, list[str]]) -> tuple[str, str | None]:
    """Remove the channel name spoken at the start (and, if repeated, the end) of the transcript.

    Returns (text, what was removed or None). Patterns are written for the start; the same wording
    is also looked for as the last sentence.
    """
    removed = []
    for pattern in patterns.get(language, []):
        match = re.match(pattern, text)
        if match and match.end() > 0:
            removed.append(match.group(0).strip())
            text = text[match.end():].lstrip()
        body = pattern.removeprefix("^").removeprefix(r"\s*")
        outro = re.search(rf"(?:^|[.!?\s])({body})\s*$", text)
        if outro and outro.start(1) > 0:
            removed.append(outro.group(1).strip())
            text = text[:outro.start(1)].rstrip()
    return text, " … ".join(removed) or None


def _repetition(text: str) -> float:
    sentences = [s.strip() for s in re.split(r"[.!?।\n]+", text) if len(s.strip()) > 12]
    if len(sentences) < 4:
        return 0.0
    return 1 - len(set(sentences)) / len(sentences)


def assess(text: str, duration_seconds: float, *, language_probability: float | None = None,
           segments: list[Any] | dict[str, Any] | None = None) -> tuple[float, dict[str, Any]]:
    """Return (confidence 0..1, quality details with plain-language reasons)."""
    reasons: list[str] = []
    confidence = language_probability if language_probability is not None else 0.9
    if language_probability is not None and language_probability < 0.7:
        reasons.append(f"The speech-to-text service wasn't sure of the language ({language_probability:.0%}).")
    chars = len(re.sub(r"\s+", "", text))
    rate = chars / duration_seconds if duration_seconds else None
    if rate is not None and not NORMAL_RATE[0] <= rate <= NORMAL_RATE[1]:
        confidence *= 0.5
        reasons.append(f"Unusual amount of text for the audio length ({rate:.1f} characters per second).")
    coverage = None
    ends = []
    if isinstance(segments, dict):
        ends = [float(v) for v in segments.get("end_time_seconds") or [] if v is not None]
    elif isinstance(segments, list):
        ends = [float(s.get("end") or s.get("end_time_seconds") or 0) for s in segments if isinstance(s, dict)]
    if ends and duration_seconds:
        coverage = min(max(ends) / duration_seconds, 1.0)
        if coverage < 0.8:
            confidence *= 0.6
            reasons.append(f"The transcript stops at {coverage:.0%} of the recording.")
    repetition = _repetition(text)
    if repetition > 0.2:
        confidence *= 0.5
        reasons.append(f"{repetition:.0%} of sentences repeat, which often means the transcription looped.")
    return round(max(0.0, min(confidence, 1.0)), 2), {
        "charsPerSecond": round(rate, 1) if rate is not None else None, "coverage": coverage and round(coverage, 2),
        "repetition": round(repetition, 2), "languageProbability": language_probability, "reasons": reasons,
    }
