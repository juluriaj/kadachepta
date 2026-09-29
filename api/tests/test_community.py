"""Phase 3: ratings and their integrity, reviews and moderation, narrator pages, search, recommendations,
collections, conversation starters, and opt-in notifications."""

from datetime import timedelta

from sqlalchemy import select

from app.auth import utcnow
from app.models import (
    AudioAsset, Household, Notification, Profile, RatingFlag, Review, StoryEmbedding, StoryRating,
)
from app.services import ratings

from .conftest import login, make_asset, make_user, make_worker
from .test_household import onboard, parent
from .test_pipeline import run_job

STORY = "a" * 16


def listen(client, profile_id, asset_id=STORY, seconds=200, completed=True):
    headers = {"X-Profile-Id": str(profile_id)}
    for _ in range(0, seconds, 100):
        client.post("/api/me/listening", json={"assetId": asset_id, "seconds": 100, "position": 250,
                                               "started": True, "completed": completed}, headers=headers)
    return headers


def family(client, db, name="mom"):
    parent(client, db, name)
    return onboard(client)


def test_only_listeners_rate_and_children_react(client, db):
    narrator = make_user(db, "narr", "narrator")
    make_asset(db, STORY, ready_to_publish=True, status="published", audience_age_range="4-8",
               narrator=narrator)
    profiles = family(client, db)
    mom = {"X-Profile-Id": str(profiles["mom"]["id"])}
    assert client.post(f"/api/stories/{STORY}/rating", json={"story": 5}, headers=mom).status_code == 409
    anu = listen(client, profiles["Anu"]["id"])  # the child listened: the parent may rate for her
    assert client.post(f"/api/stories/{STORY}/rating", json={"story": 5}, headers=anu).status_code == 422
    assert client.post(f"/api/stories/{STORY}/rating", json={"reaction": "love"}, headers=anu).status_code == 200
    rated = client.post(f"/api/stories/{STORY}/rating", json={"story": 5, "narration": 4}, headers=mom)
    assert rated.status_code == 200, rated.text
    assert rated.json()["mine"] == {"story": 5, "narration": 4, "reaction": None}
    client.post(f"/api/stories/{STORY}/rating", json={"story": 3}, headers=mom)  # changes, not a second rating
    assert db.query(StoryRating).count() == 2
    summary = client.get(f"/api/stories/{STORY}/community", headers=mom).json()
    assert summary["story"]["count"] == 1 and summary["story"]["score"] is None  # too few to show
    assert summary["reactions"] == {"love": 1}
    child_view = client.get(f"/api/stories/{STORY}/community", headers=anu).json()
    assert "reviews" not in child_view and "story" not in child_view

    client.post("/api/logout")
    login(client, "narr")  # narrators can't rate their own work
    own = client.get("/api/household").json()["profiles"][0]["id"]
    listen(client, own)
    blocked = client.post(f"/api/stories/{STORY}/rating", json={"story": 5}, headers={"X-Profile-Id": str(own)})
    assert blocked.status_code == 403


def test_bayesian_scores_and_trust_weights(db):
    asset = make_asset(db, STORY, ready_to_publish=True, status="published")
    for index in range(4):
        household = Household(owner_user_id=make_user(db, f"u{index}", "parent").id)
        db.add(household)
        db.flush()
        profile = Profile(household_id=household.id, name=f"p{index}")
        db.add(profile)
        db.flush()
        db.add(StoryRating(profile_id=profile.id, household_id=household.id, audio_asset_id=asset.id, story_rating=5,
                           weight=1.0 if index < 3 else 0.2))
    db.commit()
    score = ratings.story_scores(db, [asset.id])[asset.id]["story"]
    # (5 x 4.0 prior + 3.2 x 5) / (5 + 3.2): four perfect ratings move the score up, not to 5.
    assert score["score"] == round((5 * 4.0 + 3.2 * 5) / 8.2, 2) and score["weight"] == 3.2


