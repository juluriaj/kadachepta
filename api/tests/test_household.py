from sqlalchemy import select

from app.models import TeaserDraft, User

from .conftest import login, make_asset, make_user


def parent(client, db, name="mom"):
    make_user(db, name, "parent")
    return login(client, name)


def onboard(client, children=({"name": "Anu", "ageBand": "3-5"}, {"name": "Ravi", "ageBand": "9-12"}), **extra):
    body = {"listeningLanguages": ["te"], "uiLanguage": "en", "children": list(children),
            "moments": ["bedtime", "drive"], **extra}
    response = client.post("/api/household/onboarding", json=body)
    assert response.status_code == 200, response.text
    return {p["name"]: p for p in response.json()["profiles"]}


def test_household_is_created_with_an_adult_profile(client, db):
    parent(client, db)
    data = client.get("/api/household").json()
    assert data["household"]["onboarded"] is False
    assert [(p["name"], p["kind"]) for p in data["profiles"]] == [("mom", "adult")]


def test_onboarding_creates_children_and_preferences(client, db):
    parent(client, db)
    profiles = onboard(client)
    assert profiles["Anu"]["kind"] == "child" and profiles["Anu"]["ageBand"] == "3-5"
    assert profiles["mom"]["listeningLanguages"] == ["te-IN"]
    data = client.get("/api/household").json()
    assert data["household"]["onboarded"] and data["household"]["moments"] == ["bedtime", "drive"]
    # Re-running onboarding doesn't duplicate children.
    assert len(onboard(client)) == 3


def test_child_profiles_only_see_age_appropriate_stories(client, db):
    make_asset(db, "a" * 16, ready_to_publish=True, status="published", title="Little", audience_age_range="4-8")
    make_asset(db, "b" * 16, ready_to_publish=True, status="published", title="Big")
    db.get_bind()
    big = db.execute(select(TeaserDraft)).scalars().all()
    assert big
    from app.models import AudioAsset
    asset = db.get(AudioAsset, "b" * 16)
    asset.audience_age_range = "10-14"
    scary = make_asset(db, "c" * 16, ready_to_publish=True, status="published", title="Scary")
    scary.content_warnings = ["fear"]
    unknown = make_asset(db, "d" * 16, ready_to_publish=True, status="published", title="Unknown")
    unknown.audience_age_range = "someday"
    db.commit()
    parent(client, db)
    profiles = onboard(client)

    def titles(profile_id):
        return {i["title"] for i in client.get("/api/catalog", headers={"X-Profile-Id": str(profile_id)}).json()["items"]}

    assert titles(profiles["mom"]["id"]) == {"Little", "Big", "Scary", "Unknown"}
    assert titles(profiles["Anu"]["id"]) == {"Little"}          # no 10+, no warnings, no unknown ages
    assert titles(profiles["Ravi"]["id"]) == {"Little", "Big", "Scary"}
    hidden = client.get(f"/api/stories/{'b' * 16}", headers={"X-Profile-Id": str(profiles["Anu"]["id"])})
    assert hidden.status_code == 404


def test_profile_header_must_belong_to_the_household(client, db):
    parent(client, db, "mom")
    onboard(client)
    client.post("/api/logout")
    parent(client, db, "dad")
    other = client.get("/api/household").json()["profiles"][0]["id"]
    client.post("/api/logout")
    login(client, "mom")
    assert client.get("/api/home", headers={"X-Profile-Id": str(other)}).status_code == 404


def test_favorites_and_progress_are_per_profile(client, db):
    make_asset(db, "a" * 16, ready_to_publish=True, status="published", audience_age_range="4-8")
    parent(client, db)
    profiles = onboard(client)
    kid = {"X-Profile-Id": str(profiles["Anu"]["id"])}
    client.post("/api/me/favorites", json={"assetId": "a" * 16}, headers=kid)
    client.post("/api/me/listening", json={"assetId": "a" * 16, "seconds": 60, "screenOffSeconds": 45,
                                           "position": 90, "started": True, "day": "2026-09-23"}, headers=kid)
    assert client.get("/api/me/favorites").json()["ids"] == []
    assert client.get("/api/me/favorites", headers=kid).json()["ids"] == ["a" * 16]
    stats = client.get("/api/me/stats?today=2026-09-23", headers=kid).json()
    assert stats["weekSeconds"] == 60 and stats["weekScreenOffShare"] == 0.75
    assert client.get("/api/me/progress", headers=kid).json()["items"]["a" * 16]["position"] == 90
    home = client.get("/api/home", headers=kid).json()
    assert home["shelves"][0]["id"] == "continue" and home["shelves"][0]["items"][0]["progress"]["position"] == 90


