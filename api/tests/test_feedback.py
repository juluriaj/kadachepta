"""Feedback from the app, the studio inbox, and admin password resets."""

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.main import app
from app.models import AuditLog, Feedback

from .conftest import login, make_user


def test_anyone_signed_in_can_send_feedback_and_editors_close_it(client, db):
    make_user(db, "lis", "listener", email="lis@example.com", phone="+919876543210")
    assert client.post("/api/feedback", json={"message": "The story stops at 3 minutes"}).status_code == 401
    login(client, "lis")
    assert client.post("/api/feedback", json={"message": "  "}).status_code == 422
    sent = client.post("/api/feedback", json={"message": "The story stops at 3 minutes", "page": "/story/abc",
                                              "platform": "android"})
    assert sent.status_code == 201
    assert client.get("/api/studio/feedback").status_code == 403  # listeners don't see the inbox
    client.post("/api/logout")

    make_user(db, "ed", "editor")
    login(client, "ed")
    inbox = client.get("/api/studio/feedback").json()
    assert inbox["counts"] == {"new": 1, "done": 0}
    item = inbox["items"][0]
    assert item["message"] == "The story stops at 3 minutes" and item["page"] == "/story/abc"
    assert item["from"]["username"] == "lis" and item["from"]["phone"] == "+919876543210"
    assert client.post(f"/api/studio/feedback/{item['id']}", json={"done": True}).json()["status"] == "done"
    assert client.get("/api/studio/feedback").json()["items"] == []
    assert client.get("/api/studio/feedback?status=done").json()["items"][0]["id"] == item["id"]


def test_feedback_is_rate_limited(client, db):
    make_user(db, "lis", "listener")
    login(client, "lis")
    codes = [client.post("/api/feedback", json={"message": f"note {i}"}).status_code for i in range(11)]
    assert codes[:10] == [201] * 10 and codes[10] == 429


def test_deleting_an_account_deletes_its_feedback(client, db):
    make_user(db, "mom", "parent")
    login(client, "mom")
    client.post("/api/feedback", json={"message": "Please add more Hindi stories"})
    assert client.post("/api/me/delete", json={"confirm": "DELETE"}).status_code == 200
    assert db.scalars(select(Feedback)).first() is None


def test_admin_finds_an_account_and_resets_its_password(client, db):
    user = make_user(db, "sita", "listener", email="sita@example.com")
    with TestClient(app) as phone:
        login(phone, "sita")
        make_user(db, "ed", "editor")
        login(client, "ed")
        assert client.get("/api/admin/users?q=sita").status_code == 403  # editors can't
        client.post("/api/logout")

        admin = make_user(db, "boss", "admin")
        login(client, "boss")
        assert client.get("/api/admin/users?q=s").json()["items"] == []  # too short to search
        found = client.get("/api/admin/users?q=SITA@").json()["items"]
        assert [row["userId"] for row in found] == [user.id] and found[0]["hasPassword"] is True
        assert client.post(f"/api/admin/users/{admin.id}/password").status_code == 409  # not your own
        reset = client.post(f"/api/admin/users/{user.id}/password").json()
        assert len(reset["password"]) >= 12
        assert not phone.get("/api/session").json()["authenticated"]  # signed out everywhere
    assert client.post("/api/logout").status_code == 200
    assert client.post("/api/login", json={"username": "sita", "password": "correct horse battery"}).status_code == 401
    login(client, "sita@example.com", reset["password"])
    entry = db.scalars(select(AuditLog).where(AuditLog.action == "password.reset-by-admin")).one()
    assert entry.actor_user_id == admin.id and entry.detail["account"] == user.id
