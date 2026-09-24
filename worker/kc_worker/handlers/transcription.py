"""Speech-to-text through Sarvam (the one internet AI provider; local Telugu STT isn't good enough yet).

Settings: SARVAM_API_KEY, KC_STT_MODEL (default "saaras:v4").
Sarvam covers ten Indian languages plus English; other languages fail with a clear message
until a fallback provider (for example faster-whisper) is benchmarked and added.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from . import JobContext, PermanentError

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
        model = os.environ.get("KC_STT_MODEL", "saaras:v4")
        suffix = Path(context.inputs.get("sourceFilename") or "audio.mp3").suffix or ".mp3"
        source = context.client.download(context.inputs["sourceUrl"],
                                         context.scratch / f"{context.inputs['assetId']}{suffix}")
        client = SarvamAI(api_subscription_key=api_key)
        job = client.speech_to_text_job.create_job(model=model, mode="transcribe", language_code=language,
                                                   with_diarization=False, with_timestamps=True)
        context.log(f"Sarvam job created: {getattr(job, 'job_id', 'unknown')}")
        job.upload_files(file_paths=[str(source)])
        job.start()
        job.wait_until_complete()
        results = job.get_file_results()
        if not results.get("successful"):
            raise RuntimeError(f"Sarvam could not transcribe the file: {json.dumps(results.get('failed', []))[:800]}")
        with tempfile.TemporaryDirectory(dir=context.scratch) as output_dir:
            job.download_outputs(output_dir=output_dir)
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
                "provider": "sarvam", "model": model}
