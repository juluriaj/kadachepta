"""Admin operations: job monitoring, retries, and bulk processing."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import jobs
from ..auth import Identity, require, utcnow
from ..db import get_db
from ..models import AudioAsset, Job, Worker
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
