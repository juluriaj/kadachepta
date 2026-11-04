"""Everyone's own account details: name, email, phone, and how they'd like to be contacted.

Listeners, parents, narrators, editors, and admins all use the same endpoints. In a household with a parent
PIN, changes need the PIN (children share the device). When email is on (KC_EMAIL_ENABLED), a new email
address must be confirmed with a code sent to it, because email is also how people sign in. When it's off, the
address is saved as given: it's contact information, and the password still protects the account.
"""

from __future__ import annotations

import re
from datetime import timedelta
from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session

from .. import ratelimit
from ..auth import Identity, audit, require_identity, utcnow
from ..config import get_settings
from ..db import get_db
from ..mailer import send_email
from ..models import AuthSession, EmailOtp, Household, User
from ..security import hash_password, new_otp_code, token_hash, verify_password
from ..services.households import require_parent
from .auth import check_new_password

router = APIRouter(prefix="/api/me", tags=["account"])

EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
CHANNELS = ("email", "phone", "whatsapp")


def normalize_phone(value: str | None) -> str | None:
    """Store phone numbers in E.164. Ten-digit numbers without a country code are taken as Indian (+91)."""
    text = (value or "").strip()
    if not text:
        return None
    digits = re.sub(r"[^\d+]", "", text)
    if digits.startswith("00"):
        digits = "+" + digits[2:]
    if not digits.startswith("+"):
        digits = digits.lstrip("0")
        digits = "+91" + digits if len(digits) == 10 else "+" + digits
    if not re.fullmatch(r"\+[1-9]\d{7,14}", digits):
        raise HTTPException(status_code=422, detail="Enter a phone number with its country code, e.g. +91 98765 43210.")
    return digits


def contact_payload(user: User) -> dict:
    preferences = user.contact_preferences or {}
    return {"userId": user.id, "username": user.username, "displayName": user.display_name, "email": user.email,
            "phone": user.phone, "contactChannel": preferences.get("channel") or "email",
            "contactNotes": preferences.get("notes") or "", "role": user.role, "uiLanguage": user.ui_language,
            "hasPassword": bool(user.password_hash), "emailCodes": get_settings().email_enabled}


def _guard(db: Session, identity: Identity, pin: str | None) -> None:
    household = db.scalars(select(Household).where(Household.owner_user_id == identity.user.id)).first()
    if household:
        require_parent(household, pin)


@router.get("/profile")
def get_profile(identity: Identity = Depends(require_identity)):
    return contact_payload(identity.user)


class ProfileChange(BaseModel):
    displayName: str | None = Field(default=None, min_length=1, max_length=120)
    phone: str | None = Field(default=None, max_length=40)
    contactChannel: Literal["email", "phone", "whatsapp"] | None = None
    contactNotes: str | None = Field(default=None, max_length=300)


@router.patch("/profile")
def update_profile(payload: ProfileChange, request: Request, x_parent_pin: str | None = Header(None),
                   identity: Identity = Depends(require_identity), db: Session = Depends(get_db)):
    _guard(db, identity, x_parent_pin)
    user = db.get(User, identity.user.id)
    fields = payload.model_fields_set
    if payload.displayName is not None:
        user.display_name = payload.displayName.strip()
    if "phone" in fields:
        user.phone = normalize_phone(payload.phone)
    preferences = dict(user.contact_preferences or {})
    if payload.contactChannel:
        preferences["channel"] = payload.contactChannel
    if payload.contactNotes is not None:
        preferences["notes"] = payload.contactNotes.strip()
    channel = preferences.get("channel", "email")
    if channel in ("phone", "whatsapp") and not user.phone:
        raise HTTPException(status_code=422, detail="Add a phone number to be contacted by phone or WhatsApp.")
    if payload.contactChannel == "email" and not user.email:
        raise HTTPException(status_code=422, detail="Add an email address to be contacted by email.")
    user.contact_preferences = preferences
    audit(db, "profile.updated", request, user.id, fields=sorted(fields))
    db.commit()
    return contact_payload(user)


class EmailChange(BaseModel):
    email: str = Field(max_length=230)  # stored with a "change:<user>:" prefix in a 254-character column


