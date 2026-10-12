from app.models import AudioAsset, TeaserDraft, Transcript

from .conftest import login, make_asset, make_user


def ready_story(db, asset_id: str, **draft_fields):
    asset = make_asset(db, asset_id, ready_to_publish=True, collection="Neeti Kathalu", pipeline_stage="ready",
                       title="Garvam")
    draft = db.query(TeaserDraft).filter_by(audio_asset_id=asset_id).one()
    draft.status, draft.age_suggestion = "needs-review", "4-8"
    draft.alternates = {"en-IN": {"short": "A proud crow.", "long": "A proud crow learns a lesson."}}
    draft.safety = {"rating": "all-ages", "flags": []}
    for key, value in draft_fields.items():
        setattr(draft, key, value)
    transcript = db.query(Transcript).filter_by(audio_asset_id=asset_id).one()
    transcript.status, transcript.confidence = "needs-review", 0.9
    db.commit()
    return asset


def approval(**changes):
    body = {"title": "Garvam", "titles": {"te-IN": "గర్వం", "en-IN": "Pride"}, "teasers": {"en-IN": "A proud crow."},
            "age": "4-8", "moral": "Pride comes before a fall.", "checked": True}
    return {**body, **changes}


def test_batch_lists_ready_catalog_stories_and_publishes_one(client, db):
    ready_story(db, "b" * 16)
    make_user(db, "ed", "editor")
    login(client, "ed")
    page = client.get("/api/studio/batch").json()
    assert page["total"] == 1 and page["groups"] == [{"name": "Neeti Kathalu", "count": 1}]
    item = page["items"][0]
    assert item["age"] == "4-8" and item["fullReview"] == [] and item["teasers"]["en-IN"]["short"] == "A proud crow."

    response = client.post(f"/api/studio/batch/{'b' * 16}/publish", json=approval())
    assert response.status_code == 200, response.json()
    db.expire_all()
    asset = db.get(AudioAsset, "b" * 16)
    assert asset.status == "published" and asset.moral_takeaway == "Pride comes before a fall."
    assert asset.title_translations["te-IN"]["confirmed"] and not asset.captions_enabled
    assert client.get("/api/studio/batch").json()["total"] == 0


def test_batch_needs_the_checks_and_sends_flagged_stories_to_full_review(client, db):
    ready_story(db, "c" * 16)
    ready_story(db, "d" * 16, safety={"rating": "older-kids", "flags": [{"category": "violence", "severity": "high"}]})
    make_user(db, "ed", "editor")
    login(client, "ed")
    assert client.post(f"/api/studio/batch/{'c' * 16}/publish", json=approval(checked=False)).status_code == 409
    flagged = client.post(f"/api/studio/batch/{'d' * 16}/publish", json=approval())
    assert flagged.status_code == 409 and "safety" in flagged.json()["problems"][0]
    db.expire_all()
    assert db.get(AudioAsset, "c" * 16).status != "published"


def test_unreliable_transcript_must_be_read_in_batch(client, db):
    ready_story(db, "e" * 16)
    db.query(Transcript).filter_by(audio_asset_id="e" * 16).one().confidence = 0.3
    db.commit()
    make_user(db, "ed", "editor")
    login(client, "ed")
    assert client.post(f"/api/studio/batch/{'e' * 16}/publish", json=approval()).status_code == 409
    response = client.post(f"/api/studio/batch/{'e' * 16}/publish", json=approval(transcriptChecked=True))
    assert response.status_code == 200, response.json()
    db.expire_all()
    assert db.get(AudioAsset, "e" * 16).captions_enabled
