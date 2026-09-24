"""Audio normalization, mobile renditions, waveform, and quality checks (ffmpeg).

Outputs:
  standard.m4a   mono AAC-LC 64 kbps, 44.1 kHz, loudness -16 LUFS / -1.5 dBTP
  datasaver.m4a  mono AAC-LC 32 kbps, 22.05 kHz, same loudness
Settings: KC_FFMPEG (default "ffmpeg"), KC_FFPROBE (default "ffprobe").
"""

from __future__ import annotations

import array
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

from . import JobContext, PermanentError

TARGET_I, TARGET_TP, TARGET_LRA = -16.0, -1.5, 11.0


def _run(context: JobContext, args: list[str], *, capture: bool = True) -> subprocess.CompletedProcess:
    result = subprocess.run(args, capture_output=capture, timeout=3600)
    if result.returncode != 0:
        stderr = result.stderr.decode("utf-8", "replace") if result.stderr else ""
        context.log(stderr[-3000:])
        raise RuntimeError(f"{Path(args[0]).name} exited with {result.returncode}: {stderr.strip().splitlines()[-1:]}")
    return result


def _sha256(path: Path) -> str:
    import hashlib
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return None if number != number or number in (float("inf"), float("-inf")) else number


class MediaHandler:
    capability = "media"

    def __init__(self):
        self.ffmpeg = os.environ.get("KC_FFMPEG", "ffmpeg")
        self.ffprobe = os.environ.get("KC_FFPROBE", "ffprobe")

    def describe(self) -> dict[str, Any]:
        try:
            version = subprocess.run([self.ffmpeg, "-version"], capture_output=True, timeout=10).stdout.decode()
            return {"ffmpeg": version.splitlines()[0] if version else "unknown"}
        except OSError as error:
            return {"ffmpeg": f"unavailable: {error}"}

    def run(self, context: JobContext) -> dict[str, Any]:
        inputs = context.inputs
        joined: dict[str, Any] = {}
        if inputs.get("parts"):
            source = self._join(context, inputs["parts"])
            key = context.client.upload(context.job["id"], source.name, source)
            joined = {"sourceKey": key, "sourceChecksum": _sha256(source)}
        else:
            suffix = Path(inputs.get("sourceFilename") or "source.mp3").suffix or ".mp3"
            source = context.client.download(inputs["sourceUrl"], context.scratch / f"source{suffix}")
        probe = self._probe(context, source)
        analysis = self._analyse(context, source)
        standard, datasaver = context.scratch / "standard.m4a", context.scratch / "datasaver.m4a"
        self._render(context, source, analysis, standard, datasaver)
        waveform, noise_floor = self._pcm_analysis(context, standard)
        analysis["noiseFloorDb"] = noise_floor
        qc = self._qc(probe, analysis)
        job_id = context.job["id"]
        renditions = {}
        for name, path, bitrate, rate in (("standard", standard, 64000, 44100), ("datasaver", datasaver, 32000, 22050)):
            key = context.client.upload(job_id, path.name, path)
            renditions[name] = {"key": key, "bytes": path.stat().st_size, "bitrate": bitrate, "sampleRate": rate,
                                "mime": "audio/mp4", "codec": "aac-lc", "channels": 1}
        return {"durationSeconds": probe["duration"], "bitrate": probe["bitrate"], "sampleRate": probe["sampleRate"],
                "channels": probe["channels"], "renditions": renditions, "waveform": waveform, "qc": qc, **joined}

    def _join(self, context: JobContext, parts: list[dict[str, Any]]) -> Path:
        """Join takes recorded in the app (possibly different containers) into one lossless-enough original."""
        files = []
        for index, part in enumerate(parts):
            suffix = Path(part.get("filename") or "take.m4a").suffix or ".m4a"
            files.append(context.client.download(part["url"], context.scratch / f"part{index:02d}{suffix}"))
        target = context.scratch / "original.m4a"
        inputs = [arg for path in files for arg in ("-i", str(path))]
        graph = "".join(f"[{i}:a]aformat=sample_rates=48000:channel_layouts=mono[a{i}];" for i in range(len(files)))
        graph += "".join(f"[a{i}]" for i in range(len(files))) + f"concat=n={len(files)}:v=0:a=1[out]"
        _run(context, [self.ffmpeg, "-hide_banner", "-nostats", "-y", *inputs, "-filter_complex", graph,
                       "-map", "[out]", "-c:a", "aac", "-b:a", "192k", str(target)])
        context.log(f"Joined {len(files)} takes into {target.name}")
        return target

    def _probe(self, context: JobContext, source: Path) -> dict[str, Any]:
        result = _run(context, [self.ffprobe, "-v", "error", "-print_format", "json", "-show_format",
                                "-show_streams", "-select_streams", "a:0", str(source)])
        data = json.loads(result.stdout or b"{}")
        streams = data.get("streams") or []
        if not streams:
            raise PermanentError("The file has no audio stream. Upload an audio recording (MP3, M4A, WAV).")
        stream, fmt = streams[0], data.get("format", {})
        duration = _float(fmt.get("duration")) or _float(stream.get("duration")) or 0.0
        if duration <= 0:
            raise PermanentError("Could not read the recording's duration; the file may be damaged.")
        return {"duration": round(duration, 2), "bitrate": int(_float(fmt.get("bit_rate")) or 0) or None,
                "sampleRate": int(_float(stream.get("sample_rate")) or 0) or None,
                "channels": int(stream.get("channels") or 0) or None, "codec": stream.get("codec_name")}

    def _analyse(self, context: JobContext, source: Path) -> dict[str, Any]:
        filters = (f"silencedetect=noise=-45dB:d=2,astats=metadata=0:measure_perchannel=none,"
                   f"loudnorm=I={TARGET_I}:TP={TARGET_TP}:LRA={TARGET_LRA}:print_format=json")
        result = _run(context, [self.ffmpeg, "-hide_banner", "-nostats", "-i", str(source), "-af", filters,
                                "-f", "null", "-"])
        stderr = result.stderr.decode("utf-8", "replace")
        match = re.search(r"\{\s*\"input_i\".*?\}", stderr, re.S)
        if not match:
            context.log(stderr[-2000:])
            raise RuntimeError("ffmpeg loudness analysis produced no measurements.")
        loudness = json.loads(match.group(0))
        silences = [float(value) for value in re.findall(r"silence_duration:\s*([\d.]+)", stderr)]
        starts = [float(value) for value in re.findall(r"silence_start:\s*([\d.]+)", stderr)]

        def stat(label: str) -> float | None:
            found = re.findall(rf"{label}:\s*(-?[\d.]+|-?inf)", stderr)
            return _float(found[-1]) if found else None

        return {"loudness": loudness, "silenceSeconds": round(sum(silences), 2),
                "leadingSilence": round(silences[0], 2) if starts and starts[0] < 0.5 and silences else 0.0,
                "peakDb": stat("Peak level dB"), "peakCount": stat("Peak count"), "flatFactor": stat("Flat factor")}

    def _render(self, context: JobContext, source: Path, analysis: dict[str, Any], standard: Path,
                datasaver: Path) -> None:
        m = analysis["loudness"]
        loudnorm = (f"loudnorm=I={TARGET_I}:TP={TARGET_TP}:LRA={TARGET_LRA}:measured_I={m['input_i']}:"
                    f"measured_TP={m['input_tp']}:measured_LRA={m['input_lra']}:measured_thresh={m['input_thresh']}:"
                    f"offset={m['target_offset']}:linear=true")
        graph = f"[0:a]aformat=channel_layouts=mono,{loudnorm},aresample=44100,asplit=2[std][low];[low]aresample=22050[ds]"
        _run(context, [self.ffmpeg, "-hide_banner", "-nostats", "-y", "-i", str(source), "-filter_complex", graph,
                       "-map", "[std]", "-c:a", "aac", "-b:a", "64k", "-ac", "1", "-movflags", "+faststart",
                       "-map_metadata", "-1", str(standard),
                       "-map", "[ds]", "-c:a", "aac", "-b:a", "32k", "-ac", "1", "-movflags", "+faststart",
                       "-map_metadata", "-1", str(datasaver)])

    def _pcm_analysis(self, context: JobContext, audio: Path, points: int = 200) -> tuple[list[float], float | None]:
        """Waveform peaks, plus a noise-floor estimate measured on the loudness-normalized audio.

        The noise floor is the 10th percentile of 50 ms RMS windows, ignoring digital silence, so it
        reflects room/background noise between words rather than edited-out gaps.
        """
        rate = 8000
        result = _run(context, [self.ffmpeg, "-hide_banner", "-nostats", "-i", str(audio), "-ac", "1", "-ar", str(rate),
                                "-f", "s16le", "-"])
        samples = array.array("h")
        samples.frombytes(result.stdout[: len(result.stdout) // 2 * 2])
        if not samples:
            return [], None
        size = max(len(samples) // points, 1)
        peaks = [max(map(abs, samples[i:i + size])) for i in range(0, len(samples), size)][:points]
        top = max(peaks) or 1
        window = rate // 20
        levels = []
        for start in range(0, len(samples) - window, window):
            chunk = samples[start:start + window]
            energy = sum(value * value for value in chunk) / window
            if energy > 1:  # skip digital silence
                levels.append(energy)
        noise = None
        if len(levels) >= 20:
            import math
            levels.sort()
            noise = round(10 * math.log10(levels[len(levels) // 10] / (32768 ** 2)), 1)
        return [round(value / top, 3) for value in peaks], noise

    def _qc(self, probe: dict[str, Any], analysis: dict[str, Any]) -> dict[str, Any]:
        loudness = analysis["loudness"]
        integrated, true_peak = _float(loudness.get("input_i")), _float(loudness.get("input_tp"))
        noise = analysis.get("noiseFloorDb")
        duration = probe["duration"]
        silence_ratio = analysis["silenceSeconds"] / duration if duration else 0
        checks: list[dict[str, Any]] = []

        def check(code: str, level: str, message: str, tip: str | None = None) -> None:
            checks.append({"code": code, "level": level, "message": message, **({"tip": tip} if tip else {})})

        if integrated is not None and integrated < -35:
            check("too-quiet", "fail", f"The recording is very quiet ({integrated:.0f} LUFS).",
                  "Move closer to the microphone (about a hand's width) and raise the input level.")
        elif integrated is not None and integrated < -28:
            check("quiet", "warn", f"The recording is quiet ({integrated:.0f} LUFS); we boosted it, which also raises background noise.",
                  "Next time, move a little closer to the microphone.")
        # Clipping shows up as runs of samples pinned at full scale, not merely a loud master.
        peak = analysis.get("peakDb")
        if peak is not None and peak > -0.1 and ((analysis.get("peakCount") or 0) > 50 or (analysis.get("flatFactor") or 0) > 1):
            check("clipping", "warn", "Some loud moments may be distorted (clipping).",
                  "Lower the input level slightly or move back from the microphone during loud parts.")
        if noise is not None and noise > -48:
            check("background-sound", "warn",
                  f"Background sound stays audible between words (about {noise:.0f} dB after levelling).",
                  "If it's intended music, that's fine. Otherwise record in a quieter room, away from fans and traffic.")
        if silence_ratio > 0.6:
            check("mostly-silence", "fail", f"About {silence_ratio:.0%} of the recording is silence.",
                  "Check the microphone was working, then record again.")
        elif silence_ratio > 0.25:
            check("long-pauses", "warn", f"About {silence_ratio:.0%} of the recording is silence.",
                  "Trim long pauses, or check the recording didn't keep running after you finished.")
        if analysis.get("leadingSilence", 0) > 5:
            check("slow-start", "warn", f"The story starts after {analysis['leadingSilence']:.0f} seconds of silence.",
                  "Start speaking within a couple of seconds of pressing record.")
        if duration < 30:
            check("too-short", "fail", f"The recording is only {duration:.0f} seconds long.",
                  "Upload the complete story.")
        if probe.get("sampleRate") and probe["sampleRate"] < 22050:
            check("low-sample-rate", "warn", f"Low recording quality ({probe['sampleRate']} Hz).",
                  "Record at 44.1 kHz or 48 kHz if your app allows it.")
        verdict = "fail" if any(c["level"] == "fail" for c in checks) else "warn" if checks else "pass"
        return {"verdict": verdict, "checks": checks, "integratedLufs": integrated, "truePeakDb": true_peak,
                "loudnessRange": _float(loudness.get("input_lra")), "noiseFloorDb": noise,
                "peakDb": analysis.get("peakDb"), "silenceSeconds": analysis["silenceSeconds"],
                "silenceRatio": round(silence_ratio, 3), "speechRatio": round(1 - silence_ratio, 3),
                "sourceCodec": probe.get("codec"),
                "targetLufs": TARGET_I}
