"""Narrator photos and bios (P3-10), editor-narrator threads (P3-11), thank-you notes (P3-12), and rating alerts
for narrators (P3-13)."""

import io
from datetime import timedelta

from PIL import Image
from sqlalchemy import select

from app.auth import utcnow
from app.models import Household, Job, NarratorMessage, NarratorProfile, NarratorRating, Notification, Profile, RatingFlag
from app.services import ratings

from .conftest import login, make_asset, make_user, make_worker
from .test_community import family
from .test_pipeline import run_job

STORY = "b" * 16


def photo(size=(900, 600), color=(200, 120, 60)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, color).save(buffer, "PNG")
    return buffer.getvalue()


def narrator_with_story(db, name="narr", accepts_notes=False):
    narrator = make_user(db, name, "narrator")
    profile = db.get(NarratorProfile, narrator.id)
    profile.accepts_messages = accepts_notes
    db.commit()
    make_asset(db, STORY, ready_to_publish=True, status="published", audience_age_range="4-8", narrator=narrator,
               published_at=utcnow())
    return narrator


def test_a_narrator_photo_shows_only_after_an_editor_approves_it(client, db):
    narrator = narrator_with_story(db)
    login(client, "narr")
    assert client.put("/api/narrator/profile/photo", content=b"not an image",
                      headers={"Content-Type": "image/png"}).status_code == 422
    uploaded = client.put("/api/narrator/profile/photo", content=photo(), headers={"Content-Type": "image/png"}).json()
    assert uploaded["pendingPhotoUrl"] and uploaded["photoUrl"] is None
    client.post("/api/logout")

    profiles = family(client, db)
    mom = {"X-Profile-Id": str(profiles["mom"]["id"])}
    assert client.get(f"/api/narrators/{narrator.id}", headers=mom).json()["photoUrl"] is None
    client.post("/api/logout")

    make_user(db, "ed", "editor")
    login(client, "ed")
    listed = next(n for n in client.get("/api/studio/narrators").json()["items"] if n["userId"] == narrator.id)
    assert listed["pendingPhotoUrl"]
    assert client.post(f"/api/studio/narrators/{narrator.id}/photo", json={"approve": True}).json()["photoUrl"]
    db.expire_all()
    saved = db.get(NarratorProfile, narrator.id)
    assert saved.photo_pending_key is None and saved.photo_key.endswith(".jpg")
    stored = Image.open(io.BytesIO(client.get(listed["pendingPhotoUrl"]).content))
    assert stored.size == (512, 512)  # cropped square and shrunk
    client.post("/api/logout")

    login(client, "mom")
    assert client.get(f"/api/narrators/{narrator.id}", headers=mom).json()["photoUrl"]
    tile = next(n for n in client.get("/api/narrators", headers=mom).json()["items"] if n["id"] == narrator.id)
    assert tile["photoUrl"]
    assert db.scalars(select(Notification).where(Notification.user_id == narrator.id,
                                                 Notification.kind == "photo-approved")).first()


def test_editors_give_name_only_narrators_a_bio_and_photo(client, db):
    make_asset(db, STORY, ready_to_publish=True, status="published", audience_age_range="4-8", narrator_name="Vimala Mare")
    make_user(db, "ed", "editor")
    login(client, "ed")
    assert client.post("/api/studio/narrators/credited", json={"name": "Nobody", "biography": "x"}).status_code == 404
    assert client.post("/api/studio/narrators/credited",
                       json={"name": "vimala mare", "biography": "Told stories on the radio."}).status_code == 200
    assert client.put("/api/studio/narrators/credited/photo?name=Vimala%20Mare", content=photo(),
                      headers={"Content-Type": "image/png"}).json()["photoUrl"]
    catalog = client.get("/api/studio/narrators").json()["catalog"]
    assert catalog[0]["biography"] == "Told stories on the radio." and catalog[0]["photoUrl"]
    client.post("/api/logout")

    profiles = family(client, db)
    mom = {"X-Profile-Id": str(profiles["mom"]["id"])}
    page = client.get("/api/narrators/named/Vimala%20Mare", headers=mom).json()
    assert page["biography"] == "Told stories on the radio." and page["photoUrl"]


