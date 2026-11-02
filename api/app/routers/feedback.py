"""Feedback from anyone signed in ("Send feedback"), and the studio inbox where editors read and close it.

Email is off for the pilot, so the inbox shows how to reach each sender (phone or email from their account,
and how they like to be contacted) for replying outside the app.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import ratelimit
from ..auth import Identity, audit, require, require_identity, utcnow
from ..db import get_db
from ..models import Feedback, User
from ..services.assets import iso

router = APIRouter(tags=["feedback"])
INBOX = require("feedback.manage")


class FeedbackIn(BaseModel):
    message: str = Field(max_length=4000)
    page: str | None = Field(default=None, max_length=300)
    platform: Literal["web", "android", "ios"] | None = None


@router.post("/api/feedback", status_code=201)
def send_feedback(payload: FeedbackIn, request: Request, identity: Identity = Depends(require_identity),
                  db: Session = Depends(get_db)):
    message = payload.message.strip()
    if len(message) < 3:
        raise HTTPException(status_code=422, detail="Write a few words about what happened or what you'd like.")
    ratelimit.check(f"feedback:{identity.user.id}", 10, 60 * 60)
    row = Feedback(user_id=identity.user.id, message=message, page=payload.page, platform=payload.platform)
    db.add(row)
    db.commit()
    return {"ok": True, "id": row.id}


@router.get("/api/studio/feedback")
def inbox(status: Literal["new", "done", "all"] = "new", identity: Identity = Depends(INBOX),
          db: Session = Depends(get_db)):
    query = select(Feedback, User).outerjoin(User, User.id == Feedback.user_id).order_by(Feedback.id.desc()).limit(200)
    if status != "all":
        query = query.where(Feedback.status == status)
    counts = dict(db.execute(select(Feedback.status, func.count()).group_by(Feedback.status)).all())
    items = []
    for row, user in db.execute(query):
        preferences = (user.contact_preferences or {}) if user else {}
        items.append({
            "id": row.id, "message": row.message, "page": row.page, "platform": row.platform, "status": row.status,
            "createdAt": iso(row.created_at), "resolvedAt": iso(row.resolved_at),
            "from": None if not user else {
                "userId": user.id, "name": user.display_name or user.handle, "username": user.username,
                "role": user.role, "email": user.email, "phone": user.phone,
                "contactChannel": preferences.get("channel") or ("email" if user.email else None),
            },
        })
    return {"items": items, "counts": {"new": counts.get("new", 0), "done": counts.get("done", 0)}}


class FeedbackState(BaseModel):
    done: bool


@router.post("/api/studio/feedback/{feedback_id}")
def set_state(feedback_id: int, payload: FeedbackState, request: Request, identity: Identity = Depends(INBOX),
              db: Session = Depends(get_db)):
    row = db.get(Feedback, feedback_id)
    if not row:
        raise HTTPException(status_code=404, detail="That feedback is gone.")
    row.status = "done" if payload.done else "new"
    row.resolved_at, row.resolved_by = (utcnow(), identity.user.id) if payload.done else (None, None)
    audit(db, "feedback.done" if payload.done else "feedback.reopened", request, identity.user.id, feedback=row.id)
    db.commit()
    return {"ok": True, "status": row.status}
