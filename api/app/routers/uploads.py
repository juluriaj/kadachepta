"""Resumable uploads (P2-03).

    POST /api/uploads                 {filename, size, purpose}   → {id, chunkSize, receivedBytes}
    PUT  /api/uploads/{id}?offset=N   raw bytes                   → {receivedBytes, complete}
    GET  /api/uploads/{id}                                        → {receivedBytes, complete}

A client that loses its connection asks for ``receivedBytes`` and continues from there. Sending a chunk
again is harmless. Completed uploads are turned into submissions by the narrator API.
"""

from __future__ import annotations

import secrets
import tempfile
from datetime import timedelta
from pathlib import PurePosixPath
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from ..auth import Identity, require_identity, utcnow
from ..config import get_settings
from ..db import get_db
from ..models import Upload
from ..storage import get_storage
from .narrator import AUDIO_EXTENSIONS, safe_filename

router = APIRouter(prefix="/api/uploads", tags=["uploads"])

CHUNK_SIZE = 4 * 1024 * 1024
EVIDENCE_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png", ".txt", ".doc", ".docx"}
EVIDENCE_LIMIT = 20 * 1024 * 1024
SAMPLE_LIMIT = 30 * 1024 * 1024


class NewUpload(BaseModel):
    filename: str = Field(min_length=1, max_length=200)
    size: int = Field(gt=0)
    purpose: Literal["audio", "evidence", "sample"] = "audio"


def _payload(upload: Upload) -> dict:
    return {"id": upload.id, "filename": upload.filename, "purpose": upload.purpose, "size": upload.total_bytes,
            "receivedBytes": upload.received_bytes, "complete": upload.status != "open", "chunkSize": CHUNK_SIZE}


def own_upload(db: Session, identity: Identity, upload_id: str, *, lock: bool = False) -> Upload:
    query = select(Upload).where(Upload.id == upload_id, Upload.user_id == identity.user.id)
    upload = db.scalars(query.with_for_update() if lock else query).first()
    if not upload or upload.expires_at < utcnow():
        raise HTTPException(status_code=404, detail="Upload not found or expired; start the upload again.")
    return upload


@router.post("", status_code=201)
def create_upload(payload: NewUpload, identity: Identity = Depends(require_identity), db: Session = Depends(get_db)):
    filename = safe_filename(payload.filename)
    suffix = PurePosixPath(filename).suffix.lower()
    if payload.purpose == "audio":
        if "narrator.upload" not in identity.permissions:
            raise HTTPException(status_code=403, detail="Narrator permission required.")
        allowed, limit = AUDIO_EXTENSIONS, get_settings().max_upload_bytes
    elif payload.purpose == "sample":  # applicants record a sample before they are narrators
        allowed, limit = AUDIO_EXTENSIONS, SAMPLE_LIMIT
    else:
        allowed, limit = EVIDENCE_EXTENSIONS, EVIDENCE_LIMIT
    if suffix not in allowed:
        raise HTTPException(status_code=400, detail=f"Unsupported file type. Use one of: {', '.join(sorted(allowed))}.")
    if payload.size > limit:
        raise HTTPException(status_code=413, detail=f"Files of this kind are limited to {limit // (1024 * 1024)} MB.")
    open_count = db.scalar(select(func.count()).select_from(Upload).where(
        Upload.user_id == identity.user.id, Upload.status == "open", Upload.expires_at > utcnow()))
    if open_count >= 20:
        raise HTTPException(status_code=429, detail="Too many unfinished uploads. Finish or wait for older ones.")
    upload = Upload(id=secrets.token_hex(16), user_id=identity.user.id, filename=filename, purpose=payload.purpose,
                    total_bytes=payload.size, expires_at=utcnow() + timedelta(days=2))
    db.add(upload)
    db.commit()
    return _payload(upload)


@router.get("/{upload_id}")
def upload_status(upload_id: str, identity: Identity = Depends(require_identity), db: Session = Depends(get_db)):
    return _payload(own_upload(db, identity, upload_id))


@router.put("/{upload_id}")
async def upload_chunk(upload_id: str, offset: int, request: Request, identity: Identity = Depends(require_identity),
                       db: Session = Depends(get_db)):
    if offset < 0:
        raise HTTPException(status_code=400, detail="offset must be zero or more.")
    with tempfile.SpooledTemporaryFile(max_size=CHUNK_SIZE + 1024) as buffer:
        size = 0
        async for chunk in request.stream():
            size += len(chunk)
            if size > CHUNK_SIZE * 2:
                raise HTTPException(status_code=413, detail=f"Send chunks of at most {CHUNK_SIZE} bytes.")
            buffer.write(chunk)
        buffer.seek(0)
        return await run_in_threadpool(_write_chunk, db, identity, upload_id, offset, size, buffer)


def _write_chunk(db: Session, identity: Identity, upload_id: str, offset: int, size: int, buffer) -> dict:
    upload = own_upload(db, identity, upload_id, lock=True)
    if upload.status != "open":
        return _payload(upload)
    if offset > upload.received_bytes:
        raise HTTPException(status_code=409, detail={"error": "Chunk is ahead of what the server has.",
                                                     "receivedBytes": upload.received_bytes})
    if offset + size <= upload.received_bytes:
        return _payload(upload)  # a repeated chunk we already have
    if offset + size > upload.total_bytes:
        raise HTTPException(status_code=400, detail="Chunk goes past the declared file size.")
    upload.received_bytes = get_storage().write_at(upload.key, offset, buffer)
    if upload.received_bytes >= upload.total_bytes:
        upload.status = "complete"
    db.commit()
    return _payload(upload)
