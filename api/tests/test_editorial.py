from sqlalchemy import select

from app.models import AudioAsset, Job, NarratorCredit, TeaserDraft

from .conftest import login, make_asset, make_user


def editor(client, db):
    make_user(db, "ed", "editor")
    login(client, "ed")


def test_publish_requires_metadata_and_readiness(client, db):
    editor(client, db)
    make_asset(db, "b" * 16)
    response = client.post("/api/content/publish", json={"audioAssetId": "b" * 16})
    assert response.status_code == 409
    assert set(response.json()["missingMetadata"]) >= {"audienceAgeRange", "moralTakeaway"}


def test_publish_awards_narrator_credit_once_and_archives_parent(client, db):
    narrator = make_user(db, "voice", "narrator")
    make_asset(db, "o" * 16, status="published", narrator=narrator)
    make_asset(db, "r" * 16, narrator=narrator, ready_to_publish=True, parent_asset_id="o" * 16, version_number=2)
    editor(client, db)
    assert client.post("/api/content/publish", json={"audioAssetId": "r" * 16}).status_code == 200
    assert client.post("/api/content/publish", json={"audioAssetId": "r" * 16}).status_code == 200
    db.expire_all()
    assert db.get(AudioAsset, "r" * 16).status == "published"
    assert db.get(AudioAsset, "o" * 16).status == "archived"
    assert len(db.scalars(select(NarratorCredit)).all()) == 1


def test_seed_catalog_story_can_be_published_without_narrator_account(client, db):
    make_asset(db, "s" * 16, ready_to_publish=True)
    editor(client, db)
    assert client.post("/api/content/publish", json={"audioAssetId": "s" * 16}).status_code == 200
    assert not db.scalars(select(NarratorCredit)).all()


def test_process_validation_messages(client, db):
    editor(client, db)
    make_asset(db, "c" * 16)
    missing = client.post("/api/narrator/process", json={"action": "artwork"})
    assert missing.status_code == 400 and "missing assetId" in missing.json()["error"]
    assert "processingActions" in missing.json()["server"]
    unsupported = client.post("/api/narrator/process", json={"assetId": "c" * 16, "action": "poster"})
    assert unsupported.status_code == 400 and "poster" in unsupported.json()["error"]
    teaser = client.post("/api/narrator/process", json={"assetId": "c" * 16, "action": "teaser"})
    assert teaser.status_code == 409 and "Approve the transcript" in teaser.json()["error"]


def test_process_enqueues_once(client, db):
    editor(client, db)
    make_asset(db, "c" * 16)
    first = client.post("/api/narrator/process", json={"assetId": "c" * 16, "action": "artwork"})
    assert first.status_code == 202 and first.json()["job"]["status"] == "queued"
    again = client.post("/api/narrator/process", json={"assetId": "c" * 16, "action": "artwork"})
    assert again.status_code == 409 and "already queued" in again.json()["error"]
    assert len(db.scalars(select(Job).where(Job.job_type == "artwork")).all()) == 1


def test_rights_form_accepts_blank_dates(client, db):
    editor(client, db)
    make_asset(db, "c" * 16)
    response = client.post("/api/narrator/rights", json={
        "audioAssetId": "c" * 16, "status": "approved", "licenseStart": "", "licenseEnd": "", "recordingRights": True})
    assert response.status_code == 200
    rights = client.get(f"/api/narrator/asset?id={'c' * 16}").json()["rights"]
    assert rights["status"] == "approved" and rights["licenseEnd"] is None and rights["recordingRights"] is True


def test_transcript_edit_sends_teaser_back_to_review(client, db):
    make_asset(db, "e" * 16, ready_to_publish=True)
    editor(client, db)
    detail = client.get(f"/api/narrator/asset?id={'e' * 16}").json()
    response = client.post("/api/narrator/content-edit",
                           json={"type": "transcript", "id": detail["transcript"]["id"], "text": "సవరించిన కథ"})
    assert response.status_code == 200
    db.expire_all()
    assert db.scalars(select(TeaserDraft)).one().status == "needs-review"


def test_metadata_review_by_editor_and_narrator_limits(client, db):
    narrator = make_user(db, "voice", "narrator")
    other = make_user(db, "other", "narrator")
    make_asset(db, "m" * 16, narrator=narrator)
    login(client, "other")
    assert client.post("/api/narrator/metadata", json={"audioAssetId": "m" * 16, "title": "Mine"}).status_code == 404
    client.post("/api/logout")
    login(client, "voice")
    ok = client.post("/api/narrator/metadata", json={"audioAssetId": "m" * 16, "title": "New title",
                                                     "genres": "Folklore, Moral", "metadataReviewStatus": "approved"})
    assert ok.json()["metadataReviewStatus"] == "not-reviewed"  # narrators can't approve their own metadata
    assert ok.json()["metadata"]["genres"] == ["Folklore", "Moral"]
    assert other  # silence unused warning


def test_queue_permissions_and_catalog_search(client, db):
    make_asset(db, "k" * 16, title="Kaki Hamsa")
    make_asset(db, "z" * 16, title="Something else")
    make_user(db, "kid", "listener")
    login(client, "kid")
    assert client.get("/api/queue?queue=catalog").status_code == 403
    client.post("/api/logout")
    editor(client, db)
    items = client.get("/api/queue?queue=catalog&q=kaki").json()["items"]
    assert [item["id"] for item in items] == ["k" * 16]


def test_delete_only_for_unpublished_narrator_submissions(client, db):
    narrator = make_user(db, "voice", "narrator")
    make_asset(db, "s" * 16)
    make_asset(db, "u" * 16, narrator=narrator)
    editor(client, db)
    assert client.post("/api/narrator/delete", json={"audioAssetId": "s" * 16}).status_code == 409
    assert client.post("/api/narrator/delete", json={"audioAssetId": "u" * 16}).status_code == 200
    db.expire_all()
    assert db.get(AudioAsset, "u" * 16) is None


def test_publish_waits_for_audio_processing(client, db):
    asset = make_asset(db, "w" * 16, ready_to_publish=True)
    asset.media_status = "pending"
    db.commit()
    editor(client, db)
    response = client.post("/api/content/publish", json={"audioAssetId": "w" * 16})
    assert response.status_code == 409 and "Audio processing" in response.json()["error"]


def test_listeners_never_receive_original_audio_links(client, db):
    make_asset(db, "p" * 16, ready_to_publish=True, status="published")
    make_user(db, "kid", "listener")
    login(client, "kid")
    assert "originalAudioUrl" not in client.get("/api/catalog").json()["items"][0]


def test_one_click_kathachepta_owned_rights(client, db):
    make_asset(db, "o" * 16)
    make_user(db, "kid", "listener")
    login(client, "kid")
    assert client.post("/api/narrator/rights/owned", json={"audioAssetId": "o" * 16}).status_code == 403
    client.post("/api/logout")
    editor(client, db)
    rights = client.post("/api/narrator/rights/owned", json={"audioAssetId": "o" * 16}).json()["rights"]
    assert rights["status"] == "approved" and rights["sourceType"] == "kathachepta-owned"
    assert rights["attestedBy"] == "ed" and rights["licenseEnd"] is None
    assert all(rights[flag] for flag in ("recordingRights", "performanceRights", "adaptationRights",
                                         "artworkRights", "musicRights"))
