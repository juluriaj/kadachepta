import hashlib
import re

import pyotp
from sqlalchemy import select

from app import mailer
from app.config import get_settings
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
    assert client.get("/api/session").json() == {"authenticated": False, "emailSignIn": True, "googleSignIn": False}


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


def _enrolled_editor(client, db, username: str = "remember-me") -> str:
    make_user(db, username, "editor")
    login(client, username)
    secret = client.post("/api/auth/totp/setup").json()["secret"]
    assert client.post("/api/auth/totp/verify", json={"code": pyotp.TOTP(secret).now()}).status_code == 200
    client.post("/api/logout")
    return secret


def test_remembered_browser_skips_the_code(client, db):
    secret = _enrolled_editor(client, db)
    assert login(client, "remember-me")["mfaRequired"]
    verified = client.post("/api/auth/totp/verify", json={"code": pyotp.TOTP(secret).now(), "rememberDevice": True})
    assert "kc_device" in verified.cookies and "deviceToken" not in verified.json()
    client.post("/api/logout")
    assert "kc_device" in client.cookies  # signing out keeps the device remembered

    body = login(client, "remember-me")
    assert not body["mfaRequired"] and "content.publish" in body["permissions"]
    assert client.get("/api/dashboard").status_code == 200
    assert client.get("/api/session").json()["mfaVerified"]
    assert db.scalars(select(AuditLog).where(AuditLog.action == "mfa.remembered-device")).first()

    # Still needs the password, and the token isn't a session by itself.
    device = client.cookies.get("kc_device")
    client.post("/api/logout")
    assert client.post("/api/login", json={"username": "remember-me", "password": "wrong"}).status_code == 401
    client.cookies.clear()
    assert client.get("/api/session", headers={"Cookie": f"kc_session={device}"}).json()["authenticated"] is False
    assert client.get("/api/session", headers={"Authorization": f"Bearer {device}"}).json()["authenticated"] is False
    assert client.post("/api/auth/refresh", json={"refreshToken": device}).status_code == 401

    # Another account on the same browser still needs its own code.
    make_user(db, "other-editor", "editor", totp_enabled=True, totp_secret=pyotp.random_base32())
    other = client.post("/api/login", json={"username": "other-editor", "password": "correct horse battery"},
                        headers={"Cookie": f"kc_device={device}"})
    assert other.json()["mfaRequired"]
    # ...while the owner, with only that cookie, doesn't.
    owner = client.post("/api/login", json={"username": "remember-me", "password": "correct horse battery"},
                        headers={"Cookie": f"kc_device={device}"})
    assert not owner.json()["mfaRequired"]


def test_unticked_and_forgotten_devices_ask_again(client, db):
    secret = _enrolled_editor(client, db)
    login(client, "remember-me")
    client.post("/api/auth/totp/verify", json={"code": pyotp.TOTP(secret).now()})
    assert "kc_device" not in client.cookies
    client.post("/api/logout")
    assert login(client, "remember-me")["mfaRequired"]

    client.post("/api/auth/totp/verify", json={"code": pyotp.TOTP(secret).now(), "rememberDevice": True})
    listed = client.get("/api/auth/devices").json()
    assert listed["days"] == 30 and len(listed["devices"]) == 1
    forgotten = client.post("/api/auth/devices/forget", json={})
    assert forgotten.json()["forgotten"] == 1 and not client.get("/api/auth/devices").json()["devices"]
    client.post("/api/logout")
    assert login(client, "remember-me")["mfaRequired"]


def test_password_change_forgets_remembered_devices(client, db):
    secret = _enrolled_editor(client, db)
    login(client, "remember-me")
    client.post("/api/auth/totp/verify", json={"code": pyotp.TOTP(secret).now(), "rememberDevice": True})
    changed = client.post("/api/me/password", json={"currentPassword": "correct horse battery",
                                                    "newPassword": "a new password"})
    assert changed.status_code == 200, changed.text
    client.post("/api/logout")
    assert login(client, "remember-me", "a new password")["mfaRequired"]


def test_remembered_phone_skips_the_code(client, db):
    secret = _enrolled_editor(client, db)
    client.cookies.clear()
    mobile = {"username": "remember-me", "password": "correct horse battery", "client": "mobile"}
    tokens = client.post("/api/login", json=mobile).json()
    assert tokens["mfaRequired"]
    verified = client.post("/api/auth/totp/verify", json={"code": pyotp.TOTP(secret).now(), "rememberDevice": True},
                           headers={"Authorization": f"Bearer {tokens['accessToken']}"}).json()
    assert verified["deviceToken"] and "kc_device" not in client.cookies
    again = client.post("/api/login", json={**mobile, "deviceToken": verified["deviceToken"]}).json()
    assert not again["mfaRequired"] and "content.publish" in again["permissions"]
    headers = {"Authorization": f"Bearer {again['accessToken']}"}
    assert client.get("/api/dashboard", headers=headers).status_code == 200
    # The refreshed tokens keep the verification.
    rotated = client.post("/api/auth/refresh", json={"refreshToken": again["refreshToken"]}).json()
    assert client.get("/api/dashboard", headers={"Authorization": f"Bearer {rotated['accessToken']}"}).status_code == 200
    assert client.post("/api/login", json={**mobile, "deviceToken": "made-up"}).json()["mfaRequired"]


def test_email_otp_creates_listener_account(client, db):
    assert client.post("/api/auth/otp/request", json={"email": "Parent@Example.com"}).status_code == 202
    code = re.search(r"\b(\d{6})\b", mailer.sent_messages[-1]["Subject"]).group(1)
    wrong = "000000" if code != "000000" else "111111"
    assert client.post("/api/auth/otp/verify", json={"email": "parent@example.com", "code": wrong}).status_code == 401
    body = client.post("/api/auth/otp/verify", json={"email": "parent@example.com", "code": code}).json()
    assert body["role"] == "listener" and body["email"] == "parent@example.com"
    # A code works once.
    assert client.post("/api/auth/otp/verify", json={"email": "parent@example.com", "code": code}).status_code == 401


def test_listener_signs_up_with_a_username_and_password(client, db):
    short = client.post("/api/auth/register", json={"username": "asha", "password": "short"})
    assert short.status_code == 422 and "8 characters" in short.json()["error"]
    for bad in ("a@example.com", "ab", "-asha", "asha k"):
        assert client.post("/api/auth/register", json={"username": bad, "password": "long enough"}).status_code == 422
    body = client.post("/api/auth/register", json={"username": " Asha.K ", "password": "long enough"}).json()
    assert body["role"] == "listener" and body["username"] == "asha.k" and "kc_session" in client.cookies
    client.post("/api/logout")
    assert client.post("/api/auth/register", json={"username": "ASHA.K", "password": "other one"}).status_code == 409
    assert login(client, "Asha.K", "long enough")["username"] == "asha.k"
    assert db.scalars(select(AuditLog).where(AuditLog.action == "account.created")).one().detail["method"] == "password"


def test_without_email_only_passwords_sign_in(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "email_enabled", False)
    assert client.get("/api/session").json() == {"authenticated": False, "emailSignIn": False, "googleSignIn": False}
    assert client.post("/api/auth/otp/request", json={"email": "a@example.com"}).status_code == 404
    assert client.post("/api/auth/otp/verify", json={"email": "a@example.com", "code": "123456"}).status_code == 404
    assert not mailer.sent_messages


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
