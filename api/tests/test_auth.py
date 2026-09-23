import hashlib
import re

import pyotp
from sqlalchemy import select

from app import mailer
from app.models import AuditLog, AuthSession, User

from .conftest import login, make_user


def test_password_login_session_and_logout(client, db):
    make_user(db, "editor1", "editor")
    body = login(client, "editor1")
    assert body["role"] == "editor" and "content.publish" in body["permissions"]
    assert "kc_session" in client.cookies
    session = client.get("/api/session").json()
    assert session["authenticated"] and session["username"] == "editor1"
    assert client.post("/api/logout").status_code == 200
    assert client.get("/api/session").json() == {"authenticated": False}


def test_legacy_pbkdf2_password_is_accepted_and_upgraded(client, db):
    salt = bytes(16)
    legacy = f"{salt.hex()}${hashlib.pbkdf2_hmac('sha256', b'change-me', salt, 240_000).hex()}"
    db.add(User(username="old", role="listener", password_hash=legacy))
    db.commit()
    login(client, "old", "change-me")
    db.expire_all()
    assert db.scalars(select(User).where(User.username == "old")).one().password_hash.startswith("$argon2")


def test_wrong_password_is_rejected_and_audited(client, db):
    make_user(db, "listener1", "listener")
    response = client.post("/api/login", json={"username": "listener1", "password": "nope"})
    assert response.status_code == 401 and response.json()["error"] == "Invalid username or password."
    assert db.scalars(select(AuditLog).where(AuditLog.action == "login.failed")).first()


def test_login_rate_limit(client, db):
    make_user(db, "someone", "listener")
    codes = [client.post("/api/login", json={"username": "someone", "password": "x"}).status_code for _ in range(11)]
    assert codes[:10] == [401] * 10 and codes[10] == 429


def test_staff_totp_enrollment_and_enforcement(client, db):
    make_user(db, "mfa-editor", "editor")
    login(client, "mfa-editor")
    secret = client.post("/api/auth/totp/setup").json()["secret"]
    assert client.post("/api/auth/totp/verify", json={"code": "000000"}).status_code == 401
    assert client.post("/api/auth/totp/verify", json={"code": pyotp.TOTP(secret).now()}).status_code == 200
    client.post("/api/logout")

    body = login(client, "mfa-editor")
    assert body["mfaRequired"] and body["permissions"] == []
    blocked = client.get("/api/dashboard")
    assert blocked.status_code == 403 and "Two-factor" in blocked.json()["error"]
    verified = client.post("/api/auth/totp/verify", json={"code": pyotp.TOTP(secret).now()}).json()
    assert "content.publish" in verified["permissions"]
    assert client.get("/api/dashboard").status_code == 200


def test_email_otp_creates_listener_account(client, db):
    assert client.post("/api/auth/otp/request", json={"email": "Parent@Example.com"}).status_code == 202
    code = re.search(r"\b(\d{6})\b", mailer.sent_messages[-1]["Subject"]).group(1)
    wrong = "000000" if code != "000000" else "111111"
    assert client.post("/api/auth/otp/verify", json={"email": "parent@example.com", "code": wrong}).status_code == 401
    body = client.post("/api/auth/otp/verify", json={"email": "parent@example.com", "code": code}).json()
    assert body["role"] == "listener" and body["email"] == "parent@example.com"
    # A code works once.
    assert client.post("/api/auth/otp/verify", json={"email": "parent@example.com", "code": code}).status_code == 401


def test_otp_request_is_rate_limited_per_email(client):
    codes = [client.post("/api/auth/otp/request", json={"email": "a@example.com"}).status_code for _ in range(4)]
    assert codes == [202, 202, 202, 429]


def test_mobile_tokens_rotate_and_detect_reuse(client, db):
    make_user(db, "phone", "listener")
    tokens = client.post("/api/login", json={"username": "phone", "password": "correct horse battery",
                                             "client": "mobile"}).json()
    assert "kc_session" not in client.cookies
    headers = {"Authorization": f"Bearer {tokens['accessToken']}"}
    assert client.get("/api/me/favorites", headers=headers).status_code == 200
    rotated = client.post("/api/auth/refresh", json={"refreshToken": tokens["refreshToken"]}).json()
    assert rotated["refreshToken"] != tokens["refreshToken"]
    # Reusing the old refresh token ends the whole family, including the new tokens.
    assert client.post("/api/auth/refresh", json={"refreshToken": tokens["refreshToken"]}).status_code == 401
    assert client.post("/api/auth/refresh", json={"refreshToken": rotated["refreshToken"]}).status_code == 401
    assert db.scalars(select(AuditLog).where(AuditLog.action == "token.reuse-detected")).first()
    live = db.scalars(select(AuthSession).where(AuthSession.revoked_at.is_(None))).all()
    assert all(row.kind != "refresh" for row in live)


def test_cross_site_cookie_write_is_blocked(client, db):
    make_user(db, "victim", "listener")
    login(client, "victim")
    response = client.post("/api/me/favorites", json={"assetId": "x"}, headers={"Origin": "https://evil.example"})
    assert response.status_code == 403


def test_disabled_account_cannot_sign_in(client, db):
    from datetime import datetime, timezone
    make_user(db, "gone", "listener", disabled_at=datetime.now(timezone.utc))
    assert client.post("/api/login", json={"username": "gone", "password": "correct horse battery"}).status_code == 401
