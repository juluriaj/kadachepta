"""Local editor workspace server using only Python's standard library."""

from __future__ import annotations

import hashlib
import http.cookies
import http.server
import json
import email
import email.policy
import os
import secrets
import sqlite3
import subprocess
import sys
import threading
import time
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "catalog" / "kadachepta.db"
EDITOR_DIR = ROOT / "editor"
NARRATOR_DIR = ROOT / "narrator"
SESSIONS: dict[str, tuple[str, float]] = {}
ROLE_PERMISSIONS = {
    "listener": {"catalog.read"},
    "parent": {"catalog.read", "library.manage"},
    "narrator": {"catalog.read", "narrator.upload", "narrator.pipeline", "narrator.history"},
    "editor": {"catalog.read", "transcript.review", "teaser.review", "content.publish", "rights.manage", "metadata.review"},
    "admin": {
        "catalog.read", "library.manage", "transcript.review",
        "teaser.review", "content.publish", "users.manage", "rights.manage", "metadata.review",
    },
}


def db():
    connection = sqlite3.connect(DB)
    connection.row_factory = sqlite3.Row
    return connection


def hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 240_000)
    return f"{salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        salt_hex, digest_hex = stored.split("$", 1)
        actual = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt_hex), 240_000)
        return secrets.compare_digest(actual.hex(), digest_hex)
    except (ValueError, TypeError):
        return False


