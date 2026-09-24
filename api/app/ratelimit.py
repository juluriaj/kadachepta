"""In-process sliding-window rate limiter.

Enough for a single VM. If the API ever runs on more than one machine this moves to PostgreSQL.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request

from .auth import client_ip

_hits: dict[str, deque[float]] = defaultdict(deque)
_lock = threading.Lock()


def check(bucket: str, limit: int, window_seconds: int) -> None:
    now = time.monotonic()
    with _lock:
        hits = _hits[bucket]
        while hits and hits[0] <= now - window_seconds:
            hits.popleft()
        if len(hits) >= limit:
            retry = int(window_seconds - (now - hits[0])) + 1
            raise HTTPException(
                status_code=429,
                detail=f"Too many attempts. Try again in {retry} seconds.",
                headers={"Retry-After": str(retry)},
            )
        hits.append(now)


def limit_ip(request: Request, name: str, limit: int, window_seconds: int) -> None:
    check(f"{name}:ip:{client_ip(request)}", limit, window_seconds)


def reset() -> None:
    with _lock:
        _hits.clear()
