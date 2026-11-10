"""Continue with Google (web): OpenID Connect sign-in with the authorization-code flow and PKCE.

The browser goes to Google and comes back to /api/auth/google/callback, which signs it in with the usual session
cookie. A Google account belongs to one KathaChepta account. The first time, it joins the account that already has
its email address (Google has verified it), so people from the old website keep their account even if they forgot
their password; otherwise a new listener account is made. Team accounts still need their authenticator code.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Any
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import ratelimit
from ..auth import DEVICE_COOKIE, audit, utcnow
from ..config import get_settings
from ..db import get_db
from ..models import User, UserIdentity
from ..security import new_token
from .auth import remembered, session_response

router = APIRouter(prefix="/api/auth/google", tags=["auth"])

AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
ISSUERS = {"accounts.google.com", "https://accounts.google.com"}
# The round trip's secrets (state, nonce, PKCE verifier), signed, for ten minutes, sent only to these addresses.
STATE_COOKIE = "kc_google"
STATE_PATH = "/api/auth/google"
STATE_SECONDS = 600


class GoogleError(Exception):
    """Why sign-in stopped, as a short code the sign-in screen explains (cancelled, expired, failed, ...)."""


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _mac(body: str) -> str:
    return _b64(hmac.new(get_settings().secret_key.encode(), body.encode(), hashlib.sha256).digest())


def _sign(payload: dict[str, Any]) -> str:
    body = _b64(json.dumps(payload, separators=(",", ":")).encode())
    return f"{body}.{_mac(body)}"


def _unsign(value: str | None) -> dict[str, Any] | None:
    body, _, mac = (value or "").rpartition(".")
    if not body or not hmac.compare_digest(mac, _mac(body)):
        return None
    try:
        payload = json.loads(_unb64(body))
    except ValueError:
        return None
    return payload if isinstance(payload, dict) and payload.get("exp", 0) > time.time() else None


def _redirect_uri() -> str:
    return f"{get_settings().public_base_url.rstrip('/')}/api/auth/google/callback"


def exchange_code(code: str, verifier: str) -> dict[str, Any]:
    """The ID token's claims. The token comes straight from Google's token endpoint over TLS, in exchange for our client
    secret, so it needs no separate signature check (OpenID Connect Core 1.0, section 3.1.3.7)."""
    settings = get_settings()
    try:
        response = httpx.post(TOKEN_URL, timeout=15, data={
            "code": code, "client_id": settings.google_client_id, "client_secret": settings.google_client_secret,
            "redirect_uri": _redirect_uri(), "grant_type": "authorization_code", "code_verifier": verifier})
        token = response.json().get("id_token") if response.status_code == 200 else None
        return json.loads(_unb64(token.split(".")[1])) if token and token.count(".") == 2 else {}
    except (httpx.HTTPError, ValueError) as error:
        raise GoogleError("failed") from error


def _check(claims: dict[str, Any], nonce: str) -> tuple[str, str]:
    """The Google account's id and email, once the token is for us, current, and answers our own request."""
    if claims.get("iss") not in ISSUERS or claims.get("aud") != get_settings().google_client_id \
            or float(claims.get("exp") or 0) < time.time() or not claims.get("sub") \
            or not hmac.compare_digest(str(claims.get("nonce") or ""), nonce):
        raise GoogleError("failed")
    email = str(claims.get("email") or "").strip().lower()
    if not email or claims.get("email_verified") not in (True, "true"):
        raise GoogleError("unverified")
    return str(claims["sub"]), email


def _account(db: Session, request: Request, subject: str, email: str, name: str) -> User:
    identity = db.scalars(select(UserIdentity).where(UserIdentity.provider == "google",
                                                     UserIdentity.subject == subject)).first()
    if identity is None:
        user = db.scalars(select(User).where(func.lower(User.email) == email)).first()
        if user is not None:
            audit(db, "identity.linked", request, user.id, provider="google")
        else:
            user = User(email=email, role="listener", display_name=(name.strip() or email.split("@")[0])[:120])
            db.add(user)
            db.flush()
            audit(db, "account.created", request, user.id, method="google")
        identity = UserIdentity(user_id=user.id, provider="google", subject=subject)
        db.add(identity)
    else:
        user = identity.user
    identity.email, identity.last_used_at = email, utcnow()
    if user.disabled_at:
        raise GoogleError("disabled")
    return user


def _back(reason: str | None = None) -> RedirectResponse:
    """Back to the app: its home page, or the sign-in screen saying what went wrong."""
    base = get_settings().public_base_url.rstrip("/")
    response = RedirectResponse(f"{base}/sign-in?google={reason}" if reason else f"{base}/", status_code=302)
    response.delete_cookie(STATE_COOKIE, path=STATE_PATH)
    return response


def _require_google() -> None:
    if not get_settings().google_enabled:
        raise HTTPException(status_code=404, detail="Google sign-in isn't available.")


@router.get("/start")
def start(request: Request):
    _require_google()
    ratelimit.limit_ip(request, "google-start", 30, 15 * 60)
    settings = get_settings()
    state, nonce, verifier = new_token(), new_token(), new_token()
    query = urlencode({
        "client_id": settings.google_client_id, "redirect_uri": _redirect_uri(), "response_type": "code",
        "scope": "openid email profile", "state": state, "nonce": nonce, "prompt": "select_account",
        "code_challenge": _b64(hashlib.sha256(verifier.encode()).digest()), "code_challenge_method": "S256"})
    response = RedirectResponse(f"{AUTHORIZE_URL}?{query}", status_code=302)
    # SameSite=Lax: the cookie comes back on Google's redirect (a top-level GET) but on no cross-site POST.
    response.set_cookie(STATE_COOKIE, _sign({"state": state, "nonce": nonce, "verifier": verifier,
                                             "exp": int(time.time()) + STATE_SECONDS}),
                        max_age=STATE_SECONDS, path=STATE_PATH, httponly=True, secure=settings.cookie_secure,
                        samesite="lax")
    return response


@router.get("/callback")
def callback(request: Request, code: str | None = None, state: str | None = None, error: str | None = None,
             db: Session = Depends(get_db)):
    _require_google()
    ratelimit.limit_ip(request, "google-callback", 30, 15 * 60)
    if error:  # "access_denied" when the person closes Google's screen
        return _back("cancelled" if error == "access_denied" else "failed")
    saved = _unsign(request.cookies.get(STATE_COOKIE))
    if not saved or not code or not state or not hmac.compare_digest(state, str(saved.get("state"))):
        return _back("expired")
    try:
        claims = exchange_code(code, str(saved["verifier"]))
        subject, email = _check(claims, str(saved["nonce"]))
        user = _account(db, request, subject, email, str(claims.get("name") or ""))
        db.flush()
    except GoogleError as problem:
        db.rollback()
        return _back(str(problem))
    except IntegrityError:  # the same new account made twice at once
        db.rollback()
        return _back("failed")
    audit(db, "login.google", request, user.id)
    response = _back()
    session_response(db, user, request, response, "web",
                     mfa_verified=remembered(db, user, request, request.cookies.get(DEVICE_COOKIE)))
    return response
