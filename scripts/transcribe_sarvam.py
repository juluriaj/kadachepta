"""Run a bounded Sarvam Saaras batch and persist results locally."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from sarvamai import SarvamAI


def load_secret() -> str:
    value = os.getenv("SARVAM_API_KEY")
    if value:
        return value
    path = Path("config/secrets.local.json")
    if path.exists():
        payload = json.loads(path.read_text(encoding="utf-8"))
        value = payload.get("sarvam", {}).get("apiKey")
        if value:
            return value
    raise RuntimeError("Set SARVAM_API_KEY or configure config/secrets.local.json.")


def main() -> int:
    parser = argparse.ArgumentParser(description="Transcribe a bounded local benchmark with Sarvam.")
    parser.add_argument("--database", type=Path, default=Path("catalog/kadachepta.db"))
    parser.add_argument("--limit", type=int, default=3)
    parser.add_argument("--asset-id")
    parser.add_argument("--model", default="saaras:v4")
    parser.add_argument("--language", default="te-IN")
    parser.add_argument("--output", type=Path, default=Path("catalog/transcripts"))
    args = parser.parse_args()
    if args.limit < 1 or args.limit > 20:
        parser.error("--limit must be between 1 and 20.")

    api_key = load_secret()
    with sqlite3.connect(args.database) as connection:
        assets = connection.execute(
            """
            SELECT id, source_path, title, checksum_sha256
            FROM audio_assets
            WHERE id = COALESCE(?, id)
              AND status IN ('draft', 'needs-review')
              AND NOT EXISTS (
                SELECT 1 FROM transcripts t
                WHERE t.audio_asset_id = audio_assets.id
                  AND t.status IN ('draft', 'needs-review', 'approved')
              )
            ORDER BY id
            LIMIT ?
            """,
            (args.asset_id, args.limit),
        ).fetchall()
    if not assets:
        print("No eligible audio assets found.")
        return 0

    client = SarvamAI(api_subscription_key=api_key)
    paths = [
        Path(row[1]) if Path(row[1]).parts and Path(row[1]).parts[0].lower() == "audio"
        else Path("audio") / row[1]
        for row in assets
    ]
    for path in paths:
        if not path.exists():
            raise FileNotFoundError(f"Audio asset is missing: {path}")

    job = client.speech_to_text_job.create_job(
        model=args.model,
        mode="transcribe",
        language_code=args.language,
        with_diarization=False,
        with_timestamps=True,
    )
    job.upload_files(file_paths=[str(path) for path in paths])
    job.start()
    job.wait_until_complete()
    results = job.get_file_results()
    args.output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as temporary:
        job.download_outputs(output_dir=temporary)
        output_files = list(Path(temporary).glob("*"))
        now = datetime.now(timezone.utc).isoformat()
        by_name = {path.name: path for path in output_files}
        with sqlite3.connect(args.database) as connection:
            for index, (asset_id, source_path, title, source_checksum) in enumerate(assets):
                source_name = Path(source_path).name
                result = next(
                    (item for item in results.get("successful", []) if item.get("file_name") == source_name),
                    None,
                )
                if not result:
                    connection.execute(
                        "UPDATE processing_jobs SET status = 'failed', attempts = attempts + 1, error = ?, updated_at = ? WHERE audio_asset_id = ? AND job_type = 'transcription'",
                        (json.dumps(results.get("failed", []), ensure_ascii=False), now, asset_id),
                    )
                    continue
                downloaded = by_name.get(result.get("output_file_name", result.get("file_name", "")))
                if not downloaded:
                    downloaded = output_files[index] if index < len(output_files) else None
                if not downloaded:
                    raise RuntimeError(f"Sarvam returned no output for {source_name}.")
                raw = json.loads(downloaded.read_text(encoding="utf-8"))
                text = raw.get("transcript") or raw.get("text") or ""
                segments = (
                    raw.get("timestamps")
                    or raw.get("chunks")
                    or raw.get("segments")
                    or []
                )
                target = args.output / f"{asset_id}.v1.json"
                target.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
                version = connection.execute(
                    "SELECT COALESCE(MAX(version), 0) + 1 FROM transcripts WHERE audio_asset_id = ?",
                    (asset_id,),
                ).fetchone()[0]
                cursor = connection.execute(
                    """
                    INSERT INTO transcripts (
                        audio_asset_id, version, language, text, segments_json,
                        provider, model, source_audio_checksum, status, created_at
                    ) VALUES (?, ?, ?, ?, ?, 'sarvam', ?, ?, 'needs-review', ?)
                    """,
                    (asset_id, version, args.language, text, json.dumps(segments, ensure_ascii=False), args.model, source_checksum, now),
                )
                connection.execute(
                    "UPDATE processing_jobs SET status = 'needs-review', attempts = attempts + 1, updated_at = ?, error = NULL WHERE audio_asset_id = ? AND job_type = 'transcription'",
                    (now, asset_id),
                )
                print(json.dumps({"assetId": asset_id, "title": title, "transcriptId": cursor.lastrowid, "file": str(target)}, ensure_ascii=False))
            connection.commit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
