"""Admin operations: job monitoring, retries, bulk processing, and finding accounts to reset a forgotten password."""

from __future__ import annotations

import secrets
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session

from .. import jobs
from ..auth import Identity, audit, require, utcnow
from ..db import get_db
from ..models import AudioAsset, AuthSession, Job, User, Worker
from ..security import hash_password
from ..services.assets import iso

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.get("/jobs")
def job_overview(status: str | None = None, identity: Identity = Depends(require("jobs.manage")),
                 db: Session = Depends(get_db)):
    counts = [{"type": job_type, "status": state, "count": count} for job_type, state, count in
              db.execute(select(Job.job_type, Job.status, func.count()).group_by(Job.job_type, Job.status))]
    query = select(Job).order_by(Job.updated_at.desc()).limit(50)
    if status:
        query = query.where(Job.status == status)
    workers = db.scalars(select(Worker).order_by(Worker.name)).all()
    return {
        "counts": counts,
        "recent": [{"id": job.id, "type": job.job_type, "assetId": job.audio_asset_id, "status": job.status,
                    "attempts": job.attempts, "error": job.error, "leasedBy": job.leased_by,
                    "updatedAt": iso(job.updated_at)} for job in db.scalars(query)],
        "workers": [{"name": worker.name, "capabilities": worker.capabilities, "lastSeenAt": iso(worker.last_seen_at),
                     "online": bool(worker.last_seen_at and (utcnow() - worker.last_seen_at).total_seconds() < 120),
                     "info": worker.info, "disabled": bool(worker.disabled_at)} for worker in workers],
    }


@router.post("/jobs/{job_id}/retry")
def retry(job_id: int, identity: Identity = Depends(require("jobs.manage")), db: Session = Depends(get_db)):
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")
    if job.status not in {"dead", "failed", "cancelled"}:
        raise HTTPException(status_code=409, detail=f"Job is {job.status}; only failed jobs can be retried.")
    job.status, job.run_after, job.attempts, job.error = "queued", utcnow(), 0, None
    db.commit()
    return {"ok": True}


class Backfill(BaseModel):
    jobType: Literal["media.process"] = "media.process"
    onlyMissing: bool = True
    limit: int = 1000


@router.post("/backfill")
def backfill(payload: Backfill, identity: Identity = Depends(require("jobs.manage")), db: Session = Depends(get_db)):
    query = select(AudioAsset.id, AudioAsset.checksum_sha256).limit(payload.limit)
    if payload.onlyMissing:
        query = query.where(AudioAsset.media_status != "ready")
    created = 0
    for asset_id, checksum in db.execute(query):
        if jobs.active_job(db, asset_id, payload.jobType):
            continue
        jobs.enqueue(db, payload.jobType, asset_id=asset_id, created_by=identity.username,
                     idempotency_key=f"media:{asset_id}:{checksum}" if payload.onlyMissing else None,
                     priority=jobs.PRIORITY_BULK)
        created += 1
    db.commit()
    return {"queued": created}


# --- Accounts (forgotten passwords while email is off) ---

def _account(user: User) -> dict:
    return {"userId": user.id, "username": user.username, "email": user.email, "displayName": user.display_name,
            "phone": user.phone, "role": user.role, "createdAt": iso(user.created_at),
            "lastLoginAt": iso(user.last_login_at), "disabled": bool(user.disabled_at),
            "hasPassword": bool(user.password_hash)}


@router.get("/users")
def find_users(q: str = "", identity: Identity = Depends(require("users.manage")), db: Session = Depends(get_db)):
    """Accounts whose username, email, name or phone contain q (at least 2 characters), newest sign-in first."""
    text = q.strip().lower()
    if len(text) < 2:
        return {"items": []}
    like = "%" + text.replace("%", "") + "%"  # "_" still matches any one character: harmless here
    query = (select(User).where(User.disabled_at.is_(None), or_(
        func.lower(User.username).like(like), func.lower(User.email).like(like),
        func.lower(User.display_name).like(like), User.phone.like(like)))
        .order_by(User.last_login_at.desc().nulls_last(), User.id.desc()).limit(25))
    return {"items": [_account(user) for user in db.scalars(query)]}


@router.post("/users/{user_id}/password")
def reset_password(user_id: int, request: Request, identity: Identity = Depends(require("users.manage")),
                   db: Session = Depends(get_db)):
    """A new random password, shown once to the admin to pass on. The account is signed out everywhere; its owner
    signs in with the new password and can change it in Account."""
    user = db.get(User, user_id)
    if not user or user.disabled_at:
        raise HTTPException(status_code=404, detail="No such account.")
    if user.id == identity.user.id:
        raise HTTPException(status_code=409, detail="Change your own password in My details.")
    password = secrets.token_urlsafe(9)  # 12 characters
    user.password_hash = hash_password(password)
    db.execute(update(AuthSession).where(AuthSession.user_id == user.id, AuthSession.revoked_at.is_(None))
               .values(revoked_at=utcnow()))
    audit(db, "password.reset-by-admin", request, identity.user.id, account=user.id)
    db.commit()
    return {"password": password, "account": _account(user)}