def test_editors_and_narrators_talk_on_a_submission(client, db):
    narrator = make_user(db, "narr", "narrator")
    asset = make_asset(db, STORY, narrator=narrator)
    asset.pipeline_stage = "ready"
    db.commit()
    make_user(db, "ed", "editor")
    login(client, "ed")
    posted = client.post(f"/api/studio/review/{STORY}/messages", json={"text": "Is the ending cut short?"})
    assert posted.status_code == 201 and posted.json()["items"][0]["role"] == "editor"
    client.post("/api/logout")

    login(client, "narr")
    assert db.scalars(select(Notification).where(Notification.user_id == narrator.id,
                                                 Notification.kind == "editor-message")).first()
    thread = client.get(f"/api/narrator/submissions/{STORY}/messages").json()["items"]
    assert thread[0]["author"] == "KathaChepta" and thread[0]["text"] == "Is the ending cut short?"
    client.post(f"/api/narrator/submissions/{STORY}/messages", json={"text": "Yes, I'll record it again."})
    make_user(db, "other", "narrator")
    client.post("/api/logout")
    login(client, "other")  # only the submission's narrator sees the thread
    assert client.get(f"/api/narrator/submissions/{STORY}/messages").status_code == 404
    client.post("/api/logout")

    login(client, "ed")
    queued = next(item for item in client.get("/api/studio/queue?view=review").json()["items"] if item["id"] == STORY)
    assert queued["unreadMessages"] == 1
    thread = client.get(f"/api/studio/review/{STORY}/messages").json()["items"]
    assert [m["role"] for m in thread] == ["editor", "narrator"] and thread[1]["author"] == "narr"
    assert next(i for i in client.get("/api/studio/queue?view=review").json()["items"] if i["id"] == STORY)["unreadMessages"] == 0
    changes = client.post(f"/api/studio/review/{STORY}/request-changes",
                          json={"reasons": ["incomplete"], "note": "Please re-record the last minute."})
    assert changes.status_code == 200, changes.text
    assert client.get(f"/api/studio/review/{STORY}/messages").json()["items"][-1]["text"] == "Please re-record the last minute."


def test_families_send_thank_you_notes_that_are_checked_first(client, db):
    narrator = narrator_with_story(db)
    token = make_worker(db)
    profiles = family(client, db)
    mom = {"X-Profile-Id": str(profiles["mom"]["id"])}
    anu = {"X-Profile-Id": str(profiles["Anu"]["id"])}
    note = {"text": "Our daughter loves your crow story!", "storyId": STORY}
    assert client.get(f"/api/narrators/{narrator.id}", headers=mom).json()["notes"]["accepting"] is False
    assert client.post(f"/api/narrators/{narrator.id}/notes", json=note, headers=mom).status_code == 422  # not opted in
    db.get(NarratorProfile, narrator.id).accepts_messages = True
    db.commit()
    assert client.post(f"/api/narrators/{narrator.id}/notes", json=note, headers=anu).status_code == 403  # children
    refused = client.post(f"/api/narrators/{narrator.id}/notes", headers=mom,
                          json={"text": "Call me on 98765 43210", "storyId": STORY})
    assert refused.status_code == 422 and "phone" in refused.json()["error"]
    sent = client.post(f"/api/narrators/{narrator.id}/notes", json=note, headers=mom)
    assert sent.status_code == 201 and sent.json()["sent"][0]["status"] == "pending"
    held = client.post(f"/api/narrators/{narrator.id}/notes", headers=mom,
                       json={"text": "Anu tells all of class 3 about you", "storyId": STORY})
    assert held.json()["sent"][0]["status"] == "held"  # a child's class: an editor decides

    # The local model's check (the review.moderate job) lets the first note through.
    lease = run_job(client, token, "review.moderate", {"verdict": "allow", "reasons": [], "note": "kind",
                                                       "model": "qwen/qwen3-8b"})
    assert lease["inputs"]["reviewText"] == note["text"]
    client.post("/api/logout")

    login(client, "narr")
    inbox = client.get("/api/narrator/notes").json()
    assert [n["text"] for n in inbox["items"]] == [note["text"]] and inbox["items"][0]["author"] == "mom"
    first = inbox["items"][0]["id"]
    assert client.post(f"/api/narrator/notes/{first}/reply", json={"text": "See www.me.com"}).status_code == 422
    replied = client.post(f"/api/narrator/notes/{first}/reply", json={"text": "Thank you, that made my day."})
    assert replied.json()["items"][0]["reply"] == "Thank you, that made my day."
    client.post("/api/logout")

    login(client, "mom")
    page = client.get(f"/api/narrators/{narrator.id}", headers=mom).json()
    assert page["notes"]["sent"][-1]["reply"] == "Thank you, that made my day."
    updates = client.get("/api/me/updates", headers=mom).json()["items"]
    assert updates[0]["kind"] == "narrator-reply"
    assert client.post(f"/api/narrators/{narrator.id}/notes", json=note, headers=mom).status_code == 201
    limited = client.post(f"/api/narrators/{narrator.id}/notes", json=note, headers=mom)
    assert limited.status_code == 422 and "3 notes a day" in limited.json()["error"]
    client.post("/api/logout")

    make_user(db, "ed", "editor")
    login(client, "ed")
    notes = client.get("/api/studio/moderation").json()["notes"]
    assert [n["text"] for n in notes] == ["Anu tells all of class 3 about you"]
    assert client.post(f"/api/studio/notes/{notes[0]['id']}", json={"decision": "reject"}).json()["status"] == "rejected"


