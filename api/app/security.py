"""Password hashing, opaque tokens, one-time codes, and signed media URLs."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time

import pyotp
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

_hasher = PasswordHasher()

ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    "listener": frozenset({"catalog.read"}),
    "parent": frozenset({"catalog.read", "library.manage"}),
    "narrator": frozenset({"catalog.read", "narrator.upload", "narrator.pipeline", "narrator.history"}),
    "editor": frozenset({
        "catalog.read", "transcript.review", "teaser.review", "content.publish", "rights.manage", "metadata.review",
    }),
    "admin": frozenset({
        "catalog.read", "library.manage", "transcript.review", "teaser.review", "content.publish",
        "users.manage", "rights.manage", "metadata.review", "jobs.manage",
    }),
}
STAFF_ROLES = frozenset({"editor", "admin"})


def permissions_for(role: str) -> list[str]:
    return sorted(ROLE_PERMISSIONS.get(role, frozenset()))


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, stored: str | None) -> tuple[bool, bool]:
    """Return (valid, needs_rehash). Accepts the prototype's PBKDF2 format so old accounts keep working."""
    if not stored:
        return False, False
    if stored.startswith("$argon2"):
        try:
            _hasher.verify(stored, password)
        except (VerificationError, InvalidHashError):
            return False, False
        return True, _hasher.check_needs_rehash(stored)
    try:
        salt_hex, digest_hex = stored.split("$", 1)
        actual = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt_hex), 240_000)
    except (ValueError, TypeError):
        return False, False
    return secrets.compare_digest(actual.hex(), digest_hex), True


def new_token() -> str:
    return secrets.token_urlsafe(32)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def new_otp_code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def new_totp_secret() -> str:
    return pyotp.random_base32()


def verify_totp(secret: str, code: str) -> bool:
    return bool(secret) and pyotp.TOTP(secret).verify(str(code).strip(), valid_window=1)


def totp_uri(secret: str, account: str) -> str:
    return pyotp.TOTP(secret).provisioning_uri(name=account, issuer_name="KathaChepta")


def sign_media(key: str, secret: str, ttl_seconds: int, now: float | None = None) -> tuple[int, str]:
    expires = int((now or time.time()) + ttl_seconds)
    # Round expiry up to the TTL bucket so URLs stay stable (and cacheable) for a while.
    bucket = max(ttl_seconds // 4, 60)
    expires = expires - expires % bucket + bucket
    return expires, _media_signature(key, expires, secret)


def verify_media(key: str, expires: int, signature: str, secret: str) -> bool:
    if expires < time.time():
        return False
    return hmac.compare_digest(_media_signature(key, expires, secret), signature)


def _media_signature(key: str, expires: int, secret: str) -> str:
    mac = hmac.new(secret.encode(), f"{key}\n{expires}".encode(), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(mac[:18]).decode().rstrip("=")
