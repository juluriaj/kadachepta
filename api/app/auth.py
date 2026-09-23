"""Request authentication: web session cookies and mobile bearer tokens."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import get_settings
from .db import get_db
from .models import AuditLog, AuthSession, User
from .security import STAFF_ROLES, new_token, permissions_for, token_hash

SESSION_COOKIE = "kc_session"


@dataclass
class Identity:
    user: User
    session: AuthSession
    permissions: list[str] = field(default_factory=list)

    @property
    def username(self) -> str:
        return self.user.handle

    @property
    def role(self) -> str:
        return self.user.role

    def public(self) -> dict:
        return {
            "authenticated": True,
            "userId": self.user.id,
            "username": self.username,
            "displayName": self.user.display_name,
            "email": self.user.email,
            "role": self.role,
            "permissions": self.permissions,
            "uiLanguage": self.user.ui_language,
            "listeningLanguages": self.user.listening_languages,
            "mfaEnabled": self.user.totp_enabled,
            "mfaVerified": self.session.mfa_verified,
        }


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def client_ip(request: Request) -> str | None:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()[:64]
    return request.client.host if request.client else None


def audit(db: Session, action: str, request: Request | None = None, user_id: int | None = None, **detail) -> None:
    db.add(AuditLog(actor_user_id=user_id, action=action, detail=detail, ip=client_ip(request) if request else None))


def create_session(db: Session, user: User, kind: str, request: Request | None, *,
                   family_id: str | None = None, mfa_verified: bool = False) -> str:
    settings = get_settings()
    lifetime = {
        "web": timedelta(hours=settings.session_ttl_hours),
        "access": timedelta(minutes=settings.access_token_minutes),
        "refresh": timedelta(days=settings.refresh_token_days),
    }[kind]
    token = new_token()
    db.add(AuthSession(
        user_id=user.id, token_hash=token_hash(token), kind=kind, family_id=family_id,
        expires_at=utcnow() + lifetime, mfa_verified=mfa_verified,
        user_agent=(request.headers.get("user-agent", "")[:300] if request else None),
        ip=client_ip(request) if request else None,
    ))
    return token


def _lookup(db: Session, token: str, kinds: tuple[str, ...]) -> AuthSession | None:
    row = db.scalars(select(AuthSession).where(AuthSession.token_hash == token_hash(token))).first()
    if not row or row.kind not in kinds or row.revoked_at or row.expires_at < utcnow():
        return None
    if row.user.disabled_at:
        return None
    return row


def optional_identity(request: Request, db: Session = Depends(get_db)) -> Identity | None:
    token, kinds = None, ()
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        token, kinds = header[7:].strip(), ("access",)
    elif request.cookies.get(SESSION_COOKIE):
        token, kinds = request.cookies[SESSION_COOKIE], ("web",)
    if not token:
        return None
    session = _lookup(db, token, kinds)
    if not session:
        return None
    now = utcnow()
    if not session.last_used_at or now - session.last_used_at > timedelta(minutes=5):
        session.last_used_at = now
        db.commit()
    user = session.user
    permissions = permissions_for(user.role)
    settings = get_settings()
    # Staff with MFA pending get no permissions until the second factor is verified.
    if user.role in STAFF_ROLES and (settings.staff_mfa_required or user.totp_enabled) and not session.mfa_verified:
        permissions = []
    return Identity(user=user, session=session, permissions=permissions)


def require_identity(identity: Identity | None = Depends(optional_identity)) -> Identity:
    if not identity:
        raise HTTPException(status_code=401, detail="Login required.")
    return identity


def require(permission: str):
    def dependency(identity: Identity = Depends(require_identity)) -> Identity:
        if permission not in identity.permissions:
            if identity.user.role in STAFF_ROLES and not identity.session.mfa_verified and (
                identity.user.totp_enabled or get_settings().staff_mfa_required
            ):
                raise HTTPException(status_code=403, detail="Two-factor verification required.")
            raise HTTPException(status_code=403, detail="Insufficient permission.")
        return identity

    return dependency
