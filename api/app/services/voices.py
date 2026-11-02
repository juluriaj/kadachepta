"""Narrators' faces and words: photos and bios on their pages (P3-10), and thank-you notes from families (P3-12).

Photos: a narrator uploads one in the Narrate tab, and it waits for an editor (photo_pending_key) before families
see it (photo_key). Editors also give a bio and photo to narrators the catalog credits by name only
(credited_narrators). Every photo is cropped square and saved as a 512 px JPEG, so a large phone photo costs
little on a tile.

Notes: from grown-ups' profiles only, never children's (Epic S), and only to narrators who said yes to them. The
review checks apply: contact details and links are refused, a child's school or similar waits for an editor, and
everything else gets the local model's check (the review.moderate job, with a messageId) before the narrator sees
it. A narrator can reply, block a family, or report a note to the editors. Each family can send a few notes a day.
"""

from __future__ import annotations

import io
from collections.abc import Iterable
from datetime import datetime, timedelta
from typing import Any

from PIL import Image, ImageOps
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import jobs
from ..auth import utcnow
from ..models import (
    AudioAsset, CreditedNarrator, Household, NarratorBlock, NarratorMessage, NarratorProfile, Notification, Profile, User,
)
from ..storage import get_storage, media_url
from . import settings as app_settings
from .community import CHILD_DETAILS, PERSONAL
from .covers import CoverError, image_extension
from .notify import notify

PHOTO_SIZE = 512
MAX_PHOTO_BYTES = 10 * 1024 * 1024
NOTES_PER_DAY = 3  # per family, to all narrators together
MAX_NOTE_CHARS = 1000


class NoteRefused(ValueError):
    pass


# --- Photos and bios (P3-10) ---

def save_photo(data: bytes, folder: str) -> str:
    """Crop the image square, shrink it to 512 px and store it as a JPEG. Returns the storage key."""
    if len(data) > MAX_PHOTO_BYTES:
        raise CoverError("The photo is larger than 10 MB.")
    try:
        image_extension(data)
    except CoverError:
        raise CoverError("Upload a JPEG, PNG, or WebP photo.") from None
    image = ImageOps.exif_transpose(Image.open(io.BytesIO(data))).convert("RGB")  # phone photos come rotated
    image = ImageOps.fit(image, (PHOTO_SIZE, PHOTO_SIZE), Image.Resampling.LANCZOS)
    buffer = io.BytesIO()
    image.save(buffer, "JPEG", quality=85, optimize=True)
    key = f"narrators/{folder}/{int(utcnow().timestamp())}.jpg"
    get_storage().put_bytes(key, buffer.getvalue())
    return key


def photo_url(key: str | None, updated: datetime | None) -> str | None:
    return media_url(key, int(updated.timestamp()) if updated else None)


def name_folder(narrator_key: str) -> str:
    return "name-" + "".join(c if c.isalnum() else "-" for c in narrator_key[5:])[:60]


def photos(db: Session, keys: Iterable[str]) -> dict[str, str]:
    """{person_key: approved photo URL} for the narrators that have one."""
    keys = set(keys)
    ids = [int(key[3:]) for key in keys if key.startswith("id:")]
    names = [key for key in keys if key.startswith("name:")]
    found: dict[str, str] = {}
    if ids:
        for row in db.scalars(select(NarratorProfile).where(NarratorProfile.user_id.in_(ids),
                                                            NarratorProfile.photo_key.is_not(None))):
            found[f"id:{row.user_id}"] = photo_url(row.photo_key, row.photo_updated_at)
    if names:
        for row in db.scalars(select(CreditedNarrator).where(CreditedNarrator.narrator_key.in_(names),
                                                             CreditedNarrator.photo_key.is_not(None))):
            found[row.narrator_key] = photo_url(row.photo_key, row.photo_updated_at)
    return found


def with_photos(db: Session, people: list[dict[str, Any]], key_of) -> list[dict[str, Any]]:
    found = photos(db, [key_of(person) for person in people])
    for person in people:
        person["photoUrl"] = found.get(key_of(person))
    return people


def credited(db: Session, narrator_key: str) -> CreditedNarrator | None:
    return db.get(CreditedNarrator, narrator_key)


# --- Thank-you notes (P3-12) ---

def accepts_notes(db: Session, narrator: User | None) -> bool:
    if not narrator or narrator.role != "narrator" or narrator.disabled_at:
        return False
    profile = db.get(NarratorProfile, narrator.id)
    return bool(profile and profile.accepts_messages)