def test_a_narrator_can_block_or_report_a_family(client, db):
    narrator = narrator_with_story(db, accepts_notes=True)
    profiles = family(client, db)
    mom = {"X-Profile-Id": str(profiles["mom"]["id"])}
    client.post(f"/api/narrators/{narrator.id}/notes", json={"text": "Lovely voice"}, headers=mom)
    pending = db.scalars(select(NarratorMessage)).one()
    assert db.scalars(select(Job).where(Job.job_type == "review.moderate")).one().payload == {"messageId": pending.id}
    pending.status = "delivered"
    db.commit()
    client.post("/api/logout")

    login(client, "narr")
    reported = client.post(f"/api/narrator/notes/{pending.id}/report").json()
    assert reported["items"] == []
    db.expire_all()
    assert db.get(NarratorMessage, pending.id).status == "held"
    db.get(NarratorMessage, pending.id).status = "delivered"
    db.commit()
    assert client.post(f"/api/narrator/notes/{pending.id}/block").json()["blockedFamilies"] == 1
    client.post("/api/logout")

    login(client, "mom")
    assert client.get(f"/api/narrators/{narrator.id}", headers=mom).json()["notes"]["accepting"] is False
    assert client.post(f"/api/narrators/{narrator.id}/notes", json={"text": "Hello again"}, headers=mom).status_code == 422


def test_a_burst_of_narrator_ratings_is_held_for_an_editor(client, db):
    narrator = narrator_with_story(db)
    key = f"id:{narrator.id}"
    for index in range(10):
        household = Household(owner_user_id=make_user(db, f"raid{index}", "parent").id)
        db.add(household)
        db.flush()
        profile = Profile(household_id=household.id, name="x")
        db.add(profile)
        db.flush()
        db.add(NarratorRating(profile_id=profile.id, household_id=household.id, narrator_key=key, rating=1,
                              weight=0.2, created_at=utcnow() - timedelta(hours=index)))
    db.commit()
    flag = ratings.check_narrator_spike(db, key)
    db.commit()
    assert flag is not None and flag.narrator_key == key and flag.details["newAccounts"] == 10
    assert ratings.narrator_scores(db, [narrator.id])[narrator.id]["count"] == 0  # held out of the score

    make_user(db, "ed", "editor")
    login(client, "ed")
    alerts = client.get("/api/studio/moderation").json()["narratorFlags"]
    assert alerts[0]["narrator"] == "narr"
    assert client.post(f"/api/studio/rating-flags/{alerts[0]['id']}", json={"decision": "confirm"}).json()["status"] == "confirmed"
    db.expire_all()
    assert db.query(NarratorRating).filter_by(excluded=True).count() == 10
    assert db.get(RatingFlag, alerts[0]["id"]).resolved_by == "ed"
