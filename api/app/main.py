"""KathaChepta API application."""

from __future__ import annotations

import hashlib
import logging
import os
import sys
import time
import uuid
from pathlib import Path
from urllib.parse import urlparse

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from starlette.exceptions import HTTPException

from .auth import SESSION_COOKIE, Identity, optional_identity
from .config import get_settings
from .db import get_db, get_sessionmaker
from .models import Worker
from .routers import admin, auth, editorial, household, listener, media, narrator, studio, uploads, worker
from .security import STAFF_ROLES, token_hash

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("kathachepta")

_SOURCE_DIGEST = hashlib.sha1()
for _file in sorted(Path(__file__).parent.rglob("*.py")):
    _SOURCE_DIGEST.update(_file.read_bytes())
SERVER_INFO = {
    "pid": os.getpid(),
    "startedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    "build": os.getenv("KC_BUILD", _SOURCE_DIGEST.hexdigest()[:10]),
    "python": sys.version.split()[0],
    "processingActions": list(editorial.PROCESS_ACTIONS),
}

app = FastAPI(title="KathaChepta API", version="0.1.0", docs_url="/api/docs", openapi_url="/api/openapi.json")


@app.middleware("http")
async def request_context(request: Request, call_next):
    request_id = request.headers.get("x-request-id") or uuid.uuid4().hex[:16]
    # CSRF defence for cookie-authenticated writes: the browser's Origin must be this site.
    if request.method in {"POST", "PUT", "PATCH", "DELETE"} and SESSION_COOKIE in request.cookies \
            and not request.headers.get("authorization"):
        origin = request.headers.get("origin") or request.headers.get("referer")
        if origin and urlparse(origin).netloc != request.headers.get("host"):
            return JSONResponse(status_code=403, content={"error": "Cross-site request blocked.",
                                                          "detail": "Cross-site request blocked."})
    started = time.perf_counter()
    response = await call_next(request)
    response.headers["X-Request-Id"] = request_id
    response.headers["X-KathaChepta-Server"] = f"pid={SERVER_INFO['pid']}; build={SERVER_INFO['build']}"
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    quiet = request.url.path == "/api/worker/lease" and response.status_code == 204  # idle polling
    if request.url.path.startswith("/api/") and not quiet:
        log.info("%s %s %s %.0fms rid=%s", request.method, request.url.path, response.status_code,
                 (time.perf_counter() - started) * 1000, request_id)
    return response


@app.exception_handler(HTTPException)
async def http_error(request: Request, error: HTTPException):
    detail = error.detail
    body = dict(detail) if isinstance(detail, dict) else {"error": str(detail)}
    body.setdefault("detail", body.get("error"))
    if error.status_code >= 400 and request.url.path.startswith("/api/narrator/process"):
        body["server"] = SERVER_INFO
    return JSONResponse(status_code=error.status_code, content=body, headers=error.headers)


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, error: RequestValidationError):
    problems = [f"{'.'.join(str(p) for p in item['loc'][1:]) or 'body'}: {item['msg']}" for item in error.errors()]
    return JSONResponse(status_code=422, content={"error": "Invalid request: " + "; ".join(problems),
                                                  "problems": problems})


for module in (auth, listener, household, media, narrator, uploads, editorial, studio, worker, admin):
    app.include_router(module.router)
app.include_router(studio.me_router)


@app.get("/api/health")
def health(db: Session = Depends(get_db)):
    db.execute(text("select 1"))
    return {"ok": True, **SERVER_INFO, "environment": get_settings().environment}


# --- Web pages (the prototype UI, served until the Phase 1 app and Phase 2 studio replace it) ---

def _page(path: Path) -> FileResponse:
    return FileResponse(path, headers={"Cache-Control": "no-cache"})


@app.get("/", include_in_schema=False)
def home(identity: Identity | None = Depends(optional_identity)):
    # Everyone uses the app now: listeners and narrators land on Home, editors and admins on /studio.
    return _app_index()


def _app_index() -> FileResponse:
    settings = get_settings()
    app_index = settings.app_root / "index.html"
    return _page(app_index if app_index.is_file() else settings.web_root / "index.html")


@app.get("/editor", include_in_schema=False)
@app.get("/editor/", include_in_schema=False)
def editor_page(identity: Identity | None = Depends(optional_identity)):
    if not identity or identity.role not in STAFF_ROLES or not identity.permissions:
        return RedirectResponse("/", status_code=302)
    return _page(get_settings().web_root / "editor" / "index.html")


@app.get("/narrator", include_in_schema=False)
@app.get("/narrator/", include_in_schema=False)
def narrator_page(identity: Identity | None = Depends(optional_identity)):
    if not identity or identity.role != "narrator":
        return RedirectResponse("/", status_code=302)
    return _page(get_settings().web_root / "narrator" / "index.html")


STATIC_TYPES = {".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8",
                ".svg": "image/svg+xml", ".png": "image/png", ".jpg": "image/jpeg", ".ico": "image/x-icon",
                ".webmanifest": "application/manifest+json", ".json": "application/json", ".ttf": "font/ttf",
                ".woff2": "font/woff2", ".html": "text/html; charset=utf-8", ".map": "application/json"}


@app.get("/{path:path}", include_in_schema=False)
def static_file(path: str):
    if path.startswith(("api/", "media/")):
        return JSONResponse(status_code=404, content={"error": "Not found.", "detail": "Not found."})
    settings = get_settings()
    for root in (settings.app_root.resolve(), settings.web_root.resolve()):
        candidate = (root / path).resolve()
        if root in candidate.parents and candidate.is_file() and candidate.suffix in STATIC_TYPES:
            # Hashed bundles never change; everything else revalidates.
            cache = "public, max-age=31536000, immutable" if "/_expo/static/" in f"/{path}" else "no-cache"
            return FileResponse(candidate, media_type=STATIC_TYPES[candidate.suffix], headers={"Cache-Control": cache})
    if "." not in path.rsplit("/", 1)[-1] and not path.startswith(("editor", "narrator")):
        return _app_index()  # a client-side route of the listener app
    return JSONResponse(status_code=404, content={"error": "Not found.", "detail": "Not found."})


@app.on_event("startup")
def startup() -> None:
    settings = get_settings()
    for problem in settings.validate_for_runtime():
        log.error("Configuration problem: %s", problem)
    if settings.validate_for_runtime() and settings.is_production:
        raise RuntimeError("Refusing to start with an unsafe production configuration.")
    register_bootstrap_workers()
    log.info("KathaChepta API ready: pid %s build %s env %s", SERVER_INFO["pid"], SERVER_INFO["build"],
             settings.environment)


def register_bootstrap_workers() -> None:
    spec = get_settings().bootstrap_workers.strip()
    if not spec:
        return
    for entry in filter(None, (part.strip() for part in spec.split(";"))):
        name, token, capabilities = (entry.split(":", 2) + [""])[:3]
        if not name or len(token) < 24:
            log.error("Ignoring bootstrap worker %r: token must be at least 24 characters.", name)
            continue
        # Several Uvicorn processes run this at once; a unique-name race is harmless, so retry once.
        for _attempt in range(2):
            with get_sessionmaker()() as db:
                worker_row = db.scalars(select(Worker).where(Worker.name == name)).first() or Worker(name=name)
                worker_row.token_hash = token_hash(token)
                worker_row.capabilities = [c.strip() for c in capabilities.split(",") if c.strip()]
                db.add(worker_row)
                try:
                    db.commit()
                    break
                except IntegrityError:
                    db.rollback()

