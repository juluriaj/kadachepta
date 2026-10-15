"""Books (series) in the studio: the cover every chapter shows, where it came from, and taking a book down.

The catalog answers copyright claims reactively, so each step is quick: upload the printed book's cover with a
note on its source; swap it for KathaChepta's own cover (an illustration in the house style with the title set
in code) when the artwork is claimed; withdraw every chapter at once when the book itself is claimed.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from .. import jobs
from ..auth import Identity, require, utcnow
from ..db import get_db
from ..models import AudioAsset, EditorialEvent, Job, Series
from ..services import covers, pipeline
from ..services.assets import iso, series_cover_url

router = APIRouter(prefix="/api/studio/series", tags=["studio"])
EDITOR = require("content.publish")


def _series(db: Session, series_id: int) -> Series:
    series = db.get(Series, series_id)
    if series is None:
        raise HTTPException(status_code=404, detail="No such book.")
    return series


def _cover_jobs(db: Session) -> dict[int, Job]:
    active = db.scalars(select(Job).where(Job.job_type == "artwork", Job.status.in_(jobs.ACTIVE_STATUSES)))
    return {int(job.payload["seriesId"]): job for job in active if job.payload.get("seriesId")}


def _payload(db: Session, series: Series, counts: dict[str, int], cover_job: Job | None) -> dict[str, Any]:
    return {
        "id": series.id, "title": series.title, "language": series.language,
        "chapters": sum(counts.values()), "published": counts.get("published", 0),
        "withdrawn": counts.get("withdrawn", 0),
        "cover": {"url": series_cover_url(series), "kind": series.artwork_kind, "source": series.artwork_source,
                  "updatedAt": iso(series.artwork_updated_at), "pending": cover_job is not None,
                  "title": series.cover_title},
        "withdrawnAt": iso(series.withdrawn_at), "withdrawnReason": series.withdrawn_reason,
    }


def _counts(db: Session) -> dict[int, dict[str, int]]:
    counts: dict[int, dict[str, int]] = {}
    for series_id, status, n in db.execute(select(AudioAsset.series_id, AudioAsset.status, func.count())
                                           .where(AudioAsset.series_id.is_not(None), AudioAsset.status != "archived")
                                           .group_by(AudioAsset.series_id, AudioAsset.status)):
        counts.setdefault(series_id, {})[status] = n
    return counts


@router.get("")
def list_series(identity: Identity = Depends(EDITOR), db: Session = Depends(get_db)):
    counts, pending = _counts(db), _cover_jobs(db)
    items = [_payload(db, s, counts.get(s.id, {}), pending.get(s.id))
             for s in db.scalars(select(Series).order_by(Series.title)) if counts.get(s.id)]
    return {"items": items}


def _one(db: Session, series: Series) -> dict[str, Any]:
    return _payload(db, series, _counts(db).get(series.id, {}), _cover_jobs(db).get(series.id))


@router.get("/{series_id}")
def get_series(series_id: int, identity: Identity = Depends(EDITOR), db: Session = Depends(get_db)):
    series = _series(db, series_id)
    return {**_one(db, series), "suggestedCoverTitle": covers.suggested_title(db, series)}


@router.put("/{series_id}/cover")
async def upload_cover(series_id: int, request: Request, source: str = Query(min_length=3, max_length=500),
                       identity: Identity = Depends(EDITOR), db: Session = Depends(get_db)):
    """The printed book's cover (the request body is the image). ``source`` says where it came from."""
    data = await request.body()

    def store() -> dict[str, Any]:
        series = _series(db, series_id)
        try:
            covers.save_book_cover(db, series, data, source, identity.username)
        except covers.CoverError as error:
            raise HTTPException(status_code=422, detail=str(error)) from None
        db.commit()
        return _one(db, series)

    return await run_in_threadpool(store)


class SeriesEdit(BaseModel):
    coverSource: str | None = Field(default=None, max_length=500)
    coverTitle: str | None = Field(default=None, max_length=120)


@router.patch("/{series_id}")
def edit_series(series_id: int, payload: SeriesEdit, identity: Identity = Depends(EDITOR),
                db: Session = Depends(get_db)):
    series = _series(db, series_id)
    if payload.coverSource is not None:
        series.artwork_source = payload.coverSource.strip() or None
        covers.event(db, series, "series:cover-source", identity.username, series.artwork_source)
    if payload.coverTitle is not None:
        series.cover_title = " ".join(payload.coverTitle.split()) or None
    db.commit()
    return _one(db, series)


@router.post("/{series_id}/cover/generate", status_code=202)
def generate_cover(series_id: int, identity: Identity = Depends(EDITOR), db: Session = Depends(get_db)):
    """KathaChepta's own cover: the GPU worker paints it from the first chapter, then the title is set on it."""
    series = _series(db, series_id)
    if series.id in _cover_jobs(db):
        raise HTTPException(status_code=409, detail="A cover is already being made for this book.")
    chapters = covers.chapters(db, series.id)
    if not chapters:
        raise HTTPException(status_code=409, detail="This book has no chapters to draw from.")
    # The earliest chapter with an AI teaser says the most about the book (its characters and setting).
    source = next((chapter for chapter in chapters if pipeline.latest_draft(db, chapter.id)), chapters[0])
    job = jobs.enqueue(db, "artwork", asset_id=source.id, payload={"seriesId": series.id},
                       created_by=identity.username, priority=jobs.PRIORITY_INTERACTIVE)
    covers.event(db, series, "series:own-cover-requested", identity.username, f"job {job.id}")
    db.commit()
    return _one(db, series)


@router.delete("/{series_id}/cover")
def remove_cover(series_id: int, identity: Identity = Depends(EDITOR), db: Session = Depends(get_db)):
    """Chapters go back to their own artwork. The file is kept, so the change can be undone from the log."""
    series = _series(db, series_id)
    covers.event(db, series, "series:cover-removed", identity.username, series.artwork_key)
    series.artwork_key = series.artwork_kind = series.artwork_source = None
    series.artwork_updated_at = utcnow()
    db.commit()
    return _one(db, series)


class Withdrawal(BaseModel):
    reason: str = Field(min_length=3, max_length=1000)


@router.post("/{series_id}/withdraw")
def withdraw(series_id: int, payload: Withdrawal, identity: Identity = Depends(EDITOR),
             db: Session = Depends(get_db)):
    """Take the whole book down (a claim against the book itself): published chapters become "withdrawn"."""
    series = _series(db, series_id)
    reason = payload.reason.strip()
    for asset in covers.chapters(db, series.id):
        if asset.status == "published":
            asset.status = "withdrawn"
            db.add(EditorialEvent(entity_type="audio_asset", entity_id=asset.id, action="content:withdrawn",
                                  actor=identity.username, notes=reason))
    series.withdrawn_at, series.withdrawn_reason = utcnow(), reason
    covers.event(db, series, "series:withdrawn", identity.username, reason)
    db.commit()
    return _one(db, series)


@router.post("/{series_id}/restore")
def restore(series_id: int, identity: Identity = Depends(EDITOR), db: Session = Depends(get_db)):
    series = _series(db, series_id)
    for asset in covers.chapters(db, series.id):
        if asset.status == "withdrawn":
            asset.status = "published"
            db.add(EditorialEvent(entity_type="audio_asset", entity_id=asset.id, action="content:restored",
                                  actor=identity.username, notes=series.withdrawn_reason))
    covers.event(db, series, "series:restored", identity.username, series.withdrawn_reason)
    series.withdrawn_at = series.withdrawn_reason = None
    db.commit()
    return _one(db, series)
