"""Following narrators the catalog credits by name only, and series, for opt-in updates (P3-09)."""

from app.models import Notification
from app.routers.editorial import mark_published

from .conftest import make_asset
from .test_community import family

STORY = "a" * 16


def updates(client, headers):
    return client.get("/api/me/updates", headers=headers).json()


def test_follow_a_narrator_credited_by_name_and_hear_about_new_stories(client, db):
    make_asset(db, STORY, ready_to_publish=True, status="published", narrator_name="Vimala Mare, Leo Tolstoy")
    profiles = family(client, db)
    mom = {"X-Profile-Id": str(profiles["mom"]["id"])}
    kid = {"X-Profile-Id": str(profiles["Anu"]["id"])}
    page = client.get("/api/narrators/named/vimala  mare", headers=mom).json()
    assert page["canFollow"] and not page["following"] and page["followers"] == 0
    assert not client.get("/api/narrators/named/Vimala Mare", headers=kid).json()["canFollow"]
    assert client.post("/api/narrators/named/Vimala Mare/follow", json={"following": True}, headers=kid).status_code == 403
    assert client.post("/api/narrators/named/Nobody/follow", json={"following": True}, headers=mom).status_code == 404

    assert client.post("/api/narrators/named/VIMALA MARE/follow", json={"following": True}, headers=mom).json() == \
        {"following": True}
    page = client.get("/api/narrators/named/Vimala Mare", headers=mom).json()
    assert page["following"] and page["followers"] == 1
    mine = updates(client, mom)
    assert mine["settings"] == {"followed": True, "series": False}  # following turned these updates on
    assert mine["following"] == [{"kind": "narrator", "key": "name:vimala mare", "name": "Vimala Mare"}]

    other = make_asset(db, "b" * 16, ready_to_publish=True, narrator_name="Someone Else")
    theirs = make_asset(db, "c" * 16, ready_to_publish=True, narrator_name="Sahiti Sagar & vimala mare")
    for asset in (other, theirs):
        mark_published(db, asset, "ed")
    db.commit()
    assert [(u["kind"], u["story"]["id"]) for u in updates(client, mom)["items"]] == [("new-from-followed", "c" * 16)]

    assert client.post("/api/me/follows/remove", json={"kind": "narrators", "key": "name:vimala mare"},
                       headers=mom).status_code == 200
    assert updates(client, mom)["following"] == []
    assert not client.get("/api/narrators/named/Vimala Mare", headers=mom).json()["following"]


def test_follow_a_series_for_its_next_chapters_before_listening(client, db):
    make_asset(db, STORY, ready_to_publish=True, status="published", album=" Panchatantra ", narrator_name="Vimala")
    make_asset(db, "s" * 16, ready_to_publish=True, status="published")  # not in a series
    profiles = family(client, db)
    mom = {"X-Profile-Id": str(profiles["mom"]["id"])}
    kid = {"X-Profile-Id": str(profiles["Anu"]["id"])}
    assert client.get(f"/api/stories/{STORY}/community", headers=mom).json()["series"] == \
        {"title": "Panchatantra", "following": False}
    assert client.get(f"/api/stories/{'s' * 16}/community", headers=mom).json()["series"] is None
    assert client.post(f"/api/stories/{'s' * 16}/series/follow", json={"following": True}, headers=mom).status_code == 404
    assert client.post(f"/api/stories/{STORY}/series/follow", json={"following": True}, headers=kid).status_code == 403

    assert client.post(f"/api/stories/{STORY}/series/follow", json={"following": True}, headers=mom).json()["following"]
    assert client.get(f"/api/stories/{STORY}/community", headers=mom).json()["series"]["following"]
    mine = updates(client, mom)
    assert mine["settings"] == {"followed": False, "series": True}
    assert mine["following"] == [{"kind": "series", "key": "album:panchatantra", "name": "Panchatantra"}]

    chapter = make_asset(db, "b" * 16, ready_to_publish=True, album=" Panchatantra ", narrator_name="Vimala")
    mark_published(db, chapter, "ed")
    db.commit()
    assert [(u["kind"], u["story"]["id"]) for u in updates(client, mom)["items"]] == [("series-next", "b" * 16)]
    assert db.query(Notification).count() == 1  # nobody else follows or listened

    client.post("/api/me/follows/remove", json={"kind": "series", "key": "album:panchatantra"}, headers=mom)
    assert updates(client, mom)["following"] == []