def blocked(db: Session, narrator_id: int, household_id: int) -> bool:
    return db.get(NarratorBlock, (narrator_id, household_id)) is not None


def notes_today(db: Session, household_id: int) -> int:
    return db.scalar(select(func.count()).select_from(NarratorMessage).where(
        NarratorMessage.household_id == household_id, NarratorMessage.created_at >= utcnow() - timedelta(days=1))) or 0


def send_note(db: Session, profile: Profile, narrator: User, text: str, asset: AudioAsset | None) -> NarratorMessage:
    """Check and store a note. Raises NoteRefused with a reason the family can act on."""
    if profile.kind != "adult":
        raise NoteRefused("Notes to narrators are for grown-ups' profiles.")
    if not accepts_notes(db, narrator) or blocked(db, narrator.id, profile.household_id):
        raise NoteRefused("This narrator isn't taking notes right now.")
    text = " ".join(text.split())[:MAX_NOTE_CHARS]
    if len(text) < 3:
        raise NoteRefused("Write a few words.")
    if PERSONAL.search(text):
        raise NoteRefused("Notes can't include phone numbers, emails, or links.")
    if notes_today(db, profile.household_id) >= NOTES_PER_DAY:
        raise NoteRefused(f"Your family can send {NOTES_PER_DAY} notes a day. Try again tomorrow.")
    note = NarratorMessage(narrator_user_id=narrator.id, household_id=profile.household_id, profile_id=profile.id,
                           audio_asset_id=asset.id if asset else None, text=text)
    db.add(note)
    db.flush()
    if match := CHILD_DETAILS.search(text):
        note.status = "held"
        note.moderation = {"verdict": "hold", "reasons": ["personal-info"], "by": "pattern",
                           "note": f"Looks like a child's school or address: “{match.group(0)[:40]}”"}
        return note
    # The moderation job needs a story to hang on: the one the note is about, or the narrator's latest.
    story = asset or db.scalars(select(AudioAsset).where(AudioAsset.narrator_user_id == narrator.id,
                                                         AudioAsset.status == "published")
                                .order_by(AudioAsset.published_at.desc().nulls_last())).first()
    if story is None:
        note.status = "held"
        note.moderation = {"verdict": "hold", "reasons": ["unsure"], "by": "pipeline", "note": "No story to check against"}
        return note
    jobs.enqueue(db, "review.moderate", asset_id=story.id, payload={"messageId": note.id},
                 created_by=f"profile:{profile.id}", priority=jobs.PRIORITY_INTERACTIVE)
    return note


def deliver(db: Session, note: NarratorMessage) -> None:
    note.status = "delivered"
    notify(db, note.narrator_user_id, "listener-note", "A family sent you a thank-you note",
           note.text[:200], note.audio_asset_id)


def apply_moderation(db: Session, note: NarratorMessage, result: dict[str, Any]) -> None:
    """Like reviews: the local model only ever lets a note through; anything it doubts waits for an editor."""
    verdict = result.get("verdict") if result.get("verdict") in ("allow", "hold", "block") else "hold"
    note.moderation = {"verdict": verdict, "reasons": [] if verdict == "allow" else result.get("reasons", []),
                       "note": result.get("note", ""), "by": f"ai:{result.get('model', 'unknown')}"}
    if verdict == "allow" and app_settings.get(db, "community.autoPublishReviews"):
        deliver(db, note)
    else:
        note.status = "held"


def reply(db: Session, note: NarratorMessage, text: str, narrator_name: str) -> None:
    text = " ".join(text.split())[:MAX_NOTE_CHARS]
    if PERSONAL.search(text):
        raise NoteRefused("Replies can't include phone numbers, emails, or links.")
    first = note.reply is None
    note.reply, note.reply_at = text or None, utcnow() if text else None
    if note.reply and first:
        owner = db.scalar(select(Household.owner_user_id).where(Household.id == note.household_id))
        db.add(Notification(user_id=owner, kind="narrator-reply", title=f"{narrator_name} replied to your note",
                            body=text[:200], audio_asset_id=note.audio_asset_id))


def note_payload(note: NarratorMessage, *, for_narrator: bool = False) -> dict[str, Any]:
    payload = {"id": note.id, "text": note.text, "storyId": note.audio_asset_id, "status": note.status,
               "reply": note.reply, "replyAt": note.reply_at.isoformat() if note.reply_at else None,
               "createdAt": note.created_at.isoformat()}
    if for_narrator:  # a first name only, like reviews
        payload.update(author=note.profile.name.split()[0] if note.profile else "", read=note.read_at is not None,
                       householdId=note.household_id)
    return payload
