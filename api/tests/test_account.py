"""Contact details on every kind of account."""

import re

from app import mailer
from app.models import Household
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


def test_listeners_cannot_see_other_peoples_contact_details(client, db):
    make_user(db, "lis", "listener")
    login(client, "lis")
    assert client.get("/api/studio/narrators").status_code == 403
