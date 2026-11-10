"""Continue with Google: the round trip, account linking, and what must stop it."""

import time
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlparse

import pyotp
import pytest
from sqlalchemy import func, select

from app.config import get_settings
from app.models import AuditLog, User, UserIdentity
from app.routers import google_auth

from .conftest import make_user

APP = "http://localhost:8080"
CLIENT_ID = "test-client.apps.googleusercontent.com"


@pytest.fixture
def google(monkeypatch):
    """Google sign-in switched on, with Google's token endpoint replaced: the test sets the account it answers with."""
    settings = get_settings()
    monkeypatch.setattr(settings, "google_client_id", CLIENT_ID)
    monkeypatch.setattr(settings, "google_client_secret", "test-secret")
    monkeypatch.setattr(settings, "public_base_url", APP)
    answer: dict = {}

    def exchange(code, verifier):
        assert code == "the-code" and len(verifier) >= 43
        return {"iss": "https://accounts.google.com", "aud": CLIENT_ID, "exp": time.time() + 300, "sub": "google-123",
                "email": "Amma@Gmail.com", "email_verified": True, "name": "Amma K", **answer,
                "nonce": answer.get("nonce", answer.get("_nonce"))}

    monkeypatch.setattr(google_auth, "exchange_code", exchange)
    return answer


def begin(client, answer):
    """Start sign-in like the browser does, and note the nonce Google would put in the token."""
    response = client.get("/api/auth/google/start", follow_redirects=False)
    assert response.status_code == 302
    query = parse_qs(urlparse(response.headers["location"]).query)
    answer["_nonce"] = query["nonce"][0]
    return query


def finish(client, state, **extra):
    return client.get("/api/auth/google/callback", params={"code": "the-code", "state": state, **extra},
                      follow_redirects=False)


def test_start_sends_the_browser_to_google_with_pkce(client, google):
    response = client.get("/api/auth/google/start", follow_redirects=False)
    target = urlparse(response.headers["location"])
    query = parse_qs(target.query)
    assert target.netloc == "accounts.google.com"
    assert query["client_id"] == [CLIENT_ID] and query["scope"] == ["openid email profile"]
    assert query["redirect_uri"] == [f"{APP}/api/auth/google/callback"]
    assert query["code_challenge_method"] == ["S256"] and query["state"][0] and query["nonce"][0]
    cookie = response.headers["set-cookie"]
    assert "kc_google=" in cookie and "HttpOnly" in cookie and "Path=/api/auth/google" in cookie
    assert query["state"][0] not in cookie.split(";")[0].split(".")[-1]  # the signature, not the state itself


def test_new_google_account_becomes_a_listener(client, db, google):
    query = begin(client, google)
    response = finish(client, query["state"][0])
    assert response.status_code == 302 and response.headers["location"] == f"{APP}/"
    session = client.get("/api/session").json()
    assert session["authenticated"] and session["role"] == "listener" and session["email"] == "amma@gmail.com"
    user = db.scalars(select(User).where(User.email == "amma@gmail.com")).one()
    assert user.display_name == "Amma K" and user.password_hash is None
    assert db.scalars(select(UserIdentity)).one().subject == "google-123"
    assert db.scalars(select(AuditLog).where(AuditLog.action == "account.created")).one().detail["method"] == "google"


def test_google_joins_the_account_with_the_same_email(client, db, google):
    old = make_user(db, "wp-amma", "listener", email="amma@gmail.com")
    finish(client, begin(client, google)["state"][0])
    assert client.get("/api/session").json()["userId"] == old.id
    assert db.scalars(select(AuditLog).where(AuditLog.action == "identity.linked")).one()
    client.post("/api/logout")
    # Next time the Google account itself is the key, even if its email changes.
    google["email"] = "amma.new@gmail.com"
    finish(client, begin(client, google)["state"][0])
    assert client.get("/api/session").json()["userId"] == old.id
    assert db.scalar(select(func.count(UserIdentity.id))) == 1


def test_team_member_still_needs_the_authenticator_code(client, db, google):
    secret = pyotp.random_base32()
    make_user(db, "editor-g", "editor", email="amma@gmail.com", totp_enabled=True, totp_secret=secret)
    finish(client, begin(client, google)["state"][0])
    session = client.get("/api/session").json()
    assert session["role"] == "editor" and session["mfaRequired"] and session["permissions"] == []
    assert client.post("/api/auth/totp/verify", json={"code": pyotp.TOTP(secret).now()}).status_code == 200


@pytest.mark.parametrize("change, reason", [
    ({"aud": "someone-else"}, "failed"),
    ({"iss": "https://evil.example"}, "failed"),
    ({"exp": time.time() - 10}, "failed"),
    ({"nonce": "replayed"}, "failed"),
    ({"email_verified": False}, "unverified"),
])
def test_bad_tokens_are_refused(client, db, google, change, reason):
    query = begin(client, google)
    google.update(change)
    response = finish(client, query["state"][0])
    assert response.headers["location"] == f"{APP}/sign-in?google={reason}"
    assert client.get("/api/session").json()["authenticated"] is False
    assert not db.scalars(select(User)).all()


def test_state_must_match_this_browser(client, db, google):
    begin(client, google)
    assert finish(client, "forged-state").headers["location"] == f"{APP}/sign-in?google=expired"
    client.cookies.clear()
    state = begin(client, google)["state"][0]
    client.cookies.clear()  # another browser: no cookie from the start
    assert finish(client, state).headers["location"] == f"{APP}/sign-in?google=expired"


def test_cancelled_at_google(client, google):
    begin(client, google)
    response = client.get("/api/auth/google/callback", params={"error": "access_denied"}, follow_redirects=False)
    assert response.headers["location"] == f"{APP}/sign-in?google=cancelled"


def test_closed_account_cannot_sign_in(client, db, google):
    make_user(db, "gone-g", "listener", email="amma@gmail.com", disabled_at=datetime.now(timezone.utc))
    response = finish(client, begin(client, google)["state"][0])
    assert response.headers["location"] == f"{APP}/sign-in?google=disabled"
    assert client.get("/api/session").json()["authenticated"] is False


def test_off_until_configured(client):
    assert client.get("/api/auth/google/start", follow_redirects=False).status_code == 404
    assert client.get("/api/session").json()["googleSignIn"] is False


def test_sign_in_screen_is_told_google_is_on(client, google):
    assert client.get("/api/session").json()["googleSignIn"] is True


def test_deleting_the_account_lets_google_start_afresh(client, db, google):
    finish(client, begin(client, google)["state"][0])
    first = client.get("/api/session").json()["userId"]
    assert client.post("/api/me/delete", json={"confirm": "DELETE"}).status_code == 200
    assert not db.scalars(select(UserIdentity)).all()
    finish(client, begin(client, google)["state"][0])
    assert client.get("/api/session").json()["userId"] != first
