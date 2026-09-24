"""Signed media delivery with HTTP Range support (seeking on iOS/Safari, resumable downloads)."""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import Response, StreamingResponse

from ..auth import utcnow
from ..config import get_settings
from ..security import verify_media
from ..storage import StorageError, content_type, get_storage

router = APIRouter(tags=["media"])

_RANGE = re.compile(r"bytes=(\d*)-(\d*)$")


def _file_chunks(path: Path, start: int, length: int, chunk: int = 256 * 1024) -> Iterator[bytes]:
    with path.open("rb") as handle:
        handle.seek(start)
        remaining = length
        while remaining > 0:
            data = handle.read(min(chunk, remaining))
            if not data:
                break
            remaining -= len(data)
            yield data


@router.api_route("/media/{key:path}", methods=["GET", "HEAD"], include_in_schema=False)
def media(key: str, request: Request, e: int = Query(...), s: str = Query(...)):
    if not verify_media(key, e, s, get_settings().secret_key):
        raise HTTPException(status_code=403, detail="This media link has expired. Refresh the page.")
    try:
        path = get_storage().path(key)
    except StorageError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Media not found.")
    size = path.stat().st_size
    headers = {"Accept-Ranges": "bytes", "Cache-Control": f"private, max-age={max(e - int(utcnow().timestamp()), 0)}"}
    mime = content_type(key)
    range_header = request.headers.get("range")
    if range_header:
        match = _RANGE.match(range_header.strip())
        if not match or (not match.group(1) and not match.group(2)):
            return Response(status_code=416, headers={"Content-Range": f"bytes */{size}"})
        if match.group(1):
            start = int(match.group(1))
            end = min(int(match.group(2)) if match.group(2) else size - 1, size - 1)
        else:  # suffix range: last N bytes
            start, end = max(size - int(match.group(2)), 0), size - 1
        if start >= size or start > end:
            return Response(status_code=416, headers={"Content-Range": f"bytes */{size}"})
        length = end - start + 1
        headers.update({"Content-Range": f"bytes {start}-{end}/{size}", "Content-Length": str(length)})
        body = None if request.method == "HEAD" else _file_chunks(path, start, length)
        return StreamingResponse(body or iter(()), status_code=206, media_type=mime, headers=headers)
    headers["Content-Length"] = str(size)
    body = None if request.method == "HEAD" else _file_chunks(path, 0, size)
    return StreamingResponse(body or iter(()), media_type=mime, headers=headers)