def ensure_auth_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS editor_users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'editor',
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS editorial_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            entity_type TEXT NOT NULL,
            entity_id TEXT NOT NULL,
            action TEXT NOT NULL,
            reviewer TEXT NOT NULL,
            notes TEXT,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS narrator_assets (
            audio_asset_id TEXT PRIMARY KEY REFERENCES audio_assets(id),
            narrator_username TEXT NOT NULL REFERENCES editor_users(username),
            submitted_at TEXT NOT NULL,
            published_at TEXT,
            review_required INTEGER NOT NULL DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS narrator_credits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            narrator_username TEXT NOT NULL REFERENCES editor_users(username),
            audio_asset_id TEXT NOT NULL UNIQUE REFERENCES audio_assets(id),
            awarded_at TEXT NOT NULL,
            reason TEXT NOT NULL DEFAULT 'approved publication'
        );
        CREATE TABLE IF NOT EXISTS narrator_profiles (
            username TEXT PRIMARY KEY REFERENCES editor_users(username),
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
        CREATE INDEX IF NOT EXISTS idx_narrator_assets_user ON narrator_assets(narrator_username);
        CREATE INDEX IF NOT EXISTS idx_narrator_credits_user ON narrator_credits(narrator_username);
        """
    )
    columns = {row[1] for row in connection.execute("PRAGMA table_info(editor_users)")}
    if "role" not in columns:
        connection.execute("ALTER TABLE editor_users ADD COLUMN role TEXT NOT NULL DEFAULT 'editor'")
    asset_columns = {row[1] for row in connection.execute("PRAGMA table_info(audio_assets)")}
    if asset_columns:
        if "parent_asset_id" not in asset_columns:
            connection.execute("ALTER TABLE audio_assets ADD COLUMN parent_asset_id TEXT")
        if "version_number" not in asset_columns:
            connection.execute("ALTER TABLE audio_assets ADD COLUMN version_number INTEGER NOT NULL DEFAULT 1")
        for name, definition in (
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
    if not connection.execute("SELECT 1 FROM editor_users LIMIT 1").fetchone():
        password = os.getenv("KADACHEPTA_EDITOR_PASSWORD", "change-me")
        connection.execute(
            "INSERT INTO editor_users (username, password_hash, role, created_at) VALUES ('editor', ?, 'editor', datetime('now'))",
            (hash_password(password),),
        )
        connection.commit()
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        connection.execute(
        "INSERT OR IGNORE INTO narrator_profiles (username, display_name, language, updated_at) SELECT username, username, 'te-IN', ? FROM editor_users WHERE role='narrator'",
        (now,),
        )
        connection.commit()


def json_bytes(payload: object) -> bytes:
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


METADATA_JSON_FIELDS = {
    "genres": "genres_json",
    "listeningContexts": "listening_contexts_json",
    "contentWarnings": "content_warnings_json",
    "keywords": "keywords_json",
}


def metadata_list(value: object) -> list[str]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            value = [part.strip() for part in value.split(",")]
    if not isinstance(value, (list, tuple)):
        value = [value] if value else []
    return list(dict.fromkeys(str(item).strip() for item in value if str(item).strip()))


def metadata_from_row(row: sqlite3.Row) -> dict:
    result = {}
    names = {
        "title": "title", "album": "album", "collection": "collection",
        "episodeNumber": "episode_number", "language": "language",
        "audienceAgeRange": "audience_age_range", "mood": "mood",
        "moralTakeaway": "moral_takeaway", "sourceAdaptation": "source_adaptation",
    }
    for output, column in names.items():
        result[output] = row[column]
    for output, column in METADATA_JSON_FIELDS.items():
        result[output] = metadata_list(row[column])
    return result


def add_metadata(payload: dict, row: sqlite3.Row) -> dict:
    payload["metadata"] = metadata_from_row(row)
    payload["metadataReviewStatus"] = row["metadataReviewStatus"] if "metadataReviewStatus" in row.keys() else row["metadata_review_status"]
    return payload


def upload_metadata(fields: dict[str, str], filename: str) -> dict:
    values = {}
    for key in ("title", "album", "collection", "episodeNumber", "language",
                "audienceAgeRange", "mood", "moralTakeaway", "sourceAdaptation"):
        values[key] = (fields.get(key) or "").strip() or None
    values["title"] = values["title"] or Path(filename).stem
    for key in METADATA_JSON_FIELDS:
        values[key] = metadata_list(fields.get(key, fields.get(f"{key}[]", "")))
    return values


def missing_publication_metadata(row: sqlite3.Row) -> list[str]:
    required = {
        "title": row["title"],
        "genres": metadata_list(row["genres_json"]),
        "language": row["language"],
        "audienceAgeRange": row["audience_age_range"],
        "moralTakeaway": row["moral_takeaway"],
        "sourceAdaptation": row["source_adaptation"],
    }
    return [name for name, value in required.items() if not value]


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, format: str, *args) -> None:
        print(format % args)

    def send_json(self, status: int, payload: object) -> None:
        body = json_bytes(payload)
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        return json.loads(self.rfile.read(length) or b"{}")

    def read_upload(self) -> tuple[str, bytes, dict[str, str]]:
        content_type = self.headers.get("Content-Type", "")
        if "multipart/form-data" not in content_type:
            raise ValueError("Upload must use multipart/form-data.")
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length)
        message = email.message_from_bytes(
            b"Content-Type: " + content_type.encode() + b"\r\nMIME-Version: 1.0\r\n\r\n" + raw,
            policy=email.policy.default,
        )
        fields: dict[str, str] = {}
        audio: tuple[str, bytes] | None = None
        for part in message.walk():
            if part.is_multipart():
                continue
            name = part.get_param("name", header="Content-Disposition")
            if name == "audio":
                filename = Path(part.get_filename() or "narration.mp3").name
                audio = (filename, part.get_payload(decode=True) or b"")
            elif name:
                fields[name] = (part.get_payload(decode=True) or b"").decode("utf-8")
        if audio:
            return audio[0], audio[1], fields
        raise ValueError("The upload must include an audio file.")

    def user(self) -> str | None:
        cookie = http.cookies.SimpleCookie(self.headers.get("Cookie", ""))
        token = cookie.get("editor_session")
        if not token:
            return None
        session = SESSIONS.get(token.value)
        if not session or session[1] < time.time():
            return None
        return session[0]

    def identity(self) -> dict | None:
        username = self.user()
        if not username:
            return None
        with db() as connection:
            ensure_auth_schema(connection)
            row = connection.execute(
                "SELECT username, role FROM editor_users WHERE username=?",
                (username,),
            ).fetchone()
        if not row:
            return None
        return {
            "username": row["username"],
            "role": row["role"],
            "permissions": sorted(ROLE_PERMISSIONS.get(row["role"], set())),
        }

    def require_permission(self, permission: str) -> dict | None:
        identity = self.identity()
        if not identity:
            self.send_json(401, {"error": "Login required."})
            return None
        if permission not in identity["permissions"]:
            self.send_json(403, {"error": "Insufficient permission."})
            return None
        return identity

    def do_GET(self) -> None:
        path = urllib.parse.urlparse(self.path).path
        public_files = {
            "/": (ROOT / "index.html", "text/html; charset=utf-8"),
            "/styles.css": (ROOT / "styles.css", "text/css; charset=utf-8"),
            "/app.js": (ROOT / "app.js", "text/javascript; charset=utf-8"),
        }
        if path in public_files:
            if path == "/":
                identity = self.identity()
                if identity and identity["role"] in {"editor", "admin"}:
                    self.send_response(302)
                    self.send_header("Location", "/editor/")
                    self.end_headers()
                    return
                if identity and identity["role"] == "narrator":
                    self.send_response(302)
                    self.send_header("Location", "/narrator/")
                    self.end_headers()
                    return
            return self.serve_file(*public_files[path])
        if path == "/editor" or path == "/editor/":
            identity = self.identity()
            if not identity:
                self.send_response(302)
                self.send_header("Location", "/")
                self.end_headers()
                return
            if identity["role"] not in {"editor", "admin"}:
                self.send_response(302)
                self.send_header("Location", "/")
                self.end_headers()
                return
            return self.serve_file(EDITOR_DIR / "index.html", "text/html; charset=utf-8")
        if path == "/narrator" or path == "/narrator/":
            identity = self.identity()
            if not identity or identity["role"] != "narrator":
                self.send_response(302)
                self.send_header("Location", "/")
                self.end_headers()
                return
            return self.serve_file(NARRATOR_DIR / "index.html", "text/html; charset=utf-8")
        if path == "/api/narrator/dashboard":
            identity = self.require_permission("narrator.pipeline")
            if not identity: return
            with db() as connection:
                counts = {
                    row["status"]: row["count"]
                    for row in connection.execute(
                        """
                        SELECT a.status, COUNT(*) count
                        FROM narrator_assets n JOIN audio_assets a ON a.id=n.audio_asset_id
                        WHERE n.narrator_username=? GROUP BY a.status
                        """,
                        (identity["username"],),
                    )
                }
                credits = connection.execute(
                    "SELECT COUNT(*) FROM narrator_credits WHERE narrator_username=?",
                    (identity["username"],),
                ).fetchone()[0]
                profile = connection.execute(
                    "SELECT username, display_name displayName, biography, language, updated_at updatedAt FROM narrator_profiles WHERE username=?",
                    (identity["username"],),
                ).fetchone()
                credit_rows = connection.execute(
                    """
                    SELECT c.audio_asset_id assetId, a.title, a.version_number versionNumber,
                           c.awarded_at awardedAt, c.reason
                    FROM narrator_credits c JOIN audio_assets a ON a.id=c.audio_asset_id
                    WHERE c.narrator_username=? ORDER BY c.awarded_at DESC LIMIT 100
                    """,
                    (identity["username"],),
                ).fetchall()
                published = connection.execute(
                    """
                    SELECT a.id, a.title, a.album, a.collection, a.narrator, a.genre, a.language,
                           a.episode_number, a.audience_age_range, a.mood, a.genres_json,
                           a.listening_contexts_json, a.content_warnings_json, a.moral_takeaway,
                           a.source_adaptation, a.keywords_json, a.updated_at, n.published_at,
                           a.metadata_review_status metadataReviewStatus,
                           a.source_path sourcePath, a.version_number versionNumber
                    FROM narrator_assets n JOIN audio_assets a ON a.id=n.audio_asset_id
                    WHERE n.narrator_username=? AND a.status='published'
                    ORDER BY n.published_at DESC LIMIT 100
                    """,
                    (identity["username"],),
                ).fetchall()
            return self.send_json(200, {
                "counts": counts,
                "credits": credits,
                "profile": dict(profile) if profile else None,
                "creditHistory": [dict(row) for row in credit_rows],
                "published": [add_metadata(dict(row), row) for row in published],
            })
        if path == "/api/catalog":
            identity = self.require_permission("catalog.read")
            if not identity: return
            with db() as connection:
                rows = connection.execute(
                    """
                    SELECT a.id, a.title, a.album, a.collection, a.narrator,
                           a.genre, a.duration_seconds duration, a.source_path sourcePath,
                           a.episode_number, a.language, a.audience_age_range, a.mood,
                           a.genres_json, a.listening_contexts_json, a.content_warnings_json,
                           a.moral_takeaway, a.source_adaptation, a.keywords_json,
                           a.metadata_review_status metadataReviewStatus,
                           t.short_text shortText, t.long_text longText
                    FROM audio_assets a
                    LEFT JOIN teaser_drafts t ON t.id=(
                        SELECT id FROM teaser_drafts WHERE audio_asset_id=a.id AND status='approved'
                        ORDER BY id DESC LIMIT 1
                    )
                    WHERE a.status='published'
                      AND t.id IS NOT NULL
                    ORDER BY a.updated_at DESC LIMIT 500
                    """
                ).fetchall()
            return self.send_json(200, {"items": [add_metadata(dict(row), row) for row in rows]})
        if path == "/api/narrator/assets":
            identity = self.require_permission("narrator.pipeline")
            if not identity: return
            with db() as connection:
                rows = connection.execute(
                    """
                    SELECT a.id, a.title, a.album, a.status, a.source_path sourcePath,
                           a.collection, a.narrator, a.genre, a.language, a.episode_number,
                           a.audience_age_range, a.mood, a.genres_json, a.listening_contexts_json,
                           a.content_warnings_json, a.moral_takeaway, a.source_adaptation, a.keywords_json,
                           a.parent_asset_id parentAssetId, a.version_number versionNumber,
                           a.duration_seconds duration, a.updated_at updatedAt,
                           n.submitted_at submittedAt, n.published_at publishedAt,
                           a.metadata_review_status metadataReviewStatus,
                           n.review_required reviewRequired
                    FROM narrator_assets n JOIN audio_assets a ON a.id=n.audio_asset_id
                    WHERE n.narrator_username=?
                    ORDER BY a.updated_at DESC
                    """,
                    (identity["username"],),
                ).fetchall()
            return self.send_json(200, {"items": [add_metadata(dict(row), row) for row in rows]})
        if path == "/api/session":
            identity = self.identity()
            return self.send_json(200, {"authenticated": bool(identity), **(identity or {})})
        if path == "/api/dashboard":
            if not self.require_permission("transcript.review"): return
            with db() as connection:
                ensure_auth_schema(connection)
                counts = {
                    row["status"]: row["count"]
                    for row in connection.execute("SELECT status, COUNT(*) count FROM transcripts GROUP BY status")
                }
                teaser_counts = {
                    row["status"]: row["count"]
                    for row in connection.execute("SELECT status, COUNT(*) count FROM teaser_drafts GROUP BY status")
                }
                asset_count = connection.execute("SELECT COUNT(*) FROM audio_assets").fetchone()[0]
            return self.send_json(200, {"assets": asset_count, "transcripts": counts, "teasers": teaser_counts})
        if path == "/api/queue":
            query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            queue = query.get("queue", ["transcripts"])[0]
            permission = {
                "teasers": "teaser.review",
                "narrator-submissions": "content.publish",
            }.get(queue, "transcript.review")
            if not self.require_permission(permission): return
            with db() as connection:
                ensure_auth_schema(connection)
                if queue == "teasers":
                    rows = connection.execute(
                        """
                        SELECT t.id, t.audio_asset_id assetId, t.status, t.language,
                               t.short_text shortText, t.long_text longText,
                               a.title, a.album, tr.text transcript
                        FROM teaser_drafts t JOIN audio_assets a ON a.id=t.audio_asset_id
                        LEFT JOIN transcripts tr ON tr.id=t.transcript_id
                        ORDER BY t.id DESC LIMIT 100
                        """
                    ).fetchall()
                elif queue == "narrator-submissions":
                    rows = connection.execute(
                        """
                        SELECT a.id assetId, a.title, a.album, a.collection, a.genre, a.language,
                               a.episode_number, a.audience_age_range, a.mood, a.genres_json,
                               a.listening_contexts_json, a.content_warnings_json, a.moral_takeaway,
                               a.source_adaptation, a.keywords_json, a.status,
                               a.metadata_review_status metadataReviewStatus,
                               a.source_path sourcePath, a.updated_at updatedAt,
                               n.narrator_username narrator, n.submitted_at submittedAt,
                               a.parent_asset_id parentAssetId, a.version_number versionNumber,
                               a.source_path sourcePath,
                               n.review_required reviewRequired
                        FROM narrator_assets n JOIN audio_assets a ON a.id=n.audio_asset_id
                        WHERE a.status IN ('draft', 'needs-review', 'rejected')
                        ORDER BY a.updated_at DESC LIMIT 100
                        """
                    ).fetchall()
                else:
                    rows = connection.execute(
                        """
                        SELECT tr.id, tr.audio_asset_id assetId, tr.version, tr.status,
                               tr.language, tr.text, a.title, a.album,
                               a.source_path sourcePath, a.duration_seconds duration
                        FROM transcripts tr JOIN audio_assets a ON a.id=tr.audio_asset_id
                        ORDER BY tr.id DESC LIMIT 100
                        """
                    ).fetchall()
            items = [dict(row) for row in rows]
            if queue == "narrator-submissions":
                items = [add_metadata(item, row) for item, row in zip(items, rows)]
            return self.send_json(200, {"queue": queue, "items": items})
        if path == "/api/narrator/asset":
            identity = self.require_permission("content.publish")
            if not identity:
                return
            query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            asset_id = query.get("id", [None])[0]
            if not asset_id:
                return self.send_json(400, {"error": "Asset ID is required."})
            with db() as connection:
                asset = connection.execute(
                    """
                    SELECT a.id, a.title, a.album, a.collection, a.narrator, a.genre, a.language,
                           a.episode_number, a.audience_age_range, a.mood, a.genres_json,
                           a.listening_contexts_json, a.content_warnings_json, a.moral_takeaway,
                           a.source_adaptation, a.keywords_json,
                           a.source_path sourcePath, a.duration_seconds duration,
                           a.status, a.parent_asset_id parentAssetId,
                           a.version_number versionNumber, a.updated_at updatedAt,
                           a.metadata_review_status metadataReviewStatus,
                           n.narrator_username narratorUsername,
                           n.submitted_at submittedAt, n.published_at publishedAt,
                           n.review_required reviewRequired
                    FROM audio_assets a JOIN narrator_assets n ON n.audio_asset_id=a.id
                    WHERE a.id=?
                    """,
                    (asset_id,),
                ).fetchone()
                if not asset:
                    return self.send_json(404, {"error": "Narrator asset not found."})
                transcript = connection.execute(
                    """
                    SELECT id, version, status, language, text, reviewer, reviewed_at reviewedAt
                    FROM transcripts WHERE audio_asset_id=?
                    ORDER BY version DESC LIMIT 1
                    """,
                    (asset_id,),
                ).fetchone()
                teaser = connection.execute(
                    """
                    SELECT id, status, language, short_text shortText, long_text longText,
                           reviewer, created_at createdAt
                    FROM teaser_drafts WHERE audio_asset_id=?
                    ORDER BY id DESC LIMIT 1
                    """,
                    (asset_id,),
                ).fetchone()
                jobs = connection.execute(
                    """
                    SELECT job_type jobType, status, attempts, error, updated_at updatedAt
                    FROM processing_jobs WHERE audio_asset_id=?
                    ORDER BY id DESC
                    """,
                    (asset_id,),
                ).fetchall()
                rights = connection.execute(
                    """
                    SELECT status, rights_holder rightsHolder,
                           recording_rights recordingRights,
                           performance_rights performanceRights,
                           adaptation_rights adaptationRights,
                           artwork_rights artworkRights,
                           music_rights musicRights,
                           territory, allowed_uses allowedUses,
                           license_start licenseStart, license_end licenseEnd,
                           evidence_reference evidenceReference,
                           reviewer, review_notes reviewNotes, updated_at updatedAt
                    FROM asset_rights WHERE audio_asset_id=?
                    """,
                    (asset_id,),
                ).fetchone()
            return self.send_json(200, {
                "asset": add_metadata(dict(asset), asset),
                "transcript": dict(transcript) if transcript else None,
                "teaser": dict(teaser) if teaser else None,
                "jobs": [dict(job) for job in jobs],
                "rights": dict(rights) if rights else {
                    "status": "not-configured",
                    "message": "Configure the rights checklist before publishing.",
                },
            })
        if path.startswith("/audio/"):
            relative = urllib.parse.unquote(path.removeprefix("/audio/"))
            candidate = (ROOT / "audio" / relative).resolve()
            if ROOT.joinpath("audio") not in candidate.parents or not candidate.is_file():
                self.send_error(404)
                return
            return self.serve_file(candidate, "audio/mpeg")
        if path.startswith("/editor/"):
            asset = (EDITOR_DIR / path.removeprefix("/editor/")).resolve()
            if EDITOR_DIR in asset.parents and asset.is_file():
                return self.serve_file(asset, "text/css; charset=utf-8" if asset.suffix == ".css" else "text/javascript; charset=utf-8")
        if path.startswith("/narrator/"):
            asset = (NARRATOR_DIR / path.removeprefix("/narrator/")).resolve()
            if NARRATOR_DIR in asset.parents and asset.is_file():
                return self.serve_file(asset, "text/css; charset=utf-8" if asset.suffix == ".css" else "text/javascript; charset=utf-8")
        self.send_error(404)

    def do_POST(self) -> None:
        path = urllib.parse.urlparse(self.path).path
        if path == "/api/login":
            payload = self.read_json()
            with db() as connection:
                ensure_auth_schema(connection)
                row = connection.execute("SELECT username, password_hash, role FROM editor_users WHERE username=?", (payload.get("username"),)).fetchone()
            if not row or not verify_password(str(payload.get("password", "")), row["password_hash"]):
                self.send_json(401, {"error": "Invalid username or password."})
                return
            token = secrets.token_urlsafe(32)
            SESSIONS[token] = (row["username"], time.time() + 8 * 60 * 60)
            self.send_response(200)
            self.send_header("Set-Cookie", f"editor_session={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age=28800")
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json_bytes({
                "authenticated": True,
                "username": row["username"],
                "role": row["role"],
                "permissions": sorted(ROLE_PERMISSIONS.get(row["role"], set())),
            }))
            return
        if path == "/api/logout":
            cookie = http.cookies.SimpleCookie(self.headers.get("Cookie", ""))
            token = cookie.get("editor_session")
            if token:
                SESSIONS.pop(token.value, None)
            self.send_response(200)
            self.send_header("Set-Cookie", "editor_session=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0")
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json_bytes({"ok": True}))
            return
        if path == "/api/narrator/profile":
            identity = self.require_permission("narrator.pipeline")
            if not identity:
                return
            payload = self.read_json()
            display_name = str(payload.get("displayName") or "").strip()
            biography = str(payload.get("biography") or "").strip()
            if not display_name:
                return self.send_json(400, {"error": "Display name is required."})
            now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            with db() as connection:
                ensure_auth_schema(connection)
                connection.execute(
                    """
                    INSERT INTO narrator_profiles (username, display_name, biography, language, updated_at)
                    VALUES (?, ?, ?, 'te-IN', ?)
                    ON CONFLICT(username) DO UPDATE SET
                        display_name=excluded.display_name,
                        biography=excluded.biography,
                        updated_at=excluded.updated_at
                    """,
                    (identity["username"], display_name, biography, now),
                )
                connection.commit()
            return self.send_json(200, {"ok": True})
        if path == "/api/narrator/upload":
            identity = self.require_permission("narrator.upload")
            if not identity:
                return
            try:
                filename, content, fields = self.read_upload()
            except ValueError as error:
                self.send_json(400, {"error": str(error)})
                return
            if not content:
                self.send_json(400, {"error": "The uploaded audio file is empty."})
                return
            checksum = hashlib.sha256(content).hexdigest()
            asset_id = checksum[:16]
            parent_asset_id = fields.get("parentAssetId")
            metadata = upload_metadata(fields, filename)
            upload_dir = ROOT / "audio" / "narrator" / identity["username"]
            upload_dir.mkdir(parents=True, exist_ok=True)
            if parent_asset_id:
                with db() as connection:
                    ensure_auth_schema(connection)
                    parent = connection.execute(
                        """
                        SELECT a.id, a.status, n.narrator_username
                        FROM audio_assets a JOIN narrator_assets n ON n.audio_asset_id=a.id
                        WHERE a.id=? AND n.narrator_username=?
                        """,
                        (parent_asset_id, identity["username"]),
                    ).fetchone()
                if not parent or parent["status"] != "published":
                    self.send_json(409, {"error": "Only your published audio can receive a replacement upload."})
                    return
            destination = upload_dir / filename
            destination.write_bytes(content)
            now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            with db() as connection:
                ensure_auth_schema(connection)
                if parent_asset_id:
                    version = connection.execute(
                        """
                        SELECT COALESCE(MAX(version_number), 1) + 1
                        FROM audio_assets
                        WHERE id=? OR parent_asset_id=?
                        """,
                        (parent_asset_id, parent_asset_id),
                    ).fetchone()[0]
                    asset_status = "needs-review"
                else:
                    version = 1
                    asset_status = "draft"
                connection.execute(
                    """
                    INSERT INTO audio_assets (
                        id, source_path, checksum_sha256, title, album, collection, narrator,
                        genre, genres_json, episode_number, language, audience_age_range, mood,
                        listening_contexts_json, content_warnings_json, moral_takeaway,
                        source_adaptation, keywords_json, duration_seconds, status,
                        parent_asset_id, version_number, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        title=excluded.title, album=excluded.album, collection=excluded.collection,
                        genre=excluded.genre, genres_json=excluded.genres_json,
                        episode_number=excluded.episode_number, language=excluded.language,
                        audience_age_range=excluded.audience_age_range, mood=excluded.mood,
                        listening_contexts_json=excluded.listening_contexts_json,
                        content_warnings_json=excluded.content_warnings_json,
                        moral_takeaway=excluded.moral_takeaway, source_adaptation=excluded.source_adaptation,
                        keywords_json=excluded.keywords_json, updated_at=excluded.updated_at
                    """,
                    (asset_id, str(destination.relative_to(ROOT)), checksum, metadata["title"],
                     metadata["album"], metadata["collection"], identity["username"],
                     metadata["genres"][0] if metadata["genres"] else None,
                     json.dumps(metadata["genres"], ensure_ascii=False), metadata["episodeNumber"],
                     metadata["language"] or "te-IN", metadata["audienceAgeRange"], metadata["mood"],
                     json.dumps(metadata["listeningContexts"], ensure_ascii=False),
                     json.dumps(metadata["contentWarnings"], ensure_ascii=False), metadata["moralTakeaway"],
                     metadata["sourceAdaptation"], json.dumps(metadata["keywords"], ensure_ascii=False),
                     asset_status, parent_asset_id, version, now, now),
                )
                connection.execute(
                    """
                    INSERT OR IGNORE INTO narrator_assets
                        (audio_asset_id, narrator_username, submitted_at)
                    VALUES (?, ?, ?)
                    """,
                    (asset_id, identity["username"], now),
                )
                connection.execute(
                    """
                    INSERT INTO processing_jobs (audio_asset_id, job_type, status, created_at, updated_at)
                    VALUES (?, 'transcription', 'queued', ?, ?)
                    """,
                    (asset_id, now, now),
                )
                connection.commit()
            return self.send_json(201, {
                "assetId": asset_id,
                "parentAssetId": parent_asset_id,
                "versionNumber": version,
                "status": asset_status,
                "metadataReviewStatus": "not-reviewed",
                "filename": filename,
                "metadata": metadata,
            })
        if path in {"/api/narrator/metadata", "/api/narrator/metadata-review"}:
            identity = self.identity()
            if not identity:
                self.send_json(401, {"error": "Login required."})
                return
            if not identity:
                return
            payload = self.read_json()
            asset_id = str(payload.get("audioAssetId") or "")
            editor_update = "metadata.review" in identity["permissions"]
            if path == "/api/narrator/metadata-review" and not editor_update:
                self.send_json(403, {"error": "Metadata review permission required."})
                return
            if not editor_update and "narrator.upload" not in identity["permissions"]:
                self.send_json(403, {"error": "Metadata editing permission required."})
                return
            review_status = payload.get("metadataReviewStatus", payload.get("reviewState"))
            if review_status is None:
                review_status = "not-reviewed"
            if review_status not in {"not-reviewed", "needs-changes", "approved"}:
                return self.send_json(400, {"error": "Invalid metadata review state."})
            if not editor_update:
                review_status = "not-reviewed"
            with db() as connection:
                ensure_auth_schema(connection)
                asset = connection.execute(
                    "SELECT 1 FROM narrator_assets WHERE audio_asset_id=? AND (narrator_username=? OR ?=1)",
                    (asset_id, identity["username"], int(editor_update)),
                ).fetchone()
                if not asset:
                    return self.send_json(404, {"error": "Narrator audio asset not found."})
                metadata = upload_metadata({key: json.dumps(payload.get(key)) if isinstance(payload.get(key), list) else str(payload.get(key) or "") for key in (*METADATA_JSON_FIELDS, "title", "album", "collection", "episodeNumber", "language", "audienceAgeRange", "mood", "moralTakeaway", "sourceAdaptation")}, "narration")
                now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                connection.execute(
                    """UPDATE audio_assets SET title=?, album=?, collection=?, genre=?,
                       genres_json=?, episode_number=?, language=?, audience_age_range=?, mood=?,
                       listening_contexts_json=?, content_warnings_json=?, moral_takeaway=?,
                       source_adaptation=?, keywords_json=?, metadata_review_status=?, updated_at=? WHERE id=?""",
                    (metadata["title"], metadata["album"], metadata["collection"],
                     metadata["genres"][0] if metadata["genres"] else None,
                     json.dumps(metadata["genres"], ensure_ascii=False), metadata["episodeNumber"],
                     metadata["language"], metadata["audienceAgeRange"], metadata["mood"],
                     json.dumps(metadata["listeningContexts"], ensure_ascii=False),
                     json.dumps(metadata["contentWarnings"], ensure_ascii=False), metadata["moralTakeaway"],
                     metadata["sourceAdaptation"], json.dumps(metadata["keywords"], ensure_ascii=False),
                     review_status, now, asset_id),
                )
                connection.execute(
                    """INSERT INTO editorial_events
                       (entity_type, entity_id, action, reviewer, notes, created_at)
                       VALUES ('narrator_asset', ?, ?, ?, ?, ?)""",
                    (asset_id, f"metadata:{review_status}", identity["username"],
                     payload.get("notes") or "Narrator asset metadata updated.", now),
                )
                connection.commit()
            return self.send_json(200, {"ok": True, "assetId": asset_id, "metadata": metadata,
                                        "metadataReviewStatus": review_status})
        if path == "/api/narrator/process":
            identity = self.require_permission("content.publish")
            if not identity:
                return
            payload = self.read_json()
            asset_id = str(payload.get("assetId") or "")
            action = payload.get("action")
            if action not in {"transcription", "teaser"} or not asset_id:
                return self.send_json(400, {"error": "A valid assetId and processing action are required."})
            with db() as connection:
                ensure_auth_schema(connection)
                asset = connection.execute(
                    "SELECT id, title FROM audio_assets WHERE id=? AND EXISTS (SELECT 1 FROM narrator_assets WHERE audio_asset_id=audio_assets.id)",
                    (asset_id,),
                ).fetchone()
                if not asset:
                    return self.send_json(404, {"error": "Narrator submission not found."})
                if action == "transcription":
                    existing = connection.execute(
                        "SELECT status FROM transcripts WHERE audio_asset_id=? ORDER BY version DESC LIMIT 1",
                        (asset_id,),
                    ).fetchone()
                    if existing and existing["status"] in {"needs-review", "approved"}:
                        return self.send_json(409, {"error": "A transcript already exists for this audio."})
                    command = [
                        sys.executable, str(ROOT / "scripts" / "transcribe_sarvam.py"),
                        "--asset-id", asset_id, "--limit", "1",
                    ]
                else:
                    transcript = connection.execute(
                        "SELECT id, version FROM transcripts WHERE audio_asset_id=? AND status='approved' ORDER BY version DESC LIMIT 1",
                        (asset_id,),
                    ).fetchone()
                    if not transcript:
                        return self.send_json(409, {"error": "Approve the transcript before generating a teaser."})
                    transcript_path = ROOT / "catalog" / "transcripts" / f"{asset_id}.v{transcript['version']}.json"
                    if not transcript_path.is_file():
                        return self.send_json(409, {"error": "The approved transcript file is not available."})
                    teaser = connection.execute(
                        "SELECT status FROM teaser_drafts WHERE audio_asset_id=? ORDER BY id DESC LIMIT 1",
                        (asset_id,),
                    ).fetchone()
                    if teaser and teaser["status"] in {"needs-review", "approved"}:
                        return self.send_json(409, {"error": "A teaser draft already exists for this audio."})
                    command = [
                        sys.executable, str(ROOT / "scripts" / "ollama_teaser.py"),
                        "--asset-id", asset_id, "--title", asset["title"],
                        "--transcript", str(transcript_path),
                        "--output", str(ROOT / "catalog" / "teasers" / f"{asset_id}.json"),
                        "--require-approved-transcript",
                    ]
                now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                connection.execute(
                    "INSERT INTO processing_jobs (audio_asset_id, job_type, status, created_at, updated_at) VALUES (?, ?, 'running', ?, ?)",
                    (asset_id, action, now, now),
                )
                connection.commit()
            try:
                process = subprocess.Popen(command, cwd=str(ROOT), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except OSError as error:
                with db() as connection:
                    connection.execute(
                        "UPDATE processing_jobs SET status='failed', error=?, updated_at=? WHERE audio_asset_id=? AND job_type=? AND status='running'",
                        (str(error), now, asset_id, action),
                    )
                    connection.commit()
                return self.send_json(500, {"error": f"Could not start {action}: {error}"})
            def finish_processing() -> None:
                return_code = process.wait()
                with db() as connection:
                    if return_code != 0:
                        connection.execute(
                            "UPDATE processing_jobs SET status='failed', error=?, updated_at=? WHERE audio_asset_id=? AND job_type=? AND status='running'",
                            (f"{action} process exited with code {return_code}", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), asset_id, action),
                        )
                    elif action == "teaser":
                        connection.execute(
                            "UPDATE processing_jobs SET status='completed', updated_at=?, error=NULL WHERE audio_asset_id=? AND job_type=? AND status='running'",
                            (time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), asset_id, action),
                        )
                    connection.commit()
            threading.Thread(target=finish_processing, daemon=True).start()
            return self.send_json(202, {"assetId": asset_id, "action": action, "status": "running"})
        if path == "/api/narrator/rights":
            identity = self.require_permission("rights.manage")
            if not identity:
                return
            payload = self.read_json()
            asset_id = str(payload.get("audioAssetId") or "")
            required = ("recordingRights", "performanceRights", "adaptationRights", "artworkRights", "musicRights")
            if not asset_id:
                return self.send_json(400, {"error": "Audio asset ID is required."})
            status = payload.get("status", "needs-review")
            if status not in {"needs-review", "approved", "rejected"}:
                return self.send_json(400, {"error": "Invalid rights status."})
            with db() as connection:
                ensure_auth_schema(connection)
                if not connection.execute(
                    "SELECT 1 FROM narrator_assets WHERE audio_asset_id=?", (asset_id,)
                ).fetchone():
                    return self.send_json(404, {"error": "Narrator submission not found."})
                now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                connection.execute(
                    """
                    INSERT INTO asset_rights (
                        audio_asset_id, status, rights_holder,
                        recording_rights, performance_rights, adaptation_rights,
                        artwork_rights, music_rights, territory, allowed_uses,
                        license_start, license_end, evidence_reference,
                        reviewer, review_notes, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(audio_asset_id) DO UPDATE SET
                        status=excluded.status, rights_holder=excluded.rights_holder,
                        recording_rights=excluded.recording_rights,
                        performance_rights=excluded.performance_rights,
                        adaptation_rights=excluded.adaptation_rights,
                        artwork_rights=excluded.artwork_rights,
                        music_rights=excluded.music_rights,
                        territory=excluded.territory, allowed_uses=excluded.allowed_uses,
                        license_start=excluded.license_start, license_end=excluded.license_end,
                        evidence_reference=excluded.evidence_reference,
                        reviewer=excluded.reviewer, review_notes=excluded.review_notes,
                        updated_at=excluded.updated_at
                    """,
                    (
                        asset_id, status, payload.get("rightsHolder"),
                        int(bool(payload.get("recordingRights"))),
                        int(bool(payload.get("performanceRights"))),
                        int(bool(payload.get("adaptationRights"))),
                        int(bool(payload.get("artworkRights"))),
                        int(bool(payload.get("musicRights"))),
                        payload.get("territory"), payload.get("allowedUses"),
                        payload.get("licenseStart"), payload.get("licenseEnd"),
                        payload.get("evidenceReference"), identity["username"],
                        payload.get("reviewNotes"), now,
                    ),
                )
                connection.execute(
                    "INSERT INTO editorial_events (entity_type, entity_id, action, reviewer, notes, created_at) VALUES ('rights', ?, ?, ?, ?, ?)",
                    (asset_id, f"rights:{status}", identity["username"], payload.get("reviewNotes"), now),
                )
                connection.commit()
            return self.send_json(200, {"ok": True, "status": status})
        if path == "/api/narrator/content-edit":
            payload = self.read_json()
            content_type = payload.get("type")
            content_id = payload.get("id")
            text = str(payload.get("text") or "").strip()
            if content_type not in {"transcript", "teaser"} or not content_id:
                return self.send_json(400, {"error": "A valid content type and ID are required."})
            permission = "transcript.review" if content_type == "transcript" else "teaser.review"
            identity = self.require_permission(permission)
            if not identity:
                return
            if not text:
                return self.send_json(400, {"error": "Edited content cannot be empty."})
            with db() as connection:
                ensure_auth_schema(connection)
                if content_type == "transcript":
                    row = connection.execute(
                        "SELECT audio_asset_id FROM transcripts WHERE id=?", (content_id,)
                    ).fetchone()
                    if not row:
                        return self.send_json(404, {"error": "Transcript not found."})
                    connection.execute(
                        """
                        UPDATE transcripts
                        SET text=?, status='needs-review', reviewer=NULL,
                            review_notes='Edited content requires re-review.', reviewed_at=NULL
                        WHERE id=?
                        """,
                        (text, content_id),
                    )
                    connection.execute(
                        """
                        UPDATE teaser_drafts
                        SET status='needs-review',
                            review_notes='Transcript changed; teaser requires re-review.'
                        WHERE audio_asset_id=? AND status='approved'
                        """,
                        (row["audio_asset_id"],),
                    )
                    connection.execute(
                        """
                        UPDATE processing_jobs
                        SET status='needs-review', error=NULL, updated_at=?
                        WHERE audio_asset_id=? AND job_type='transcription'
                        """,
                        (now, row["audio_asset_id"]),
                    )
                    transcript_row = connection.execute(
                        "SELECT version FROM transcripts WHERE id=?", (content_id,)
                    ).fetchone()
                    transcript_file = ROOT / "catalog" / "transcripts" / f"{row['audio_asset_id']}.v{transcript_row['version']}.json"
                    if transcript_file.is_file():
                        transcript_payload = json.loads(transcript_file.read_text(encoding="utf-8"))
                        transcript_payload["transcript"] = text
                        transcript_payload["text"] = text
                        transcript_file.write_text(
                            json.dumps(transcript_payload, ensure_ascii=False, indent=2),
                            encoding="utf-8",
                        )
                else:
                    row = connection.execute(
                        "SELECT audio_asset_id FROM teaser_drafts WHERE id=?", (content_id,)
                    ).fetchone()
                    if not row:
                        return self.send_json(404, {"error": "Teaser draft not found."})
                    connection.execute(
                        """
                        UPDATE teaser_drafts
                        SET long_text=?, status='needs-review',
                            reviewer=NULL, review_notes='Edited content requires re-review.'
                        WHERE id=?
                        """,
                        (text, content_id),
                    )
                    connection.execute(
                        """
                        UPDATE processing_jobs
                        SET status='needs-review', error=NULL, updated_at=?
                        WHERE audio_asset_id=? AND job_type='teaser'
                        """,
                        (now, row["audio_asset_id"]),
                    )
                connection.execute(
                    """
                    INSERT INTO editorial_events
                        (entity_type, entity_id, action, reviewer, notes, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (content_type, str(content_id), f"{content_type}:edited",
                     identity["username"], "Content edited; re-review required.", now),
                )
                connection.commit()
            return self.send_json(200, {"ok": True, "status": "needs-review"})
        if path == "/api/narrator/delete":
            identity = self.require_permission("content.publish")
            if not identity:
                return
            payload = self.read_json()
            now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            asset_id = str(payload.get("audioAssetId") or "")
            notes = str(payload.get("notes") or "").strip()
            if not asset_id:
                return self.send_json(400, {"error": "Audio asset ID is required."})
            with db() as connection:
                ensure_auth_schema(connection)
                asset = connection.execute(
                    """
                    SELECT a.id, a.status, a.source_path
                    FROM audio_assets a JOIN narrator_assets n ON n.audio_asset_id=a.id
                    WHERE a.id=?
                    """,
                    (asset_id,),
                ).fetchone()
                if not asset:
                    return self.send_json(404, {"error": "Narrator submission not found."})
                if asset["status"] in {"published", "archived"}:
                    return self.send_json(409, {"error": "Published or archived audio cannot be deleted."})
                connection.execute("DELETE FROM teaser_drafts WHERE audio_asset_id=?", (asset_id,))
                connection.execute("DELETE FROM transcripts WHERE audio_asset_id=?", (asset_id,))
                connection.execute("DELETE FROM processing_jobs WHERE audio_asset_id=?", (asset_id,))
                connection.execute("DELETE FROM narrator_assets WHERE audio_asset_id=?", (asset_id,))
                connection.execute("DELETE FROM audio_assets WHERE id=?", (asset_id,))
                connection.execute(
                    """
                    INSERT INTO editorial_events
                        (entity_type, entity_id, action, reviewer, notes, created_at)
                    VALUES ('narrator_asset', ?, 'content:deleted', ?, ?, ?)
                    """,
                    (asset_id, identity["username"], notes or None, now),
                )
                connection.commit()
            source = (ROOT / asset["source_path"]).resolve()
            audio_root = (ROOT / "audio").resolve()
            if audio_root in source.parents and source.is_file():
                source.unlink()
            return self.send_json(200, {"ok": True, "assetId": asset_id})
        identity = self.identity()
        if not identity:
            self.send_json(401, {"error": "Login required."})
            return
        username = identity["username"]
        payload = self.read_json()
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        with db() as connection:
            ensure_auth_schema(connection)
            if path == "/api/content/publish":
                if "content.publish" not in identity["permissions"]:
                    self.send_json(403, {"error": "Content publishing permission required."})
                    return
                asset_id = payload.get("audioAssetId")
                owned_asset = connection.execute(
                    """SELECT a.id, a.title, a.language, a.audience_age_range,
                              a.genres_json, a.moral_takeaway, a.source_adaptation
                              , a.metadata_review_status
                       FROM audio_assets a JOIN narrator_assets n ON n.audio_asset_id=a.id
                       WHERE a.id=?""",
                    (asset_id,),
                ).fetchone()
                if not owned_asset:
                    self.send_json(404, {"error": "Narrator submission not found."})
                    return
                missing_metadata = missing_publication_metadata(owned_asset)
                if missing_metadata:
                    self.send_json(409, {
                        "error": "Required narrator metadata is missing.",
                        "missingMetadata": missing_metadata,
                    })
                    return
                if owned_asset["metadata_review_status"] != "approved":
                    self.send_json(409, {
                        "error": "Narrator metadata must be approved before publishing.",
                        "metadataReviewStatus": owned_asset["metadata_review_status"],
                        "requiredMetadataReviewStatus": "approved",
                    })
                    return
                ready = connection.execute(
                    """
                    SELECT
                        EXISTS(SELECT 1 FROM transcripts WHERE audio_asset_id=? AND status='approved') transcript_ready,
                        EXISTS(SELECT 1 FROM teaser_drafts WHERE audio_asset_id=? AND status='approved') teaser_ready
                    """,
                    (asset_id, asset_id),
                ).fetchone()
                rights = connection.execute(
                    """
                    SELECT status, recording_rights, performance_rights, adaptation_rights,
                           artwork_rights, music_rights, license_end
                    FROM asset_rights WHERE audio_asset_id=?
                    """,
                    (asset_id,),
                ).fetchone()
                rights_ready = rights and rights["status"] == "approved" and all(
                    rights[key] for key in ("recording_rights", "performance_rights", "adaptation_rights", "artwork_rights", "music_rights")
                ) and (not rights["license_end"] or rights["license_end"] >= now[:10])
                if not ready["transcript_ready"] or not ready["teaser_ready"] or not rights_ready:
                    self.send_json(409, {"error": "Approved transcript, teaser, and current approved rights are required before publishing."})
                    return
                connection.execute(
                    "UPDATE audio_assets SET status='published', updated_at=? WHERE id=?",
                    (now, asset_id),
                )
                replacement = connection.execute(
                    "SELECT parent_asset_id FROM audio_assets WHERE id=?",
                    (asset_id,),
                ).fetchone()
                if replacement and replacement["parent_asset_id"]:
                    connection.execute(
                        "UPDATE audio_assets SET status='archived', updated_at=? WHERE id=? AND status='published'",
                        (now, replacement["parent_asset_id"]),
                    )
                connection.execute(
                    """
                    UPDATE narrator_assets SET published_at=?, review_required=0
                    WHERE audio_asset_id=?
                    """,
                    (now, asset_id),
                )
                owner = connection.execute(
                    "SELECT narrator_username FROM narrator_assets WHERE audio_asset_id=?",
                    (asset_id,),
                ).fetchone()
                if owner:
                    connection.execute(
                        """
                        INSERT OR IGNORE INTO narrator_credits
                            (narrator_username, audio_asset_id, awarded_at)
                        VALUES (?, ?, ?)
                        """,
                        (owner["narrator_username"], asset_id, now),
                    )
                entity = str(asset_id)
                action = "content:published"
            elif path == "/api/narrator/review":
                if "content.publish" not in identity["permissions"]:
                    self.send_json(403, {"error": "Content publishing permission required."})
                    return
                asset_id = payload.get("audioAssetId")
                decision = payload.get("decision")
                if decision not in {"rejected"}:
                    self.send_json(400, {"error": "Narrator submissions can be rejected here or published after readiness checks."})
                    return
                connection.execute(
                    """
                    UPDATE audio_assets SET status='rejected', updated_at=?
                    WHERE id=? AND EXISTS (
                        SELECT 1 FROM narrator_assets WHERE audio_asset_id=audio_assets.id
                    )
                    """,
                    (now, asset_id),
                )
                entity = str(asset_id)
                action = "content:rejected"
            elif path == "/api/narrator/submit-edit":
                if "narrator.upload" not in identity["permissions"]:
                    self.send_json(403, {"error": "Narrator upload permission required."})
                    return
                asset_id = payload.get("audioAssetId")
                owns_asset = connection.execute(
                    """
                    SELECT 1 FROM narrator_assets
                    WHERE audio_asset_id=? AND narrator_username=?
                    """,
                    (asset_id, username),
                ).fetchone()
                if not owns_asset:
                    self.send_json(404, {"error": "Narrator audio asset not found."})
                    return
                current = connection.execute(
                    "SELECT status FROM audio_assets WHERE id=?",
                    (asset_id,),
                ).fetchone()
                if not current or current["status"] != "published":
                    self.send_json(409, {"error": "Only published audio can receive an edit submission."})
                    return
                entity = str(asset_id)
                action = "content:edit-submitted"
            elif path == "/api/transcript/review":
                if "transcript.review" not in identity["permissions"]:
                    self.send_json(403, {"error": "Transcript review permission required."})
                    return
                connection.execute(
                    "UPDATE transcripts SET status=?, reviewer=?, review_notes=?, reviewed_at=? WHERE id=?",
                    (payload.get("decision"), username, payload.get("notes"), now, payload.get("id")),
                )
                connection.execute(
                    "UPDATE processing_jobs SET status=?, updated_at=?, error=NULL WHERE audio_asset_id=(SELECT audio_asset_id FROM transcripts WHERE id=?) AND job_type='transcription'",
                    (payload.get("decision"), now, payload.get("id")),
                )
                updated = connection.execute(
                    "SELECT id, audio_asset_id, status, review_notes FROM transcripts WHERE id=?",
                    (payload.get("id"),),
                ).fetchone()
                entity = str(payload.get("id"))
                action = f"transcript:{payload.get('decision')}"
            elif path == "/api/teaser/review":
                if "teaser.review" not in identity["permissions"]:
                    self.send_json(403, {"error": "Teaser review permission required."})
                    return
                connection.execute(
                    "UPDATE teaser_drafts SET status=?, reviewer=?, review_notes=? WHERE id=?",
                    (payload.get("decision"), username, payload.get("notes"), payload.get("id")),
                )
                connection.execute(
                    "UPDATE processing_jobs SET status=?, updated_at=?, error=NULL WHERE audio_asset_id=(SELECT audio_asset_id FROM teaser_drafts WHERE id=?) AND job_type='teaser'",
                    (payload.get("decision"), now, payload.get("id")),
                )
                updated = connection.execute(
                    "SELECT id, audio_asset_id, status, review_notes FROM teaser_drafts WHERE id=?",
                    (payload.get("id"),),
                ).fetchone()
                entity = str(payload.get("id"))
                action = f"teaser:{payload.get('decision')}"
            else:
                self.send_json(404, {"error": "Unknown editorial action."})
                return
            connection.execute(
                "INSERT INTO editorial_events (entity_type, entity_id, action, reviewer, notes, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (action.split(":")[0], entity, action, username, payload.get("notes"), now),
            )
            connection.commit()
        response = {"ok": True}
        if "updated" in locals() and updated:
            response["review"] = dict(updated)
        self.send_json(200, response)

    def serve_file(self, path: Path, content_type: str) -> None:
        body = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    with db() as connection:
        ensure_auth_schema(connection)
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 4173), Handler)
    print("KathaChepta: http://127.0.0.1:4173/")
    print("Editorial workspace: http://127.0.0.1:4173/editor/")
    server.serve_forever()
