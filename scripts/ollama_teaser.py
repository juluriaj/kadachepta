"""Generate a teaser draft from a reviewed Telugu transcript using Ollama.

This script intentionally does not transcribe audio. It only operates on an
explicit transcript file so generated copy cannot silently be based on guesses.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import urllib.error
import urllib.request
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a Telugu/English teaser with Ollama.")
    parser.add_argument("--transcript", type=Path, required=True)
    parser.add_argument("--title", required=True)
    parser.add_argument("--model", default=os.getenv("KADACHEPTA_OLLAMA_MODEL", "llama3.1:8b"))
    parser.add_argument("--endpoint", default=os.getenv("OLLAMA_ENDPOINT", "http://localhost:11434/api/generate"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--database", type=Path, default=Path("catalog/kadachepta.db"))
    parser.add_argument("--asset-id")
    parser.add_argument("--require-approved-transcript", action="store_true")
    args = parser.parse_args()

    if args.transcript.suffix.lower() == ".json":
        payload = json.loads(args.transcript.read_text(encoding="utf-8"))
        transcript = payload.get("transcript") or payload.get("text") or ""
    else:
        transcript = args.transcript.read_text(encoding="utf-8").strip()
    if not transcript:
        parser.error("Transcript is empty.")
    if args.require_approved_transcript:
        if not args.asset_id:
            parser.error("--asset-id is required when checking transcript approval.")
        with sqlite3.connect(args.database) as connection:
            status = connection.execute(
                "SELECT status FROM transcripts WHERE audio_asset_id = ? ORDER BY version DESC LIMIT 1",
                (args.asset_id,),
            ).fetchone()
        if not status or status[0] != "approved":
            raise SystemExit("The latest transcript must be approved before teaser generation.")

    prompt = f"""You are an editor for a family-safe Telugu audiobook app.
Create a non-spoiler teaser from the transcript below.
Use only facts present in the transcript. Do not invent names or events.
Return JSON only with exactly these keys:
teaserTe, teaserEn, shortTe, shortEn, themes, mood, ageSuggestion, contentWarnings.
teaserTe and teaserEn should each be 35 to 60 words.
The title is: {args.title}

TRANSCRIPT:
{transcript}
"""
    request_body = json.dumps({
        "model": args.model,
        "prompt": prompt,
        "stream": False,
        "format": "json",
        "options": {"temperature": 0.2},
    }).encode("utf-8")
    request = urllib.request.Request(
        args.endpoint,
        data=request_body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=600) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        raise SystemExit(f"Could not reach Ollama at {args.endpoint}: {exc}") from exc

    raw = result.get("response", "")
    try:
        teaser = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Ollama returned invalid JSON: {exc}") from exc

    output = {
        "status": "needs-review",
        "provider": "ollama",
        "model": args.model,
        "promptVersion": "teaser-v1-local",
        "title": args.title,
        "draft": teaser,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.asset_id:
        now = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()
        with sqlite3.connect(args.database) as connection:
            transcript_id = connection.execute(
                "SELECT id FROM transcripts WHERE audio_asset_id = ? ORDER BY version DESC LIMIT 1",
                (args.asset_id,),
            ).fetchone()
            if not transcript_id:
                raise SystemExit(f"No transcript exists for asset {args.asset_id}.")
            connection.execute(
                """
                INSERT INTO teaser_drafts (
                    audio_asset_id, transcript_id, language, short_text, long_text,
                    themes_json, mood_json, age_suggestion, warnings_json,
                    source_segments_json, provider, model, prompt_version, status, created_at
                ) VALUES (?, ?, 'te', ?, ?, ?, ?, ?, ?, '[]', 'ollama', ?, ?, 'needs-review', ?)
                """,
                (
                    args.asset_id, transcript_id[0],
                    teaser.get("shortTe"), teaser.get("teaserTe"),
                    json.dumps(teaser.get("themes", []), ensure_ascii=False),
                    json.dumps(teaser.get("mood", []), ensure_ascii=False),
                    str(teaser.get("ageSuggestion", "")),
                    json.dumps(teaser.get("contentWarnings", []), ensure_ascii=False),
                    args.model, output["promptVersion"], now,
                ),
            )
            connection.commit()
    print(json.dumps({"output": str(args.output), "status": "needs-review", "model": args.model}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
