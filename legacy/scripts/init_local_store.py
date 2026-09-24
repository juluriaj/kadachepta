"""Create the local-first KathaChepta SQLite store from catalog-draft.json."""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path


SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS audio_assets (
    id TEXT PRIMARY KEY,
    source_path TEXT NOT NULL UNIQUE,
    checksum_sha256 TEXT NOT NULL,
    title TEXT NOT NULL,
    album TEXT,
    collection TEXT,
    artist TEXT,
    narrator TEXT,
    track_number TEXT,
    genre TEXT,
    genres_json TEXT NOT NULL DEFAULT '[]',
    language TEXT,
    episode_number TEXT,
    audience_age_range TEXT,
    mood TEXT,
    listening_contexts_json TEXT NOT NULL DEFAULT '[]',
    content_warnings_json TEXT NOT NULL DEFAULT '[]',
    moral_takeaway TEXT,
    source_adaptation TEXT,
    keywords_json TEXT NOT NULL DEFAULT '[]',
    year TEXT,
    duration_seconds REAL NOT NULL,
    bitrate INTEGER,
    sample_rate INTEGER,
    channels INTEGER,
    has_embedded_artwork INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'draft',
    metadata_review_status TEXT NOT NULL DEFAULT 'not-reviewed',
    artwork_path TEXT,
    parent_asset_id TEXT,
    version_number INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS transcripts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    audio_asset_id TEXT NOT NULL REFERENCES audio_assets(id),
    version INTEGER NOT NULL,
    language TEXT NOT NULL,
    text TEXT,
    segments_json TEXT,
    provider TEXT,
    model TEXT,
    source_audio_checksum TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'not-configured',
    reviewer TEXT,
    review_notes TEXT,
    reviewed_at TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(audio_asset_id, version)
);

