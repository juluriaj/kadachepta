"""The conversation on each submission between editors and its narrator (P3-11).

Either side can write at any time, so a question no longer needs a resubmission. The notes an editor leaves when
asking for changes or not accepting a story appear in the thread too. The narrator gets an in-app notification for
each editor message; the studio queue shows which submissions have unread messages from their narrator.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from ..auth import utcnow
from ..models import AudioAsset, SubmissionMessage, User
from .notify import notify

MAX_CHARS = 4000


def post(db: Session, asset: AudioAsset, author: User, role: str, text: str, *,
         notify_narrator: bool = True) -> SubmissionMessage | None:
    text = text.strip()[:MAX_CHARS]
    if not text:
        return None
    message = SubmissionMessage(audio_asset_id=asset.id, author_user_id=author.id, author_role=role, text=text)
    db.add(message)
    if role == "editor" and notify_narrator:
        notify(db, asset.narrator_user_id, "editor-message", f"A message about “{asset.title}”", text[:300], asset.id)
    return message


def thread(db: Session, asset_id: str, viewer_role: str) -> list[dict[str, Any]]:
    """The whole conversation, oldest first; messages from the other side are marked read."""
    other = "editor" if viewer_role == "narrator" else "narrator"
    db.execute(update(SubmissionMessage).where(SubmissionMessage.audio_asset_id == asset_id,
                                               SubmissionMessage.author_role == other,
                                               SubmissionMessage.read_at.is_(None)).values(read_at=utcnow()))
    rows = db.execute(select(SubmissionMessage, User).outerjoin(User, User.id == SubmissionMessage.author_user_id)
                      .where(SubmissionMessage.audio_asset_id == asset_id).order_by(SubmissionMessage.id)).all()
    return [{"id": message.id, "role": message.author_role, "text": message.text, "createdAt": message.created_at.isoformat(),
             "read": message.read_at is not None, "mine": message.author_role == viewer_role,
             # Narrators see "KathaChepta" for editors, as in the submission history.
             "author": (user.display_name or user.handle) if user and (viewer_role == "editor" or message.author_role == "narrator")
             else "KathaChepta"}
            for message, user in rows]


def unread_from_narrators(db: Session, asset_ids: list[str]) -> dict[str, int]:
    if not asset_ids:
        return {}
    return dict(db.execute(select(SubmissionMessage.audio_asset_id, func.count())
                           .where(SubmissionMessage.audio_asset_id.in_(asset_ids),
                                  SubmissionMessage.author_role == "narrator", SubmissionMessage.read_at.is_(None))
                           .group_by(SubmissionMessage.audio_asset_id)).all())
