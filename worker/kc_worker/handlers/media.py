"""Mastering, loudness normalization, mobile renditions, waveform, and quality checks (ffmpeg).

Outputs:
  standard.m4a   mono AAC-LC 64 kbps, 44.1 kHz, loudness -16 LUFS / -1.5 dBTP (mastered when it helps)
  datasaver.m4a  mono AAC-LC 32 kbps, 22.05 kHz, same loudness
  compare.m4a    the recording as made at the same loudness (only when mastering changed it)
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
MIN_IMPROVEMENT_DB = 3.0  # full mastering must lower the background by this much, or it falls back to light

# Mastering (P2-18). The background between words decides how much to do; thresholds were calibrated on the
# 589-track seed catalog (2017-2021), which holds raw recordings, edited voice tracks, and music-bed productions.
MODEL_PATH = Path(__file__).resolve().parents[1] / "assets" / "rnnoise-std.rnnn"
SPECTRAL_FILTER = ("aformat=channel_layouts=mono,aresample=16000,asetnsamples=n=1024:p=0,"
                   "astats=metadata=1:reset=1:measure_perchannel=none:measure_overall=RMS_level,"
                   "aspectralstats=win_size=1024:overlap=0:measure=flatness,ametadata=print:file=-")
EDITED_SILENCE = 0.02  # share of digitally silent frames: someone cut or gated the pauses
PROFILES = {
    "music": ("none", "Music or effects under the voice: already produced, left as it is."),
    "tonal": ("none", "A steady tone under the voice (a music drone or electrical hum): left as it is; listen, and "
                      "choose Clean up if it's hum."),
    "edited": ("light", "Pauses already cut to silence: polished lightly (levels, harshness, fades)."),
    "clean": ("light", "Quiet background: polished lightly (levels, harshness, fades)."),
    "noise": ("full", "Steady background noise (fan, hiss, room): noise removed, then polished."),
    "hum": ("full", "Low electrical or motor hum: noise removed, then polished."),
    "unknown": ("none", "Too short to judge: left as it is."),
}
STRENGTHS = {"gentle": {"mix": 0.7, "ratio": 2.0}, "standard": {"mix": 0.85, "ratio": 2.5},
             "strong": {"mix": 1.0, "ratio": 3.5}}
FADE_IN, FADE_OUT = 0.15, 0.8
KEEP_LEAD, KEEP_TAIL = 0.3, 0.8  # seconds of quiet kept before the first word and after the last
WIDE_LRA = 10.0  # loudness range (LU) above which a recording also gets gentle compression


def gap_features(frames: list[tuple[float, float]]) -> dict[str, Any]:
    """Summarise 64 ms frames of (RMS dB, spectral flatness): what the quietest moments sound like."""
    import statistics

    live = sorted(level for level, _ in frames if level > -80)
    if len(live) < 50:
        return {}
    speech, cut = live[int(len(live) * 0.9)], live[int(len(live) * 0.15)]
    gaps = [(level, flat) for level, flat in frames if -80 < level <= cut]
    return {"gapDb": round(statistics.median(level for level, _ in gaps) - speech, 1),
            "gapSpread": round(statistics.pstdev(level for level, _ in gaps), 2),
            "gapFlatness": round(statistics.median(flat for _, flat in gaps), 3),
            "digitalSilence": round(sum(1 for level, _ in frames if level <= -80) / len(frames), 3)}


def background_profile(features: dict[str, Any]) -> tuple[str, str]:
    """music | tonal | edited | clean | noise | hum | unknown, with the reason shown to editors.

    gapDb: the quietest moments relative to the voice. gapSpread: how much they move (music moves, a fan
    doesn't). gapFlatness: noise-like (high) or tonal (low). topHz/stablePeaks: a fixed low peak is hum.
    """
    if not features:
        return "unknown", PROFILES["unknown"][1]
    if features["digitalSilence"] >= EDITED_SILENCE:
        name = "edited"
    elif features["gapDb"] > -20 or features["gapSpread"] >= 6:
        name = "music"
    elif features["gapDb"] <= -50:
        name = "clean"
    elif features["gapFlatness"] >= 0.4:
        name = "noise"
    elif features.get("topHz", 1000) < 125 and features.get("stablePeaks", 0) >= 0.14:
        name = "hum"
    else:
        name = "tonal"
    return name, PROFILES[name][1]


def choose_level(profile: str, mode: str, override: str | None) -> str:
    """An editor's choice for the story wins; then the admin setting; then the background profile."""
    if override in ("full", "light", "none"):
        return override
    if mode == "off":
        return "none"
    return PROFILES.get(profile, PROFILES["unknown"])[0]


def _filter_path(path: Path) -> str:
    return str(path).replace("\\", "/").replace(":", "\\:")


def mastering_chain(level: str, strength: str, input_i: float | None, input_lra: float | None = None) -> str:
    settings = STRENGTHS.get(strength, STRENGTHS["standard"])
    # Bring speech to about -20 LUFS first so levels mean the same thing for every file.
    gain = max(-20.0, min(30.0, -20.0 - input_i)) if input_i is not None else 0.0
    filters = ["aformat=channel_layouts=mono", "aresample=48000", f"volume={gain:.1f}dB"]
    if level == "full":
        filters += ["highpass=f=80", f"arnndn=m={_filter_path(MODEL_PATH)}:mix={settings['mix']}"]
    else:
        filters.append("highpass=f=60")
    filters += ["deesser=i=0.4:m=0.5:f=0.5",
                "equalizer=f=250:t=q:w=1:g=-1.5",   # less boxiness
                "equalizer=f=4000:t=q:w=1:g=1.5"]   # a little more clarity
    if input_lra is not None and input_lra > WIDE_LRA:
        # Only for wide swings (whispers next to shouts). Compressing ordinary narration lifts the background
        # between words, and loudness normalization then makes it louder still.
        filters.append(f"acompressor=threshold=-18dB:ratio={settings['ratio']}:attack=20:release=250:knee=6:"
                       "detection=rms")
    # Catch the few sharp peaks so normalization can apply one steady gain instead of riding the level.
    filters.append("alimiter=limit=0.5:attack=5:release=50:level=disabled")
    return ",".join(filters)


def trim_points(silencedetect_log: str, length: float) -> tuple[float, float]:
    """Where to cut dead air at the ends, keeping a little quiet so words aren't clipped."""
    starts = [float(v) for v in re.findall(r"silence_start:\s*(-?[\d.]+)", silencedetect_log)]
    ends = [float(v) for v in re.findall(r"silence_end:\s*([\d.]+)", silencedetect_log)]
    start, end = 0.0, length
    if starts and starts[0] <= 0.05 and ends and ends[0] - KEEP_LEAD > 0.5:
        start = ends[0] - KEEP_LEAD
    if starts and (len(ends) < len(starts) or ends[-1] >= length - 0.1) and starts[-1] > start:
        tail = starts[-1] + KEEP_TAIL
        if length - tail > 0.5:
            end = tail
    return round(max(start, 0.0), 2), round(end, 2)


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
        settings = inputs.get("settings") or {}
        mastering = self._background(context, source)
        mastering.update(mode=settings.get("audio.mastering") or "auto", override=inputs.get("mastering"))
        level = choose_level(mastering["profile"], mastering["mode"], mastering["override"])
        strength = settings.get("audio.masteringStrength") or "standard"
        before = None
        if level != "none":
            # The recording as made, at the same loudness, so editors and narrators can compare fairly; also the
            # baseline for judging whether noise removal helped.
            compare = context.scratch / "compare.m4a"
            self._render(context, source, analysis, compare, None)
            _, before = self._pcm_analysis(context, compare)

        standard, datasaver = context.scratch / "standard.m4a", context.scratch / "datasaver.m4a"
        while True:
            render_from, render_analysis = source, analysis
            if level != "none":
                render_from, details = self._master(context, source, analysis, level, strength)
                mastering.update(details)
                render_analysis = self._analyse(context, render_from)
            self._render(context, render_from, render_analysis, standard, datasaver)
            waveform, noise_floor = self._pcm_analysis(context, standard)
            if level == "full" and not mastering["override"] and before is not None and noise_floor is not None \
                    and noise_floor > before - MIN_IMPROVEMENT_DB:
                # Noise removal didn't lower the background, so it is probably music after all: polish lightly.
                context.log(f"Noise removal gave {before} -> {noise_floor} dB; using light mastering")
                mastering["fallback"] = f"Noise removal did not lower the background ({before} -> {noise_floor} dB)."
                level = "light"
                continue
            break
        mastering.update(level=level, strength=strength, beforeDb=before if level != "none" else noise_floor,
                         afterDb=noise_floor)
        if level == "none":
            for key in ("chain", "trimmedStart", "trimmedEnd"):
                mastering.pop(key, None)

        # Loudness, silence, and pacing describe the recording as made; background is what listeners will hear.
        qc = self._qc(probe, {**analysis, "noiseFloorDb": noise_floor, "mastered": level != "none",
                              "profile": mastering["profile"]})
        qc["mastering"] = mastering
        outputs = [("standard", standard, 64000, 44100), ("datasaver", datasaver, 32000, 22050)]
        if level != "none":
            outputs.append(("compare", compare, 64000, 44100))
        renditions = {}
        for name, path, bitrate, rate in outputs:
            key = context.client.upload(context.job["id"], path.name, path)
            renditions[name] = {"key": key, "bytes": path.stat().st_size, "bitrate": bitrate, "sampleRate": rate,
                                "mime": "audio/mp4", "codec": "aac-lc", "channels": 1}
        duration = self._probe(context, standard)["duration"] if level != "none" else probe["duration"]
        return {"durationSeconds": duration, "bitrate": probe["bitrate"], "sampleRate": probe["sampleRate"],
                "channels": probe["channels"], "renditions": renditions, "waveform": waveform, "qc": qc, **joined}

    def _background(self, context: JobContext, source: Path) -> dict[str, Any]:
        """Describe what sits between the words, to decide whether (and how much) to master a recording."""
        result = _run(context, [self.ffmpeg, "-hide_banner", "-nostats", "-i", str(source), "-af", SPECTRAL_FILTER,
                                "-f", "null", "-"])
        out = result.stdout.decode("utf-8", "replace")
        levels = [-120.0 if (value := _float(v)) is None else value for v in re.findall(r"RMS_level=(\S+)", out)]
        flatness = [_float(v) or 0.0 for v in re.findall(r"flatness=(\S+)", out)]
        features = gap_features(list(zip(levels, flatness)))
        if features and features["digitalSilence"] < EDITED_SILENCE:
            features.update(self._tonal(context, source))
        profile, reason = background_profile(features)
        context.log(f"Background: {profile} ({reason}) {features}")
        return {"profile": profile, "reason": reason, "features": features}

    def _tonal(self, context: JobContext, source: Path) -> dict[str, Any]:
        """Hum stays on one low frequency; a music bed's peaks move. Looks at the quietest moments only."""
        import numpy as np

        rate, size = 8000, 1024
        result = _run(context, [self.ffmpeg, "-hide_banner", "-nostats", "-i", str(source), "-ac", "1", "-ar",
                                str(rate), "-f", "s16le", "-"])
        pcm = result.stdout[: len(result.stdout) // 2 * 2]
        samples = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768
        count = len(samples) // size
        if count < 50:
            return {}
        frames = samples[: count * size].reshape(count, size)
        energy = (frames ** 2).mean(axis=1)
        live = energy > 1e-9
        if live.sum() < 50:
            return {}
        gaps = frames[live & (energy <= np.quantile(energy[live], 0.15))]
        spectrum = np.abs(np.fft.rfft(gaps * np.hanning(size), axis=1))[:, 4:]  # ignore below ~30 Hz
        mean = spectrum.mean(axis=0)
        values, counts = np.unique(spectrum.argmax(axis=1), return_counts=True)
        return {"topHz": round(float((values[counts.argmax()] + 4) * rate / size)),
                "stablePeaks": round(float(np.sort(mean)[-5:].sum() / mean.sum()), 3)}

    def _master(self, context: JobContext, source: Path, analysis: dict[str, Any], level: str,
                strength: str) -> tuple[Path, dict[str, Any]]:
        """Clean up and polish a recording for listening. The narrator's original is never changed.

        light: rumble filter, de-essing, a gentle voice EQ, and gentle compression so quiet and loud passages
        sit closer together. full: the same after speech noise removal (RNNoise). Both then trim long dead air
        at the start and end and add short fades. Loudness normalization follows, as for every story.
        """
        loudness = analysis["loudness"]
        chain = mastering_chain(level, strength, _float(loudness.get("input_i")), _float(loudness.get("input_lra")))
        stage = context.scratch / "mastering.wav"
        result = _run(context, [self.ffmpeg, "-hide_banner", "-nostats", "-y", "-i", str(source), "-af",
                                f"{chain},silencedetect=noise=-50dB:d=0.5", "-c:a", "pcm_s24le", str(stage)])
        length = self._probe(context, stage)["duration"]
        start, end = trim_points(result.stderr.decode("utf-8", "replace"), length)
        target = context.scratch / "mastered.wav"
        fades = (f"atrim=start={start:.2f}:end={end:.2f},asetpts=PTS-STARTPTS,afade=t=in:d={FADE_IN},"
                 f"afade=t=out:st={max(end - start - FADE_OUT, 0):.2f}:d={FADE_OUT}")
        _run(context, [self.ffmpeg, "-hide_banner", "-nostats", "-y", "-i", str(stage), "-af", fades,
                       "-c:a", "pcm_s24le", str(target)])
        context.log(f"Mastering ({level}, {strength}): trimmed {start:.1f}s at the start, {length - end:.1f}s at the end")
        return target, {"chain": chain.replace(_filter_path(MODEL_PATH), MODEL_PATH.name),
                        "trimmedStart": round(start, 2), "trimmedEnd": round(length - end, 2)}

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
                datasaver: Path | None) -> None:
        m = analysis["loudness"]
        loudnorm = (f"loudnorm=I={TARGET_I}:TP={TARGET_TP}:LRA={TARGET_LRA}:measured_I={m['input_i']}:"
                    f"measured_TP={m['input_tp']}:measured_LRA={m['input_lra']}:measured_thresh={m['input_thresh']}:"
                    f"offset={m['target_offset']}:linear=true")
        std = ["-c:a", "aac", "-b:a", "64k", "-ac", "1", "-movflags", "+faststart", "-map_metadata", "-1", str(standard)]
        if datasaver is None:
            graph = f"[0:a]aformat=channel_layouts=mono,{loudnorm},aresample=44100[std]"
            _run(context, [self.ffmpeg, "-hide_banner", "-nostats", "-y", "-i", str(source), "-filter_complex", graph,
                           "-map", "[std]", *std])
            return
        graph = f"[0:a]aformat=channel_layouts=mono,{loudnorm},aresample=44100,asplit=2[std][low];[low]aresample=22050[ds]"
        _run(context, [self.ffmpeg, "-hide_banner", "-nostats", "-y", "-i", str(source), "-filter_complex", graph,
                       "-map", "[std]", *std,
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
        profile = analysis.get("profile")
        if profile == "tonal":
            check("tonal-background", "warn", "A steady tone sits under the voice: a music drone, or electrical hum.",
                  "If it's intended music, that's fine. Otherwise record away from fans, fridges, and chargers.")
        elif noise is not None and noise > -48 and profile not in ("music", "edited"):
            # Music beds are intended, and in edited tracks the quietest moments are word tails, not background.
            check("background-sound", "warn",
                  f"Background sound stays audible between words (about {noise:.0f} dB after levelling"
                  + (", even after automatic clean-up)." if analysis.get("mastered") else ")."),
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