CREATE TABLE IF NOT EXISTS teaser_drafts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    audio_asset_id TEXT NOT NULL REFERENCES audio_assets(id),
    transcript_id INTEGER REFERENCES transcripts(id),
    language TEXT NOT NULL,
    short_text TEXT,
    long_text TEXT,
    themes_json TEXT,
    mood_json TEXT,
    age_suggestion TEXT,
    warnings_json TEXT,
    source_segments_json TEXT,
    provider TEXT,
    model TEXT,
    prompt_version TEXT,
    status TEXT NOT NULL DEFAULT 'blocked-by-transcription',
    reviewer TEXT,
    review_notes TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS processing_jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    audio_asset_id TEXT NOT NULL REFERENCES audio_assets(id),
    job_type TEXT NOT NULL,
    status TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    error TEXT,
    provider_request_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS narrator_assets (
    audio_asset_id TEXT PRIMARY KEY REFERENCES audio_assets(id),
    narrator_username TEXT NOT NULL,
    submitted_at TEXT NOT NULL,
    published_at TEXT,
    review_required INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS narrator_credits (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    narrator_username TEXT NOT NULL,
    audio_asset_id TEXT NOT NULL UNIQUE REFERENCES audio_assets(id),
    awarded_at TEXT NOT NULL,
    reason TEXT NOT NULL DEFAULT 'approved publication'
);

CREATE TABLE IF NOT EXISTS narrator_profiles (
    username TEXT PRIMARY KEY,
    display_name TEXT,
    biography TEXT,
    language TEXT NOT NULL DEFAULT 'te-IN',
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS asset_rights (
    audio_asset_id TEXT PRIMARY KEY REFERENCES audio_assets(id),
    status TEXT NOT NULL DEFAULT 'needs-review',
    rights_holder TEXT,
    recording_rights INTEGER NOT NULL DEFAULT 0,
    performance_rights INTEGER NOT NULL DEFAULT 0,
    adaptation_rights INTEGER NOT NULL DEFAULT 0,
    artwork_rights INTEGER NOT NULL DEFAULT 0,
    music_rights INTEGER NOT NULL DEFAULT 0,
    territory TEXT,
    allowed_uses TEXT,
    license_start TEXT,
    license_end TEXT,
    evidence_reference TEXT,
    reviewer TEXT,
    review_notes TEXT,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_assets_collection ON audio_assets(collection);
CREATE INDEX IF NOT EXISTS idx_assets_status ON audio_assets(status);
CREATE INDEX IF NOT EXISTS idx_transcripts_status ON transcripts(status);
CREATE INDEX IF NOT EXISTS idx_teasers_status ON teaser_drafts(status);
"""


def ensure_schema_columns(connection: sqlite3.Connection) -> None:
    columns = {row[1] for row in connection.execute("PRAGMA table_info(transcripts)")}
    for name, definition in (
        ("reviewer", "TEXT"),
        ("review_notes", "TEXT"),
        ("reviewed_at", "TEXT"),
    ):
        if name not in columns:
            connection.execute(f"ALTER TABLE transcripts ADD COLUMN {name} {definition}")
    asset_columns = {row[1] for row in connection.execute("PRAGMA table_info(audio_assets)")}
    for name, definition in (
        ("parent_asset_id", "TEXT"),
        ("version_number", "INTEGER NOT NULL DEFAULT 1"),
        ("genres_json", "TEXT NOT NULL DEFAULT '[]'"),
        ("episode_number", "TEXT"),
        ("audience_age_range", "TEXT"),
        ("mood", "TEXT"),
        ("listening_contexts_json", "TEXT NOT NULL DEFAULT '[]'"),
        ("content_warnings_json", "TEXT NOT NULL DEFAULT '[]'"),
        ("moral_takeaway", "TEXT"),
        ("source_adaptation", "TEXT"),
        ("keywords_json", "TEXT NOT NULL DEFAULT '[]'"),
        ("metadata_review_status", "TEXT NOT NULL DEFAULT 'not-reviewed'"),
    ):
        if name not in asset_columns:
            connection.execute(f"ALTER TABLE audio_assets ADD COLUMN {name} {definition}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Initialize the local KathaChepta SQLite store.")
    parser.add_argument("--catalog", type=Path, default=Path("catalog/catalog-draft.json"))
    parser.add_argument("--database", type=Path, default=Path("catalog/kadachepta.db"))
    args = parser.parse_args()

    if not args.catalog.exists():
        parser.error(f"Catalog draft does not exist: {args.catalog}")

    payload = json.loads(args.catalog.read_text(encoding="utf-8"))
    generated_at = payload.get("generatedAt", "")
    args.database.parent.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(args.database) as connection:
        connection.executescript(SCHEMA)
        ensure_schema_columns(connection)
        for item in payload["items"]:
            metadata = item["metadata"]
            media = item["media"]
            source = item["source"]
            connection.execute(
                """
                INSERT INTO audio_assets (
                    id, source_path, checksum_sha256, title, album, collection,
                    artist, narrator, track_number, genre, genres_json, language,
                    episode_number, audience_age_range, mood, listening_contexts_json,
                    content_warnings_json, moral_takeaway, source_adaptation, keywords_json, year,
                    duration_seconds, bitrate, sample_rate, channels,
                    has_embedded_artwork, status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    source_path = excluded.source_path,
                    checksum_sha256 = excluded.checksum_sha256,
                    title = excluded.title,
                    album = excluded.album,
                    collection = excluded.collection,
                    artist = excluded.artist,
                    narrator = excluded.narrator,
                    track_number = excluded.track_number,
                    genre = excluded.genre,
                    genres_json = excluded.genres_json,
                    language = excluded.language,
                    episode_number = excluded.episode_number,
                    audience_age_range = excluded.audience_age_range,
                    mood = excluded.mood,
                    listening_contexts_json = excluded.listening_contexts_json,
                    content_warnings_json = excluded.content_warnings_json,
                    moral_takeaway = excluded.moral_takeaway,
                    source_adaptation = excluded.source_adaptation,
                    keywords_json = excluded.keywords_json,
                    year = excluded.year,
                    duration_seconds = excluded.duration_seconds,
                    bitrate = excluded.bitrate,
                    sample_rate = excluded.sample_rate,
                    channels = excluded.channels,
                    has_embedded_artwork = excluded.has_embedded_artwork,
                    updated_at = excluded.updated_at
                """,
                (
                    item["id"], source["path"], source["checksumSha256"],
                    metadata["title"], metadata.get("album"), metadata.get("collection"),
                    metadata.get("artist"), metadata.get("narrator"), metadata.get("trackNumber"),
                    metadata.get("genre"),
                    json.dumps(metadata.get("genres") or ([metadata["genre"]] if metadata.get("genre") else []), ensure_ascii=False),
                    metadata.get("language"), metadata.get("episodeNumber"),
                    metadata.get("audienceAgeRange"), metadata.get("mood"),
                    json.dumps(metadata.get("listeningContexts") or [], ensure_ascii=False),
                    json.dumps(metadata.get("contentWarnings") or [], ensure_ascii=False),
                    metadata.get("moralTakeaway"), metadata.get("sourceAdaptation"),
                    json.dumps(metadata.get("keywords") or [], ensure_ascii=False), metadata.get("year"),
                    media["durationSeconds"], media.get("bitrate"), media.get("sampleRate"),
                    media.get("channels"), int(media.get("hasEmbeddedArtwork", False)),
                    item["status"], generated_at, generated_at,
                ),
            )
            connection.execute(
                """
                INSERT INTO processing_jobs (audio_asset_id, job_type, status, created_at, updated_at)
                SELECT ?, 'transcription', 'not-configured', ?, ?
                WHERE NOT EXISTS (
                    SELECT 1 FROM processing_jobs
                    WHERE audio_asset_id = ? AND job_type = 'transcription'
                )
                """,
                (item["id"], generated_at, generated_at, item["id"]),
            )
        connection.commit()
        count = connection.execute("SELECT COUNT(*) FROM audio_assets").fetchone()[0]
        jobs = connection.execute("SELECT COUNT(*) FROM processing_jobs").fetchone()[0]

    print(json.dumps({"database": str(args.database), "audioAssets": count, "jobs": jobs}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
