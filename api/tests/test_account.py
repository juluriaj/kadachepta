"""Contact details on every kind of account."""

import re

from fastapi.testclient import TestClient

from app import mailer
from app.config import get_settings
from app.main import app
from app.models import Household, User
from app.security import hash_password

from .conftest import login, make_asset, make_user


def code_in_last_email() -> str:
    return re.search(r"\b(\d{6})\b", mailer.sent_messages[-1]["Subject"]).group(1)


def test_every_role_can_keep_contact_details(client, db):
    for role in ("listener", "parent", "narrator", "editor", "admin"):
        make_user(db, role, role)
        login(client, role)
        response = client.patch("/api/me/profile", json={"displayName": f"{role} person", "phone": "98765 43210",
                                                         "contactChannel": "whatsapp", "contactNotes": "after 6 pm"})
        assert response.status_code == 200, (role, response.text)
        body = client.get("/api/me/profile").json()
        assert body["phone"] == "+919876543210" and body["contactChannel"] == "whatsapp"
        assert body["contactNotes"] == "after 6 pm" and body["displayName"] == f"{role} person"


def test_phone_rules(client, db):
    make_user(db, "lis", "listener")
    login(client, "lis")
    assert client.patch("/api/me/profile", json={"phone": "+1 (415) 555-0100"}).json()["phone"] == "+14155550100"
    assert client.patch("/api/me/profile", json={"phone": "12"}).status_code == 422
    assert client.patch("/api/me/profile", json={"phone": None, "contactChannel": "phone"}).status_code == 422
    assert client.patch("/api/me/profile", json={"phone": ""}).json()["phone"] is None


def test_parent_pin_protects_account_details(client, db):
    user = make_user(db, "mum", "parent")
    db.add(Household(owner_user_id=user.id, parental_pin_hash=hash_password("1234")))
    db.commit()
    login(client, "mum")
    assert client.patch("/api/me/profile", json={"phone": "9876543210"}).status_code == 403
    ok = client.patch("/api/me/profile", json={"phone": "9876543210"}, headers={"X-Parent-Pin": "1234"})
    assert ok.status_code == 200


def test_changing_email_needs_the_code_sent_to_the_new_address(client, db):
    make_user(db, "lis", "listener", email="old@example.com")
    make_user(db, "other", "listener", email="taken@example.com")
    login(client, "lis")
    assert client.post("/api/me/email/request", json={"email": "taken@example.com"}).status_code == 409
    assert client.post("/api/me/email/request", json={"email": "New@Example.com"}).status_code == 202
    assert mailer.sent_messages[-1]["To"] == "new@example.com"
    code = code_in_last_email()
    wrong = client.post("/api/me/email/confirm", json={"email": "new@example.com", "code": "000000"})
    assert wrong.status_code == 400  # never 401: that would sign the app out
    done = client.post("/api/me/email/confirm", json={"email": "new@example.com", "code": code})
    assert done.json()["email"] == "new@example.com"
    assert mailer.sent_messages[-1]["To"] == "old@example.com"  # the old address hears about it


def test_without_email_a_new_address_is_saved_as_given(client, db, monkeypatch):
    monkeypatch.setattr(get_settings(), "email_enabled", False)
    make_user(db, "lis", "listener")
    login(client, "lis")
    assert client.get("/api/me/profile").json()["emailCodes"] is False
    body = client.post("/api/me/email/request", json={"email": "Lis@Example.com"}).json()
    assert body["codeSent"] is False and body["profile"]["email"] == "lis@example.com"
    assert not mailer.sent_messages
    assert login(client, "lis@example.com")["username"] == "lis"  # the email signs in too, with the password


def test_changing_the_password_signs_out_other_devices(client, db):
    make_user(db, "lis", "listener")
    with TestClient(app) as other_device:
        login(other_device, "lis")
        login(client, "lis")
        wrong = client.post("/api/me/password", json={"currentPassword": "nope", "newPassword": "a new password"})
        assert wrong.status_code == 400  # never 401: that would sign the app out
        short = client.post("/api/me/password", json={"currentPassword": "correct horse battery", "newPassword": "short"})
        assert short.status_code == 422
        done = client.post("/api/me/password", json={"currentPassword": "correct horse battery",
                                                     "newPassword": "a new password"})
        assert done.status_code == 200 and done.json()["hasPassword"] is True
        assert client.get("/api/session").json()["authenticated"]
        assert not other_device.get("/api/session").json()["authenticated"]
    client.post("/api/logout")
    assert client.post("/api/login", json={"username": "lis", "password": "correct horse battery"}).status_code == 401
    login(client, "lis", "a new password")


def test_an_account_without_a_password_can_set_one(client, db):
    db.add(User(email="code@example.com", role="listener", display_name="code"))
    db.commit()
    assert client.post("/api/auth/otp/request", json={"email": "code@example.com"}).status_code == 202
    client.post("/api/auth/otp/verify", json={"email": "code@example.com", "code": code_in_last_email()})
    assert client.get("/api/me/profile").json()["hasPassword"] is False
    assert client.post("/api/me/password", json={"newPassword": "first password"}).status_code == 200
    client.post("/api/logout")
    login(client, "code@example.com", "first password")


def test_editors_see_how_to_reach_a_narrator(client, db):
    narrator = make_user(db, "narr", "narrator", email="narr@example.com")
    narrator.phone, narrator.contact_preferences = "+919876543210", {"channel": "phone", "notes": "mornings"}
    db.commit()
    make_asset(db, "a" * 16, narrator=narrator)
    make_user(db, "ed", "editor")
    login(client, "ed")
    listed = client.get("/api/studio/narrators").json()["items"][0]
    assert listed["phone"] == "+919876543210" and listed["contactChannel"] == "phone"
    review = client.get(f"/api/studio/review/{'a' * 16}").json()
    assert review["narrator"]["contactNotes"] == "mornings" and review["narrator"]["email"] == "narr@example.com"


def test_editors_see_narrators_the_catalog_credits_by_name(client, db):
    narrator = make_user(db, "narr", "narrator")
    make_asset(db, "a" * 16, ready_to_publish=True, status="published", narrator_name="Vimala Mare, Leo Tolstoy", title="Pilli")
    make_asset(db, "b" * 16, narrator_name="vimala mare", title="Kaaki")  # not published yet
    make_asset(db, "c" * 16, status="rejected", narrator_name="Kusuma P")
    make_asset(db, "d" * 16, ready_to_publish=True, status="published", narrator=narrator)  # has an account: listed above
    make_user(db, "ed", "editor")
    login(client, "ed")
    listed = client.get("/api/studio/narrators").json()
    assert [n["name"] for n in listed["items"]] == ["narr"]
    catalog = {n["name"]: n for n in listed["catalog"]}
    assert list(catalog) == ["Vimala Mare", "Leo Tolstoy", "Kusuma P"]  # most published first, then most stories
    vimala = catalog["Vimala Mare"]
    assert (vimala["published"], vimala["notPublished"], vimala["rejected"], vimala["languages"]) == (1, 1, 0, ["te-IN"])
    assert [s["title"] for s in vimala["stories"]] == ["Pilli", "Kaaki"]  # published first
    assert vimala["narration"]["count"] == 0 and catalog["Kusuma P"]["narration"] is None


def test_listeners_cannot_see_other_peoples_contact_details(client, db):
    make_user(db, "lis", "listener")
    login(client, "lis")
    assert client.get("/api/studio/narrators").status_code == 403
