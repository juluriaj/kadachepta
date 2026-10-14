"""Speech-to-text through Sarvam (the one internet AI provider; local Telugu STT isn't good enough yet).

Settings: SARVAM_API_KEY, KC_STT_MODEL (default "saaras:v4").
Sarvam covers ten Indian languages plus English; other languages fail with a clear message
until a fallback provider (for example faster-whisper) is benchmarked and added.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any

from . import JobContext, PermanentError

RATE_LIMIT_WAITS = (15, 30, 60, 120, 240)  # seconds; the job's lease is kept alive by the heartbeat meanwhile


def with_backoff(context: JobContext, call, *args, waits=RATE_LIMIT_WAITS, **kwargs):
    """Sarvam answers HTTP 429 when too many requests arrive at once: wait and try again instead of failing the job."""
    for wait in (*waits, None):
        try:
            return call(*args, **kwargs)
        except Exception as error:  # noqa: BLE001 - the SDK's TooManyRequestsError, matched by status code
            if getattr(error, "status_code", None) != 429 or wait is None:
                raise
            context.log(f"Sarvam rate limit; trying again in {wait} s")
            time.sleep(wait)
    raise AssertionError("unreachable")


SARVAM_LANGUAGES = {"te-IN", "hi-IN", "ta-IN", "kn-IN", "ml-IN", "mr-IN", "bn-IN", "gu-IN", "pa-IN", "od-IN", "en-IN"}


class TranscriptionHandler:
    capability = "stt"

    def describe(self) -> dict[str, Any]:
        return {"provider": "sarvam", "model": os.environ.get("KC_STT_MODEL", "saaras:v4"),
                "configured": bool(os.environ.get("SARVAM_API_KEY"))}

    def run(self, context: JobContext) -> dict[str, Any]:
        api_key = os.environ.get("SARVAM_API_KEY")
        if not api_key:
            raise PermanentError("SARVAM_API_KEY is not configured on this worker.")
        language = context.inputs.get("language") or "te-IN"
        if language not in SARVAM_LANGUAGES:
            raise PermanentError(f"No speech-to-text provider is configured for {language} yet.")
        try:
            from sarvamai import SarvamAI
        except ImportError as error:
            raise PermanentError("The sarvamai package is not installed on this worker.") from error
        model = (context.inputs.get("settings") or {}).get("ai.stt.model") or os.environ.get("KC_STT_MODEL", "saaras:v4")
        suffix = Path(context.inputs.get("sourceFilename") or "audio.mp3").suffix or ".mp3"
        source = context.client.download(context.inputs["sourceUrl"],
                                         context.scratch / f"{context.inputs['assetId']}{suffix}")
        client = SarvamAI(api_subscription_key=api_key)
        job = with_backoff(context, client.speech_to_text_job.create_job, model=model, mode="transcribe",
                           language_code=language, with_diarization=False, with_timestamps=True)
        context.log(f"Sarvam job created: {getattr(job, 'job_id', 'unknown')}")
        with_backoff(context, job.upload_files, file_paths=[str(source)])
        with_backoff(context, job.start)
        # Long chapters can take a while; poll gently so several jobs together stay under the rate limit.
        with_backoff(context, job.wait_until_complete, poll_interval=15, timeout=3600)
        results = with_backoff(context, job.get_file_results)
        if not results.get("successful"):
            raise RuntimeError(f"Sarvam could not transcribe the file: {json.dumps(results.get('failed', []))[:800]}")
        with tempfile.TemporaryDirectory(dir=context.scratch) as output_dir:
            with_backoff(context, job.download_outputs, output_dir=output_dir)
            outputs = sorted(Path(output_dir).glob("*.json"))
            if not outputs:
                raise RuntimeError("Sarvam reported success but returned no transcript file.")
            raw_path = outputs[0]
            raw = json.loads(raw_path.read_text(encoding="utf-8"))
            raw_key = context.client.upload(context.job["id"], "sarvam.json", raw_path)
        text = raw.get("transcript") or raw.get("text") or ""
        if not text.strip():
            raise PermanentError("The transcript came back empty; the audio may have no speech.")
        segments = raw.get("timestamps") or raw.get("chunks") or raw.get("segments") or []
        return {"language": language, "text": text, "segments": segments, "rawKey": raw_key,
                "provider": "sarvam", "model": model, "languageProbability": raw.get("language_probability")}
