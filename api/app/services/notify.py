"""In-app notifications, mirrored to email for the moments narrators care about."""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from .. import mailer
from ..config import get_settings
from ..models import Notification, User

log = logging.getLogger("kathachepta.notify")
EMAIL_KINDS = {"published", "changes-requested", "needs-fix", "rejected"}


def notify(db: Session, user_id: int | None, kind: str, title: str, body: str | None = None,
           asset_id: str | None = None) -> None:
    if not user_id:
        return
    db.add(Notification(user_id=user_id, kind=kind, title=title, body=body, audio_asset_id=asset_id))
    user = db.get(User, user_id)
    if kind in EMAIL_KINDS and user and user.email:
        link = f"{get_settings().public_base_url}/narrate" + (f"/submission/{asset_id}" if asset_id else "")
        try:
            mailer.send_email(user.email, f"KathaChepta: {title}", f"{body or title}\n\nOpen your studio: {link}\n")
        except OSError:
            log.warning("Notification email to user %s failed; the in-app notification was still saved.", user_id)