def test_parent_pin_guards_profile_changes_and_family_stats(client, db):
    parent(client, db)
    onboard(client)
    assert client.post("/api/household/pin", json={"pin": "12a4"}).status_code == 400
    assert client.post("/api/household/pin", json={"pin": "2468"}).json()["hasParentPin"] is True
    blocked = client.post("/api/household/profiles", json={"name": "Kiran", "ageBand": "6-8"})
    assert blocked.status_code == 403 and blocked.json()["code"] == "parental-pin-required"
    assert client.get("/api/household/stats").status_code == 403
    assert client.post("/api/household/pin/verify", json={"pin": "0000"}).json()["ok"] is False
    assert client.post("/api/household/pin/verify", json={"pin": "2468"}).json()["ok"] is True
    pin = {"X-Parent-Pin": "2468"}
    assert client.post("/api/household/profiles", json={"name": "Kiran", "ageBand": "6-8"}, headers=pin).status_code == 201
    family = client.get("/api/household/stats?today=2026-09-23", headers=pin).json()["profiles"]
    assert {p["name"] for p in family} == {"mom", "Anu", "Ravi", "Kiran"}
    # Changing the PIN needs the current one.
    assert client.post("/api/household/pin", json={"pin": "1357"}).status_code == 403
    assert client.post("/api/household/pin", json={"pin": "1357", "currentPin": "2468"}).status_code == 200


def test_last_adult_profile_cannot_be_removed(client, db):
    parent(client, db)
    profiles = onboard(client)
    response = client.delete(f"/api/household/profiles/{profiles['mom']['id']}")
    assert response.status_code == 409
    assert client.delete(f"/api/household/profiles/{profiles['Anu']['id']}").status_code == 200
    assert "Anu" not in {p["name"] for p in client.get("/api/household").json()["profiles"]}


def test_teaser_follows_profile_language(client, db):
    make_asset(db, "a" * 16, ready_to_publish=True, status="published", audience_age_range="All ages")
    teaser = db.scalars(select(TeaserDraft)).one()
    teaser.alternates = {"en-IN": {"short": "A short tale", "long": "A good story"}}
    db.commit()
    parent(client, db)
    client.post("/api/household/onboarding", json={"listeningLanguages": ["en-IN", "te-IN"], "children": []})
    item = client.get("/api/catalog").json()["items"][0]
    assert item["teaser"] == {"language": "en-IN", "short": "A short tale", "long": "A good story"}


def test_story_detail_lists_next_episodes(client, db):
    for number, asset_id in ((1, "e1"), (2, "e2"), (3, "e3")):
        make_asset(db, asset_id * 8, ready_to_publish=True, status="published", album="Series",
                   episode_number=str(number), title=f"Part {number}", audience_age_range="All ages")
    parent(client, db)
    detail = client.get(f"/api/stories/{'e2' * 8}").json()
    assert [item["title"] for item in detail["upNext"]] == ["Part 3"]


def test_export_and_delete_account(client, db):
    make_asset(db, "a" * 16, ready_to_publish=True, status="published", audience_age_range="All ages")
    parent(client, db)
    client.post("/api/me/favorites", json={"assetId": "a" * 16})
    export = client.get("/api/me/export").json()
    assert export["account"]["username"] == "mom" and export["favorites"][0]["storyId"] == "a" * 16
    assert client.post("/api/me/delete", json={"confirm": "nope"}).status_code == 400
    assert client.post("/api/me/delete", json={"confirm": "DELETE"}).status_code == 200
    assert client.get("/api/session").json() == {"authenticated": False}
    assert client.post("/api/login", json={"username": "mom", "password": "correct horse battery"}).status_code == 401
    user = db.scalars(select(User)).one()
    db.refresh(user)
    assert user.email is None and user.username is None and user.disabled_at is not None


def test_staff_accounts_cannot_self_delete(client, db):
    make_user(db, "ed", "editor")
    login(client, "ed")
    assert client.post("/api/me/delete", json={"confirm": "DELETE"}).status_code == 409


def test_pin_can_be_changed_with_recently_entered_pin_header(client, db):
    parent(client, db)
    client.post("/api/household/pin", json={"pin": "2468"})
    assert client.post("/api/household/pin", json={"pin": "1357"}, headers={"X-Parent-Pin": "2468"}).status_code == 200
    assert client.post("/api/household/pin/verify", json={"pin": "1357"}).json()["ok"] is True
