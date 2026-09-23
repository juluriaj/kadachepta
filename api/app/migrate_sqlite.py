"""One-time migration from the prototype's SQLite database to PostgreSQL.

    docker compose exec api python -m app.migrate_sqlite --sqlite /data/legacy-catalog/kadachepta.db [--reset]

- Keeps every asset ID, transcript/teaser ID, and checksum.
- Legacy audio stays where it is (storage keys under ``legacy/``); artwork and raw transcript files are copied
  into media storage.
- Stories without a narrator account are KathaChepta-owned (owner confirmed 2026-09-23), so they get an
  approved rights record with an owner attestation.
- Unfinished prototype jobs are recorded as cancelled so nothing (for example paid transcription) starts by itself.
- Writes a verification report comparing source and target counts and checksums.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from .db import get_sessionmaker
from .models import (
    AssetRights, AudioAsset, EditorialEvent, Household, Job, ListenerFavorite, ListeningDaily, ListeningProgress,
    NarratorCredit, NarratorProfile, Profile, TeaserDraft, Transcript, User,
)
from .services.assets import as_list, normalize_language
from .storage import get_storage

OWNER_ATTESTATION = "Owner confirmed KathaChepta holds rights to all prototype stories (2026-09-23)."
JOB_STATUS = {"completed": "succeeded", "approved": "succeeded", "needs-review": "succeeded", "failed": "dead"}
TABLES = [User, Household, Profile, NarratorProfile, AudioAsset, AssetRights, Transcript, TeaserDraft, Job, NarratorCredit,
          ListenerFavorite, ListeningProgress, ListeningDaily, EditorialEvent]


def ts(value: Any) -> datetime | None:
    if not value:
        return None
    text_value = str(value).strip().replace("Z", "+00:00").replace(" ", "T")
    try:
        parsed = datetime.fromisoformat(text_value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def when(value: Any) -> datetime:
    return ts(value) or datetime.now(timezone.utc)


def day(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value)[:10]) if value else None
    except ValueError:
        return None


def rows(source: sqlite3.Connection, table: str) -> list[sqlite3.Row]:
    exists = source.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
    return source.execute(f"SELECT * FROM {table}").fetchall() if exists else []


def legacy_key(source_path: str) -> str:
    relative = source_path.replace("\\", "/").lstrip("/")
    if relative.lower().startswith("audio/"):
        relative = relative[6:]
    return f"legacy/{relative}"


def copy_file(src: Path, key: str, report: dict) -> str | None:
    if not src.is_file():
        report["missingFiles"].append(str(src))
        return None
    with src.open("rb") as handle:
        get_storage().put_stream(key, handle)
    return key


def migrate(db: Session, source: sqlite3.Connection, catalog_dir: Path, report: dict) -> None:
    storage = get_storage()
    users: dict[str, int] = {}
    profiles: dict[str, int] = {}
    for row in rows(source, "editor_users"):
        user = User(username=row["username"], role=row["role"] or "editor", display_name=row["username"],
                    password_hash=row["password_hash"], created_at=when(row["created_at"]))
        db.add(user)
        db.flush()
        users[row["username"]] = user.id
        household = Household(owner_user_id=user.id, name=row["username"])
        db.add(household)
        db.flush()
        profile = Profile(household_id=household.id, name=row["username"], kind="adult")
        db.add(profile)
        db.flush()
        profiles[row["username"]] = profile.id
    for row in rows(source, "narrator_profiles"):
        if row["username"] in users:
            db.add(NarratorProfile(user_id=users[row["username"]], display_name=row["display_name"],
                                   biography=row["biography"], languages=[normalize_language(row["language"])]))

    narrator_rows = {row["audio_asset_id"]: row for row in rows(source, "narrator_assets")}
    for row in rows(source, "audio_assets"):
        narrator = narrator_rows.get(row["id"])
        key = legacy_key(row["source_path"])
        if not storage.exists(key):
            report["missingFiles"].append(key)
        keys = row.keys()
        asset = AudioAsset(
            id=row["id"], source_key=key, source_filename=Path(row["source_path"].replace("\\", "/")).name,
            checksum_sha256=row["checksum_sha256"], title=row["title"], album=row["album"],
            collection=row["collection"], artist=row["artist"], narrator_name=row["narrator"],
            narrator_user_id=users.get(narrator["narrator_username"]) if narrator else None,
            submitted_at=ts(narrator["submitted_at"]) if narrator else None,
            published_at=ts(narrator["published_at"]) if narrator else None,
            review_required=bool(narrator["review_required"]) if narrator else True,
            track_number=row["track_number"], episode_number=row["episode_number"] if "episode_number" in keys else None,
            genre=row["genre"], genres=as_list(row["genres_json"]) if "genres_json" in keys else [],
            language=normalize_language(row["language"]), year=row["year"],
            audience_age_range=row["audience_age_range"] if "audience_age_range" in keys else None,
            mood=row["mood"] if "mood" in keys else None,
            listening_contexts=as_list(row["listening_contexts_json"]) if "listening_contexts_json" in keys else [],
            content_warnings=as_list(row["content_warnings_json"]) if "content_warnings_json" in keys else [],
            keywords=as_list(row["keywords_json"]) if "keywords_json" in keys else [],
            moral_takeaway=row["moral_takeaway"] if "moral_takeaway" in keys else None,
            source_adaptation=row["source_adaptation"] if "source_adaptation" in keys else None,
            duration_seconds=row["duration_seconds"] or 0, bitrate=row["bitrate"], sample_rate=row["sample_rate"],
            channels=row["channels"], has_embedded_artwork=bool(row["has_embedded_artwork"]), status=row["status"],
            metadata_review_status=row["metadata_review_status"] if "metadata_review_status" in keys else "not-reviewed",
            parent_asset_id=row["parent_asset_id"] if "parent_asset_id" in keys else None,
            version_number=row["version_number"] if "version_number" in keys else 1,
            created_at=when(row["created_at"]), updated_at=when(row["updated_at"]),
        )
        if not asset.genres and asset.genre:
            asset.genres = [asset.genre]
        if asset.status == "published" and not asset.published_at:
            asset.published_at = asset.updated_at
        artwork = row["artwork_path"] if "artwork_path" in keys else None
        if artwork:
            source_file = catalog_dir / "artworks" / Path(artwork).name
            asset.artwork_key = copy_file(source_file, f"artworks/{row['id']}/legacy-{Path(artwork).name}", report)
            asset.artwork_updated_at = asset.updated_at if asset.artwork_key else None
        db.add(asset)
    db.flush()

    migrated_rights = set()
    for row in rows(source, "asset_rights"):
        migrated_rights.add(row["audio_asset_id"])
        db.add(AssetRights(
            audio_asset_id=row["audio_asset_id"], status=row["status"], rights_holder=row["rights_holder"] or None,
            recording_rights=bool(row["recording_rights"]), performance_rights=bool(row["performance_rights"]),
            adaptation_rights=bool(row["adaptation_rights"]), artwork_rights=bool(row["artwork_rights"]),
            music_rights=bool(row["music_rights"]), territory=row["territory"] or None,
            allowed_uses=row["allowed_uses"] or None, license_start=day(row["license_start"]),
            license_end=day(row["license_end"]), evidence_reference=row["evidence_reference"] or None,
            reviewer=row["reviewer"], review_notes=row["review_notes"] or None, updated_at=when(row["updated_at"])))
    owned = 0
    for asset_id in db.scalars(select(AudioAsset.id).where(AudioAsset.narrator_user_id.is_(None))):
        if asset_id in migrated_rights:
            continue
        db.add(AssetRights(
            audio_asset_id=asset_id, status="approved", source_type="kathachepta-owned", rights_holder="KathaChepta",
            recording_rights=True, performance_rights=True, adaptation_rights=True, artwork_rights=True,
            music_rights=True, territory="Worldwide", allowed_uses="streaming, download, preview, translation",
            evidence_reference=OWNER_ATTESTATION, attested_by="owner", attested_at=datetime.now(timezone.utc),
            reviewer="migration", review_notes=OWNER_ATTESTATION))
        owned += 1
    report["ownerAttestedRights"] = owned

    for row in rows(source, "transcripts"):
        raw_file = catalog_dir / "transcripts" / f"{row['audio_asset_id']}.v{row['version']}.json"
        raw_key = copy_file(raw_file, f"transcripts/{row['audio_asset_id']}/v{row['version']}-{row['provider'] or 'raw'}.json",
                            report) if raw_file.exists() else None
        segments = json.loads(row["segments_json"] or "[]") if row["segments_json"] else []
        db.add(Transcript(
            id=row["id"], audio_asset_id=row["audio_asset_id"], version=row["version"],
            language=normalize_language(row["language"]), text=row["text"], segments=segments, raw_key=raw_key,
            provider=row["provider"], model=row["model"], source_audio_checksum=row["source_audio_checksum"],
            status=row["status"], reviewer=row["reviewer"], review_notes=row["review_notes"],
            reviewed_at=ts(row["reviewed_at"]), created_at=when(row["created_at"])))
    db.flush()

    for row in rows(source, "teaser_drafts"):
        alternates = {}
        teaser_file = catalog_dir / "teasers" / f"{row['audio_asset_id']}.json"
        if teaser_file.exists():
            draft = json.loads(teaser_file.read_text(encoding="utf-8")).get("draft", {})
            if draft.get("teaserEn") or draft.get("shortEn"):
                alternates["en-IN"] = {"short": draft.get("shortEn"), "long": draft.get("teaserEn")}
        db.add(TeaserDraft(
            id=row["id"], audio_asset_id=row["audio_asset_id"], transcript_id=row["transcript_id"],
            language=normalize_language(row["language"]), short_text=row["short_text"], long_text=row["long_text"],
            alternates=alternates, themes=json.loads(row["themes_json"] or "[]"),
            mood=json.loads(row["mood_json"] or "[]"), age_suggestion=row["age_suggestion"],
            warnings=json.loads(row["warnings_json"] or "[]"), provider=row["provider"], model=row["model"],
            prompt_version=row["prompt_version"], status=row["status"], reviewer=row["reviewer"],
            review_notes=row["review_notes"], created_at=when(row["created_at"])))

    for row in rows(source, "processing_jobs"):
        status = JOB_STATUS.get(row["status"], "cancelled")
        db.add(Job(job_type=row["job_type"] if row["job_type"] in {"transcription", "teaser", "artwork"} else "transcription",
                   audio_asset_id=row["audio_asset_id"], status=status, attempts=row["attempts"] or 0,
                   error=row["error"] if status != "cancelled" else f"Migrated from prototype (was {row['status']}).",
                   created_by="migration", created_at=when(row["created_at"]), updated_at=when(row["updated_at"])))

    for row in rows(source, "narrator_credits"):
        if row["narrator_username"] in users:
            db.add(NarratorCredit(narrator_user_id=users[row["narrator_username"]], audio_asset_id=row["audio_asset_id"],
                                  awarded_at=when(row["awarded_at"]), reason=row["reason"]))
    for row in rows(source, "listener_favorites"):
        if row["username"] in users:
            db.add(ListenerFavorite(user_id=users[row["username"]], profile_id=profiles[row["username"]],
                                    audio_asset_id=row["audio_asset_id"],
                                    created_at=when(row["created_at"])))
    for row in rows(source, "listening_progress"):
        if row["username"] in users:
            db.add(ListeningProgress(
                user_id=users[row["username"]], profile_id=profiles[row["username"]],
                audio_asset_id=row["audio_asset_id"], seconds_listened=row["seconds_listened"], last_position=row["last_position"],
                play_count=row["play_count"], completed=bool(row["completed"]),
                first_listened_at=when(row["first_listened_at"]), last_listened_at=when(row["last_listened_at"])))
    for row in rows(source, "listening_daily"):
        if row["username"] in users:
            db.add(ListeningDaily(user_id=users[row["username"]], profile_id=profiles[row["username"]],
                                  day=day(row["day"]), seconds=row["seconds"]))
    for row in rows(source, "editorial_events"):
        db.add(EditorialEvent(entity_type=row["entity_type"], entity_id=row["entity_id"], action=row["action"],
                              actor=row["reviewer"], notes=row["notes"], created_at=when(row["created_at"])))
    db.flush()
    for table, column in (("transcripts", "id"), ("teaser_drafts", "id")):
        db.execute(text(f"SELECT setval(pg_get_serial_sequence('{table}', '{column}'), "
                        f"COALESCE((SELECT MAX({column}) FROM {table}), 0) + 1, false)"))


def verify(db: Session, source: sqlite3.Connection, report: dict) -> bool:
    pairs = {"editor_users": User, "audio_assets": AudioAsset, "transcripts": Transcript,
             "teaser_drafts": TeaserDraft, "processing_jobs": Job, "narrator_credits": NarratorCredit,
             "listener_favorites": ListenerFavorite, "listening_progress": ListeningProgress,
             "listening_daily": ListeningDaily, "editorial_events": EditorialEvent}
    counts, ok = {}, True
    for table, model in pairs.items():
        expected = len(rows(source, table))
        actual = db.scalar(select(func.count()).select_from(model))
        counts[table] = {"sqlite": expected, "postgres": actual, "match": expected == actual}
        ok &= expected == actual
    source_digest = hashlib.sha256("\n".join(
        f"{r['id']}:{r['checksum_sha256']}" for r in sorted(rows(source, "audio_assets"), key=lambda r: r["id"])).encode()).hexdigest()
    target_digest = hashlib.sha256("\n".join(
        f"{i}:{c}" for i, c in db.execute(select(AudioAsset.id, AudioAsset.checksum_sha256).order_by(AudioAsset.id))).encode()).hexdigest()
    report.update(counts=counts, assetChecksumDigest={"sqlite": source_digest, "postgres": target_digest,
                                                      "match": source_digest == target_digest})
    ok &= source_digest == target_digest
    report["ok"] = ok and not report["missingFiles"]
    return report["ok"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--sqlite", type=Path, default=Path("/data/legacy-catalog/kadachepta.db"))
    parser.add_argument("--reset", action="store_true", help="Delete all PostgreSQL data first.")
    args = parser.parse_args()
    if not args.sqlite.exists():
        sys.exit(f"SQLite database not found: {args.sqlite}")
    source = sqlite3.connect(f"file:{args.sqlite}?mode=ro", uri=True)
    source.row_factory = sqlite3.Row
    report: dict[str, Any] = {"source": str(args.sqlite), "startedAt": datetime.now(timezone.utc).isoformat(),
                              "missingFiles": []}
    with get_sessionmaker()() as db:
        if db.scalar(select(func.count()).select_from(User)):
            if not args.reset:
                sys.exit("PostgreSQL already has data. Re-run with --reset to replace it.")
            db.execute(text("TRUNCATE " + ", ".join(t.__tablename__ for t in TABLES) + ", auth_sessions, email_otps, "
                            "audit_log RESTART IDENTITY CASCADE"))
            db.commit()
        migrate(db, source, args.sqlite.parent, report)
        db.commit()
        ok = verify(db, source, report)
    report["finishedAt"] = datetime.now(timezone.utc).isoformat()
    text_report = json.dumps(report, indent=2, ensure_ascii=False)
    get_storage().put_bytes(f"reports/migration-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.json", text_report.encode())
    print(text_report)
    print("\nMIGRATION VERIFIED" if ok else "\nMIGRATION HAS PROBLEMS - see report above")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
