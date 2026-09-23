"""PostgreSQL-backed job queue with leases, retries, and dead-lettering."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from sqlalchemy import and_, or_, select, update
from sqlalchemy.orm import Session

from .auth import utcnow
from .models import Job

# Which worker capability each job type needs.
JOB_CAPABILITIES = {
    "media.process": "media",
    "transcription": "stt",
    "teaser": "llm",
    "artwork": "image",
}
# Legacy UI vocabulary for job states.
LEGACY_STATUS = {
    "queued": "queued", "leased": "running", "succeeded": "completed",
    "failed": "queued", "dead": "failed", "cancelled": "failed",
}
ACTIVE_STATUSES = ("queued", "leased", "failed")
PRIORITY_INTERACTIVE, PRIORITY_DEFAULT, PRIORITY_BULK = 10, 50, 100


def enqueue(db: Session, job_type: str, *, asset_id: str | None = None, payload: dict[str, Any] | None = None,
            created_by: str | None = None, idempotency_key: str | None = None, max_attempts: int = 3,
            priority: int = PRIORITY_DEFAULT) -> Job:
    if job_type not in JOB_CAPABILITIES:
        raise ValueError(f"Unknown job type {job_type!r}")
    if idempotency_key:
        existing = db.scalars(select(Job).where(Job.idempotency_key == idempotency_key)).first()
        if existing:
            return existing
    job = Job(job_type=job_type, audio_asset_id=asset_id, payload=payload or {}, created_by=created_by,
              idempotency_key=idempotency_key, max_attempts=max_attempts, priority=priority)
    db.add(job)
    db.flush()
    return job


def active_job(db: Session, asset_id: str, job_type: str) -> Job | None:
    return db.scalars(select(Job).where(
        Job.audio_asset_id == asset_id, Job.job_type == job_type, Job.status.in_(ACTIVE_STATUSES),
    ).order_by(Job.id.desc())).first()


def lease(db: Session, worker_name: str, capabilities: list[str], lease_seconds: int) -> Job | None:
    types = [job_type for job_type, capability in JOB_CAPABILITIES.items() if capability in capabilities]
    if not types:
        return None
    now = utcnow()
    candidate = db.scalars(
        select(Job)
        .where(
            Job.job_type.in_(types),
            or_(
                and_(Job.status.in_(("queued", "failed")), Job.run_after <= now),
                and_(Job.status == "leased", Job.lease_until < now),  # expired lease: worker died
            ),
        )
        .order_by(Job.priority, Job.run_after, Job.id)
        .limit(1)
        .with_for_update(skip_locked=True)
    ).first()
    if not candidate:
        return None
    candidate.status = "leased"
    candidate.leased_by = worker_name
    candidate.lease_until = now + timedelta(seconds=lease_seconds)
    candidate.attempts += 1
    db.commit()
    return candidate


def heartbeat(db: Session, job: Job, lease_seconds: int) -> None:
    job.lease_until = utcnow() + timedelta(seconds=lease_seconds)
    db.commit()


def complete(db: Session, job: Job, result: dict[str, Any], log_tail: str | None = None) -> None:
    job.status = "succeeded"
    job.result = result
    job.error = None
    job.lease_until = None
    job.log_tail = log_tail
    db.flush()


def fail(db: Session, job: Job, error: str, *, retryable: bool = True, log_tail: str | None = None) -> None:
    job.error = error[:4000]
    job.log_tail = log_tail
    job.lease_until = None
    if retryable and job.attempts < job.max_attempts:
        job.status = "failed"
        job.run_after = utcnow() + timedelta(seconds=30 * 2 ** job.attempts)
    else:
        job.status = "dead"
    db.flush()


def cancel_active(db: Session, asset_id: str) -> None:
    db.execute(update(Job).where(Job.audio_asset_id == asset_id, Job.status.in_(("queued", "failed")))
               .values(status="cancelled", error="Asset removed."))
