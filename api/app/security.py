"""Password hashing, opaque tokens, one-time codes, and signed media URLs."""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets
import time

import bcrypt
import pyotp
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

_hasher = PasswordHasher()

ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    "listener": frozenset({"catalog.read"}),
    "parent": frozenset({"catalog.read", "library.manage"}),
    "narrator": frozenset({"catalog.read", "library.manage", "narrator.upload", "narrator.pipeline",
                           "narrator.history"}),
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
    """Return (valid, needs_rehash). Also accepts the prototype's PBKDF2 format and hashes imported from WordPress,
    so old accounts keep working; those are replaced with argon2 at the next sign-in."""
    if not stored:
        return False, False
    if stored.startswith("$argon2"):
        try:
            _hasher.verify(stored, password)
        except (VerificationError, InvalidHashError):
            return False, False
        return True, _hasher.check_needs_rehash(stored)
    if is_wordpress_hash(stored):
        return _verify_wordpress(password, stored), True
    try:
        salt_hex, digest_hex = stored.split("$", 1)
        actual = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt_hex), 240_000)
    except (ValueError, TypeError):
        return False, False
    return secrets.compare_digest(actual.hex(), digest_hex), True


# WordPress formats, checked the way wp_check_password() does (wp-includes/pluggable.php, WordPress 6.8):
# "$wp$2y$…" bcrypt of an HMAC-SHA384 pre-hash (6.8+), "$P$…" phpass (before 6.8), "$2y$…" plain bcrypt (plugins),
# and 32-character MD5 from before WordPress 2.5.
_WP_BCRYPT = re.compile(r"^(\$wp)?\$2[aby]\$\d\d\$[./A-Za-z0-9]{53}$")
_WP_PHPASS = re.compile(r"^\$[PH]\$[./A-Za-z0-9]{31}$")
_WP_MD5 = re.compile(r"^[0-9a-f]{32}$")
_ITOA64 = "./0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"


def is_wordpress_hash(stored: str) -> bool:
    return bool(_WP_BCRYPT.match(stored) or _WP_PHPASS.match(stored) or _WP_MD5.match(stored))


def _verify_wordpress(password: str, stored: str) -> bool:
    secret = password.encode()
    if _WP_MD5.match(stored):
        return hmac.compare_digest(stored, hashlib.md5(secret).hexdigest())
    if _WP_PHPASS.match(stored):
        return hmac.compare_digest(stored, _phpass(secret, stored))
    if stored.startswith("$wp"):
        stored, secret = stored[3:], base64.b64encode(hmac.digest(b"wp-sha384", secret, "sha384"))
    try:
        return bcrypt.checkpw(secret[:72], stored.encode())  # PHP's bcrypt also reads only the first 72 bytes
    except ValueError:
        return False


def _phpass(secret: bytes, setting: str) -> str:
    """Portable phpass: MD5 of salt + password, then 2^n rounds of MD5 (WordPress uses n = 13)."""
    rounds = _ITOA64.index(setting[3])
    if not 7 <= rounds <= 16:  # WordPress never goes past 13; a huge count would only stall the sign-in
        return ""
    digest = hashlib.md5(setting[4:12].encode() + secret).digest()
    for _ in range(1 << rounds):
        digest = hashlib.md5(digest + secret).digest()
    encoded = []
    for start in range(0, len(digest), 3):  # phpass's own base64: little-endian 6-bit groups
        chunk = digest[start:start + 3]
        value = int.from_bytes(chunk, "little")
        encoded += [_ITOA64[(value >> (6 * shift)) & 0x3F] for shift in range(len(chunk) + 1)]
    return setting[:12] + "".join(encoded)


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
