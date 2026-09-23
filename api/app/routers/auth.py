"""Sign-in flows.

- Staff and legacy accounts: username/email + password, then TOTP for staff.
- Listeners: passwordless email one-time code (creates the account on first use).
- Web gets an httpOnly session cookie; mobile gets access + rotating refresh tokens.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from .. import ratelimit
from ..auth import (
    SESSION_COOKIE, Identity, audit, create_session, optional_identity, require_identity, utcnow,
)
from ..config import get_settings
from ..db import get_db
from ..mailer import send_email
from ..models import AuthSession, EmailOtp, User
from ..security import (
    STAFF_ROLES, hash_password, new_otp_code, new_totp_secret, permissions_for, token_hash, totp_uri,
    verify_password, verify_totp,
)

router = APIRouter(prefix="/api", tags=["auth"])

Client = Literal["web", "mobile"]


class PasswordLogin(BaseModel):
    username: str = Field(min_length=1, max_length=254)
    password: str = Field(min_length=1, max_length=512)
    client: Client = "web"


class OtpRequest(BaseModel):
    email: EmailStr


class OtpVerify(BaseModel):
    email: EmailStr
    code: str = Field(min_length=6, max_length=6)
    client: Client = "web"


class TotpCode(BaseModel):
    code: str = Field(min_length=6, max_length=8)


class RefreshRequest(BaseModel):
    refreshToken: str


def _mfa_state(user: User) -> dict:
    settings = get_settings()
    staff = user.role in STAFF_ROLES
    return {
        "mfaRequired": staff and user.totp_enabled,
        "mfaEnrollmentRequired": staff and settings.staff_mfa_required and not user.totp_enabled,
    }


def _session_response(db: Session, user: User, request: Request, response: Response, client: Client,
                      *, mfa_verified: bool = False) -> dict:
    user.last_login_at = utcnow()
    body = {
        "authenticated": True, "userId": user.id, "username": user.handle, "displayName": user.display_name,
        "email": user.email, "role": user.role, "permissions": permissions_for(user.role),
        "uiLanguage": user.ui_language, "listeningLanguages": user.listening_languages,
        **_mfa_state(user),
    }
    if body["mfaRequired"] or body["mfaEnrollmentRequired"]:
        body["permissions"] = []
    if client == "mobile":
        family = str(uuid.uuid4())
        body["accessToken"] = create_session(db, user, "access", request, family_id=family, mfa_verified=mfa_verified)
        body["refreshToken"] = create_session(db, user, "refresh", request, family_id=family, mfa_verified=mfa_verified)
        body["accessTokenExpiresIn"] = get_settings().access_token_minutes * 60
    else:
        token = create_session(db, user, "web", request, mfa_verified=mfa_verified)
        _set_cookie(response, token)
    db.commit()
    return body


def _set_cookie(response: Response, token: str) -> None:
    settings = get_settings()
    response.set_cookie(SESSION_COOKIE, token, httponly=True, samesite="lax", secure=settings.cookie_secure,
                        max_age=settings.session_ttl_hours * 3600, path="/")


@router.post("/login")
def password_login(payload: PasswordLogin, request: Request, response: Response, db: Session = Depends(get_db)):
    ratelimit.limit_ip(request, "login", 10, 60)
    ratelimit.check(f"login:user:{payload.username.lower()}", 20, 15 * 60)
    identifier = payload.username.strip().lower()
    user = db.scalars(select(User).where(
        (func.lower(User.username) == identifier) | (func.lower(User.email) == identifier))).first()
    valid, needs_rehash = verify_password(payload.password, user.password_hash if user else None)
    if not user or not valid or user.disabled_at:
        audit(db, "login.failed", request, user.id if user else None, username=identifier)
        db.commit()
        raise HTTPException(status_code=401, detail="Invalid username or password.")
    if needs_rehash:
        user.password_hash = hash_password(payload.password)
    audit(db, "login.password", request, user.id)
    return _session_response(db, user, request, response, payload.client)


@router.post("/auth/otp/request", status_code=202)
def request_otp(payload: OtpRequest, request: Request, db: Session = Depends(get_db)):
    email = payload.email.lower()
    ratelimit.limit_ip(request, "otp-request", 10, 15 * 60)
    ratelimit.check(f"otp-request:email:{email}", 3, 10 * 60)
    code = new_otp_code()
    db.execute(update(EmailOtp).where(EmailOtp.email == email, EmailOtp.consumed_at.is_(None))
               .values(consumed_at=utcnow()))
    db.add(EmailOtp(email=email, code_hash=token_hash(f"{email}:{code}"),
                    expires_at=utcnow() + timedelta(minutes=get_settings().otp_ttl_minutes)))
    db.commit()
    send_email(email, f"Your KathaChepta code: {code}",
               f"Your sign-in code is {code}. It expires in {get_settings().otp_ttl_minutes} minutes.\n\n"
               "If you didn't ask for this, you can ignore this email.")
    return {"ok": True, "expiresInMinutes": get_settings().otp_ttl_minutes}


@router.post("/auth/otp/verify")
def verify_otp(payload: OtpVerify, request: Request, response: Response, db: Session = Depends(get_db)):
    email = payload.email.lower()
    ratelimit.limit_ip(request, "otp-verify", 20, 15 * 60)
    otp = db.scalars(select(EmailOtp).where(EmailOtp.email == email, EmailOtp.consumed_at.is_(None))
                     .order_by(EmailOtp.id.desc())).first()
    if not otp or otp.expires_at < utcnow() or otp.attempts >= 5:
        raise HTTPException(status_code=401, detail="That code has expired. Request a new one.")
    if otp.code_hash != token_hash(f"{email}:{payload.code.strip()}"):
        otp.attempts += 1
        db.commit()
        raise HTTPException(status_code=401, detail="That code isn't right. Check the email and try again.")
    otp.consumed_at = utcnow()
    user = db.scalars(select(User).where(func.lower(User.email) == email)).first()
    if not user:
        user = User(email=email, role="listener", display_name=email.split("@")[0])
        db.add(user)
        db.flush()
        audit(db, "account.created", request, user.id, method="email-otp")
    if user.disabled_at:
        raise HTTPException(status_code=403, detail="This account is disabled.")
    audit(db, "login.otp", request, user.id)
    return _session_response(db, user, request, response, payload.client)


@router.post("/auth/refresh")
def refresh(payload: RefreshRequest, request: Request, db: Session = Depends(get_db)):
    ratelimit.limit_ip(request, "refresh", 60, 60)
    row = db.scalars(select(AuthSession).where(AuthSession.token_hash == token_hash(payload.refreshToken))).first()
    if not row or row.kind != "refresh":
        raise HTTPException(status_code=401, detail="Invalid refresh token.")
    if row.revoked_at:
        # A rotated token was reused: assume theft and end the whole token family.
        db.execute(update(AuthSession).where(AuthSession.family_id == row.family_id, AuthSession.revoked_at.is_(None))
                   .values(revoked_at=utcnow()))
        audit(db, "token.reuse-detected", request, row.user_id, family=row.family_id)
        db.commit()
        raise HTTPException(status_code=401, detail="Session ended for security reasons. Please sign in again.")
    if row.expires_at < utcnow() or row.user.disabled_at:
        raise HTTPException(status_code=401, detail="Session expired. Please sign in again.")
    row.revoked_at = utcnow()
    access = create_session(db, row.user, "access", request, family_id=row.family_id, mfa_verified=row.mfa_verified)
    new_refresh = create_session(db, row.user, "refresh", request, family_id=row.family_id,
                                 mfa_verified=row.mfa_verified)
    db.commit()
    return {"accessToken": access, "refreshToken": new_refresh,
            "accessTokenExpiresIn": get_settings().access_token_minutes * 60}


@router.post("/logout")
def logout(request: Request, response: Response, identity: Identity | None = Depends(optional_identity),
           db: Session = Depends(get_db)):
    if identity:
        now = utcnow()
        identity.session.revoked_at = now
        if identity.session.family_id:
            db.execute(update(AuthSession).where(AuthSession.family_id == identity.session.family_id,
                                                 AuthSession.revoked_at.is_(None)).values(revoked_at=now))
        audit(db, "logout", request, identity.user.id)
        db.commit()
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"ok": True}


@router.get("/session")
def session(identity: Identity | None = Depends(optional_identity)):
    if not identity:
        return {"authenticated": False}
    body = {**identity.public(), **_mfa_state(identity.user)}
    if identity.session.mfa_verified:
        body.update(mfaRequired=False, mfaEnrollmentRequired=False)
    return body


@router.post("/auth/totp/setup")
def totp_setup(identity: Identity = Depends(require_identity), db: Session = Depends(get_db)):
    user = identity.user
    if user.totp_enabled:
        raise HTTPException(status_code=409, detail="Two-factor authentication is already enabled.")
    user.totp_secret = new_totp_secret()
    db.commit()
    return {"secret": user.totp_secret, "otpauthUri": totp_uri(user.totp_secret, user.handle)}


@router.post("/auth/totp/verify")
def totp_verify(payload: TotpCode, request: Request, identity: Identity = Depends(require_identity),
                db: Session = Depends(get_db)):
    ratelimit.check(f"totp:user:{identity.user.id}", 10, 15 * 60)
    user = identity.user
    if not user.totp_secret or not verify_totp(user.totp_secret, payload.code):
        audit(db, "mfa.failed", request, user.id)
        db.commit()
        raise HTTPException(status_code=401, detail="That code isn't right. Check your authenticator app.")
    if not user.totp_enabled:
        user.totp_enabled = True
        audit(db, "mfa.enabled", request, user.id)
    identity.session.mfa_verified = True
    audit(db, "mfa.verified", request, user.id)
    db.commit()
    return {**identity.public(), "permissions": permissions_for(user.role), "mfaVerified": True,
            "mfaRequired": False, "mfaEnrollmentRequired": False}