@router.post("/email/request", status_code=202)
def request_email_change(payload: EmailChange, request: Request, x_parent_pin: str | None = Header(None),
                         identity: Identity = Depends(require_identity), db: Session = Depends(get_db)):
    _guard(db, identity, x_parent_pin)
    email = payload.email.strip().lower()
    if not EMAIL.match(email):
        raise HTTPException(status_code=422, detail="Enter a valid email address.")
    if email == (identity.user.email or "").lower():
        raise HTTPException(status_code=409, detail="That's already your email address.")
    if db.scalar(select(User.id).where(func.lower(User.email) == email)):
        raise HTTPException(status_code=409, detail="Another account already uses that email address.")
    ratelimit.check(f"email-change:{identity.user.id}", 3, 10 * 60)
    if not get_settings().email_enabled:
        user = db.get(User, identity.user.id)
        previous, user.email = user.email, email
        audit(db, "profile.email-changed", request, user.id, previous=previous, new=email, confirmed=False)
        db.commit()
        return {"ok": True, "codeSent": False, "profile": contact_payload(user)}
    key = f"change:{identity.user.id}:{email}"
    code = new_otp_code()
    db.execute(update(EmailOtp).where(EmailOtp.email == key, EmailOtp.consumed_at.is_(None)).values(consumed_at=utcnow()))
    db.add(EmailOtp(email=key, code_hash=token_hash(f"{key}:{code}"),
                    expires_at=utcnow() + timedelta(minutes=get_settings().otp_ttl_minutes)))
    db.commit()
    send_email(email, f"Confirm your new KathaChepta email: {code}",
               f"Enter {code} in KathaChepta to use this address for your account. It expires in "
               f"{get_settings().otp_ttl_minutes} minutes.\n\nIf you didn't ask for this, you can ignore this email.")
    return {"ok": True, "codeSent": True}


class EmailConfirm(BaseModel):
    email: str = Field(max_length=254)
    code: str = Field(min_length=6, max_length=6)


@router.post("/email/confirm")
def confirm_email_change(payload: EmailConfirm, request: Request, identity: Identity = Depends(require_identity),
                         db: Session = Depends(get_db)):
    email = payload.email.strip().lower()
    key = f"change:{identity.user.id}:{email}"
    otp = db.scalars(select(EmailOtp).where(EmailOtp.email == key, EmailOtp.consumed_at.is_(None))
                     .order_by(EmailOtp.id.desc())).first()
    # 400, not 401: a wrong code must not look like a signed-out session to the app.
    if not otp or otp.expires_at < utcnow() or otp.attempts >= 5:
        raise HTTPException(status_code=400, detail="That code has expired. Ask for a new one.")
    if otp.code_hash != token_hash(f"{key}:{payload.code.strip()}"):
        otp.attempts += 1
        db.commit()
        raise HTTPException(status_code=400, detail="That code isn't right.")
    if db.scalar(select(User.id).where(func.lower(User.email) == email, User.id != identity.user.id)):
        raise HTTPException(status_code=409, detail="Another account already uses that email address.")
    otp.consumed_at = utcnow()
    user = db.get(User, identity.user.id)
    previous, user.email = user.email, email
    audit(db, "profile.email-changed", request, user.id, previous=previous, new=email)
    db.commit()
    if previous:  # tell the old address, in case the change wasn't them
        try:
            send_email(previous, "Your KathaChepta email was changed",
                       f"Your account now uses {email}. If this wasn't you, reply to this email right away.")
        except OSError:
            pass
    return contact_payload(user)


class PasswordChange(BaseModel):
    currentPassword: str | None = Field(default=None, max_length=512)  # not needed when the account has none yet
    newPassword: str = Field(max_length=128)


@router.post("/password")
def change_password(payload: PasswordChange, request: Request, x_parent_pin: str | None = Header(None),
                    identity: Identity = Depends(require_identity), db: Session = Depends(get_db)):
    _guard(db, identity, x_parent_pin)
    ratelimit.check(f"password-change:{identity.user.id}", 10, 15 * 60)
    user = db.get(User, identity.user.id)
    if user.password_hash and not verify_password(payload.currentPassword or "", user.password_hash)[0]:
        audit(db, "password.change-failed", request, user.id)
        db.commit()
        # 400, not 401: a wrong password here must not look like a signed-out session to the app.
        raise HTTPException(status_code=400, detail="Your current password isn't right.")
    check_new_password(payload.newPassword)
    user.password_hash = hash_password(payload.newPassword)
    # Sign out everywhere else and forget remembered devices (they're "device" rows, with no family).
    # This device stays signed in (on a phone, with its refresh token).
    others = [AuthSession.user_id == user.id, AuthSession.id != identity.session.id, AuthSession.revoked_at.is_(None)]
    if identity.session.family_id:
        others.append(or_(AuthSession.family_id.is_(None), AuthSession.family_id != identity.session.family_id))
    db.execute(update(AuthSession).where(*others).values(revoked_at=utcnow()))
    audit(db, "password.changed", request, user.id)
    db.commit()
    return contact_payload(user)