def test_a_burst_of_new_accounts_is_held_out_until_an_editor_decides(client, db):
    asset = make_asset(db, STORY, ready_to_publish=True, status="published")
    for index in range(10):
        household = Household(owner_user_id=make_user(db, f"raid{index}", "parent").id)
        db.add(household)
        db.flush()
        profile = Profile(household_id=household.id, name="x")
        db.add(profile)
        db.flush()
        db.add(StoryRating(profile_id=profile.id, household_id=household.id, audio_asset_id=asset.id, story_rating=1,
                           weight=0.2, created_at=utcnow() - timedelta(hours=index)))
    db.commit()
    flag = ratings.check_spike(db, asset.id)
    db.commit()
    assert flag is not None and flag.details["recent"] == 10 and flag.details["newAccounts"] == 10
    assert ratings.story_scores(db, [asset.id])[asset.id]["story"]["count"] == 0  # held out

    make_user(db, "ed", "editor")
    login(client, "ed")
    alerts = client.get("/api/studio/moderation").json()["ratingFlags"]
    assert [a["story"]["id"] for a in alerts] == [asset.id]
    assert client.post(f"/api/studio/rating-flags/{alerts[0]['id']}", json={"decision": "confirm"}).json()["status"] == "confirmed"
    db.expire_all()
    assert db.query(StoryRating).filter_by(excluded=True).count() == 10
    assert db.get(RatingFlag, alerts[0]["id"]).resolved_by == "ed"


def test_reviews_are_checked_reported_and_answered(client, db):
    narrator = make_user(db, "narr", "narrator")
    make_asset(db, STORY, ready_to_publish=True, status="published", audience_age_range="4-8",
               narrator=narrator)
    token = make_worker(db)
    profiles = family(client, db)
    mom = listen(client, profiles["mom"]["id"])
    held = client.post(f"/api/stories/{STORY}/review", json={"text": "Call me on 98765 43210"}, headers=mom).json()
    assert held["myReview"]["status"] == "held"
    school = client.post(f"/api/stories/{STORY}/review", json={"text": "Arjun from Delhi Public School class 2 loved it"},
                         headers=mom).json()
    assert school["myReview"]["status"] == "held"
    written = client.post(f"/api/stories/{STORY}/review", json={"text": "My daughter loved the crow!"}, headers=mom)
    assert written.json()["myReview"]["status"] == "pending"
    lease = run_job(client, token, "review.moderate", {"verdict": "allow", "reasons": [], "note": "", "model": "m"})
    assert lease["inputs"]["reviewText"] == "My daughter loved the crow!"
    anu = {"X-Profile-Id": str(profiles["Anu"]["id"])}
    assert client.post(f"/api/stories/{STORY}/review", json={"text": "fun"}, headers=anu).status_code == 403
    review_id = db.scalars(select(Review.id)).one()

    client.post("/api/logout")
    others = [family(client, db, "dad")["dad"]["id"]]
    visible = client.get(f"/api/stories/{STORY}/community", headers={"X-Profile-Id": str(others[0])}).json()
    assert [r["text"] for r in visible["reviews"]] == ["My daughter loved the crow!"] and visible["reviews"][0]["author"] == "mom"
    client.post(f"/api/reviews/{review_id}/report", json={"reason": "unkind"}, headers={"X-Profile-Id": str(others[0])})
    client.post("/api/logout")
    aunt = family(client, db, "aunt")["aunt"]["id"]
    client.post(f"/api/reviews/{review_id}/report", json={"reason": "spam"}, headers={"X-Profile-Id": str(aunt)})
    db.expire_all()
    assert db.get(Review, review_id).status == "held"  # two households reported it

    client.post("/api/logout")
    make_user(db, "ed", "editor")
    login(client, "ed")
    queue = client.get("/api/studio/moderation").json()["reviews"]
    assert queue[0]["reports"] == 2 and set(queue[0]["reportReasons"]) == {"unkind", "spam"}
    client.post(f"/api/studio/reviews/{review_id}", json={"decision": "publish"})

    client.post("/api/logout")
    login(client, "narr")
    mine = client.get("/api/narrator/reviews").json()["items"]
    assert [item["text"] for item in mine] == ["My daughter loved the crow!"]
    assert client.post(f"/api/narrator/reviews/{review_id}/reply", json={"text": "Email me at a@b.co"}).status_code == 422
    assert client.post(f"/api/narrator/reviews/{review_id}/reply", json={"text": "Thank you!"}).json()["reply"] == "Thank you!"


