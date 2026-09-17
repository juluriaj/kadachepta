"""Build a reviewable catalog draft from the local audio folder.

This stage intentionally does not transcribe or publish content. It extracts
stable metadata and media facts so later transcription/teaser jobs can be
idempotent and audited.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from mutagen import File


SUPPORTED_EXTENSIONS = {".mp3", ".m4a", ".aac", ".wav", ".flac", ".ogg"}


def first_tag(tags: Any, key: str) -> str | None:
    value = tags.get(key) if tags else None
    if isinstance(value, list):
        value = value[0] if value else None
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def normalized_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def asset_id(relative_path: str, checksum: str) -> str:
    return hashlib.sha1(f"{relative_path}:{checksum}".encode("utf-8")).hexdigest()[:16]


def checksum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_audio(path: Path, root: Path) -> tuple[dict[str, Any], str | None]:
    relative = path.relative_to(root).as_posix()
    file_hash = checksum(path)
    item = File(path, easy=True)
    if item is None:
        return {}, "unsupported-or-corrupt-audio"

    tags = item.tags or {}
    info = item.info
    title = first_tag(tags, "title") or path.stem
    album = first_tag(tags, "album")
    artist = first_tag(tags, "artist")
    track = first_tag(tags, "tracknumber")
    genre = first_tag(tags, "genre")
    year = first_tag(tags, "date")
    collection_path = path.parent.relative_to(root).as_posix()
    collection = album or (path.parent.name if path.parent != root else None)
    duration = round(float(getattr(info, "length", 0)), 3)
    record = {
        "id": asset_id(relative, file_hash),
        "kind": "audio",
        "status": "draft",
        "source": {
            "path": relative,
            "checksumSha256": file_hash,
            "extension": path.suffix.lower(),
            "sizeBytes": path.stat().st_size,
        },
        "metadata": {
            "title": title,
            "titleKey": normalized_key(title),
            "album": album,
            "collection": collection,
            "collectionPath": collection_path if collection_path != "." else None,
            "artist": artist,
            "narrator": artist,
            "trackNumber": track,
            "genre": genre,
            "language": "te" if (genre or "").lower() == "telugu" else None,
            "year": year,
        },
        "media": {
            "durationSeconds": duration,
            "durationMinutes": round(duration / 60, 2),
            "bitrate": getattr(info, "bitrate", None),
            "sampleRate": getattr(info, "sample_rate", None),
            "channels": getattr(info, "channels", None),
            "hasEmbeddedArtwork": bool(getattr(item, "pictures", [])),
        },
        "processing": {
            "transcription": {"status": "not-configured"},
            "teaser": {"status": "blocked-by-transcription"},
            "review": {"status": "needs-review"},
        },
    }
    return record, None


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a KathaChepta catalog draft.")
    parser.add_argument("--input", type=Path, default=Path("audio"))
    parser.add_argument("--output", type=Path, default=Path("catalog"))
    args = parser.parse_args()

    if not args.input.exists():
        parser.error(f"Input folder does not exist: {args.input}")

    args.output.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    seen_checksums: dict[str, str] = {}
    extension_counts: Counter[str] = Counter()

    for path in sorted(args.input.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            continue
        extension_counts[path.suffix.lower()] += 1
        try:
            record, error = read_audio(path, args.input)
            relative = path.relative_to(args.input).as_posix()
            if error:
                errors.append({"path": relative, "error": error})
                continue
            duplicate_of = seen_checksums.get(record["source"]["checksumSha256"])
            if duplicate_of:
                record["source"]["duplicateOf"] = duplicate_of
                record["status"] = "duplicate"
            else:
                seen_checksums[record["source"]["checksumSha256"]] = record["id"]
            records.append(record)
        except Exception as exc:  # Each file must fail visibly without stopping the batch.
            errors.append({"path": path.relative_to(args.input).as_posix(), "error": str(exc)})

    generated_at = datetime.now(timezone.utc).isoformat()
    report = {
        "generatedAt": generated_at,
        "input": str(args.input.resolve()),
        "totalFilesSeen": sum(extension_counts.values()),
        "recordsCreated": len(records),
        "errors": len(errors),
        "duplicates": sum(1 for item in records if item["status"] == "duplicate"),
        "extensions": dict(extension_counts),
        "durationHours": round(sum(item["media"]["durationSeconds"] for item in records) / 3600, 2),
        "transcription": {
            "status": "not-configured",
            "reason": "No Telugu speech-to-text provider is configured.",
            "nextStep": "Configure a provider adapter before transcription and teaser generation.",
        },
        "errorsDetail": errors,
    }
    payload = {"schemaVersion": 1, "generatedAt": generated_at, "items": records}
    (args.output / "catalog-draft.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (args.output / "import-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