def test_search_finds_telugu_titles_typed_in_english_letters(client, db):
    make_asset(db, STORY, ready_to_publish=True, status="published", title="కాకి హంస కాగలదా")
    make_asset(db, "b" * 16, ready_to_publish=True, status="published", title="Kothi Chesina Mosam")
    profiles = family(client, db)
    mom = {"X-Profile-Id": str(profiles["mom"]["id"])}

    def found(query):
        response = client.get("/api/search", params={"q": query}, headers=mom)
        assert response.status_code == 200, response.text
        return [item["title"] for item in response.json()["items"]]

    assert found("kaki hamsa") == ["కాకి హంస కాగలదా"]
    assert found("Kaaki") == ["కాకి హంస కాగలదా"]
    assert found("crow") == ["కాకి హంస కాగలదా"]  # English synonym
    assert found("కోతి") == ["Kothi Chesina Mosam"]  # Telugu script finds the romanized title
    assert found("koti mosam") == ["Kothi Chesina Mosam"]
    assert found("elephant") == []


def test_follow_and_opt_in_notifications_on_publish(client, db):
    narrator = make_user(db, "narr", "narrator")
    make_asset(db, STORY, ready_to_publish=True, status="published", narrator=narrator, album="Panchatantra")
    profiles = family(client, db)
    mom = {"X-Profile-Id": str(profiles["mom"]["id"])}
    page = client.get(f"/api/narrators/{narrator.id}", headers=mom).json()
    assert page["name"] == "narr" and [s["id"] for s in page["stories"]] == [STORY] and page["canFollow"]
    assert client.post(f"/api/narrators/{narrator.id}/follow", json={"following": True}, headers=mom).json()["following"]
    kid = {"X-Profile-Id": str(profiles["Anu"]["id"])}
    assert client.post(f"/api/narrators/{narrator.id}/follow", json={"following": True}, headers=kid).status_code == 403
    listen(client, profiles["mom"]["id"])

    from app.routers.editorial import mark_published
    second = make_asset(db, "b" * 16, ready_to_publish=True, narrator=narrator, album="Panchatantra")
    mark_published(db, second, "ed")
    db.commit()
    assert db.query(Notification).filter(Notification.kind.in_(("new-from-followed", "series-next"))).count() == 0  # opt-in

    assert client.post("/api/me/notification-settings", json={"followed": True, "series": True}, headers=mom).json() == \
        {"followed": True, "series": True}
    third = make_asset(db, "c" * 16, ready_to_publish=True, narrator=narrator, album="Panchatantra")
    mark_published(db, third, "ed")
    db.commit()
    updates = client.get("/api/me/updates", headers=mom).json()
    assert [(u["kind"], u["story"]["id"]) for u in updates["items"]] == [("new-from-followed", "c" * 16)]
    assert client.get("/api/me/updates", headers=kid).json()["items"] == []


def test_recommendations_blend_meaning_and_listening(client, db):
    for asset_id, vector in (("a" * 16, [1, 0, 0]), ("b" * 16, [0.9, 0.1, 0]), ("c" * 16, [0, 0, 1])):
        make_asset(db, asset_id, ready_to_publish=True, status="published")
        db.add(StoryEmbedding(audio_asset_id=asset_id, model="m", source_hash="h", embedding=vector))
    make_asset(db, "d" * 16, ready_to_publish=True, status="published")
    db.commit()
    profiles = family(client, db)
    mom = listen(client, profiles["mom"]["id"], "a" * 16)
    detail = client.get(f"/api/stories/{'a' * 16}", headers=mom).json()
    assert [s["id"] for s in detail["moreLikeThis"]][0] == "b" * 16
    listen(client, profiles["mom"]["id"], "c" * 16)
    home = client.get("/api/home", headers=mom).json()
    because = next((s for s in home["shelves"] if s["id"] == "because"), None)
    assert because is None  # only one unheard neighbour: not enough for a shelf


def test_collections_show_in_season_and_prompts_are_for_parents(client, db):
    make_asset(db, STORY, ready_to_publish=True, status="published", audience_age_range="4-8")
    make_user(db, "ed", "editor")
    login(client, "ed")
    today = utcnow().date()
    body = {"kind": "festival", "titles": {"en-IN": "Diwali stories", "te-IN": "దీపావళి కథలు"}, "published": True,
            "startsOn": (today - timedelta(days=1)).isoformat(), "endsOn": (today + timedelta(days=5)).isoformat(),
            "assetIds": [STORY, "missing"]}
    created = client.post("/api/studio/collections", json=body)
    assert created.status_code == 201, created.text
    past = {**body, "startsOn": (today - timedelta(days=30)).isoformat(), "endsOn": (today - timedelta(days=20)).isoformat()}
    client.post("/api/studio/collections", json=past)
    saved = client.post(f"/api/studio/prompts/{STORY}", json={"texts": {"en-IN": ["What would you do?", " "]}})
    assert saved.json()["prompts"]["texts"] == {"en-IN": ["What would you do?"]}
    client.post("/api/logout")

    profiles = family(client, db)
    shelves = client.get("/api/home", headers={"X-Profile-Id": str(profiles["mom"]["id"])}).json()["shelves"]
    festival = [s for s in shelves if s["id"].startswith("collection-")]
    assert len(festival) == 1 and festival[0]["collection"]["titles"]["te-IN"] == "దీపావళి కథలు"
    assert client.get(f"/api/stories/{STORY}", headers={"X-Profile-Id": str(profiles["mom"]["id"])}).json()["prompts"] == \
        {"en-IN": ["What would you do?"]}
    assert client.get(f"/api/stories/{STORY}", headers={"X-Profile-Id": str(profiles["Anu"]["id"])}).json()["prompts"] is None


def test_embed_and_prompt_jobs_store_their_results(client, db):
    asset = make_asset(db, STORY, ready_to_publish=True, status="published", moral_takeaway="Be kind to everyone.")
    token = make_worker(db)
    make_user(db, "ed", "editor")
    login(client, "ed")
    assert client.post("/api/studio/community/refresh").json()["queued"] == {"embed": 1, "prompts": 1}
    from app.services import recommend
    expected = recommend.source_hash("text-embedding-nomic-embed-text-v1.5",
                                     recommend.embedding_text(db.get(AudioAsset, STORY), None))
    lease = run_job(client, token, "embed", {"vector": [0.1, 0.2], "model": "text-embedding-nomic-embed-text-v1.5",
                                             "sourceHash": expected})
    assert "Be kind" in lease["inputs"]["text"] and lease["inputs"]["sourceHash"] == expected
    run_job(client, token, "prompts", {"texts": {"en-IN": ["What if the crow could talk?"]}, "model": "qwen"})
    db.expire_all()
    asset = db.get(AudioAsset, STORY)
    assert db.get(StoryEmbedding, STORY).embedding == [0.1, 0.2]
    assert asset.imagination_prompts["status"] == "draft"  # waits for an editor
    assert client.post("/api/studio/community/refresh").json()["queued"] == {}  # nothing new to do
