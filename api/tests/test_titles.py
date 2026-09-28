"""Story titles in each app language: AI suggestions, editor confirmation, and what listeners see."""

from app.models import AudioAsset, Job
from app.services import titles

from .conftest import login, make_asset, make_user, make_worker
from .test_pipeline import run_job


def test_numbered_chapters_and_titles_in_script_need_no_ai(db):
    chapter = make_asset(db, "c" * 16, title="Chapter 12")
    telugu = make_asset(db, "d" * 16, title="కాకి హంస కాగలదా")
    romanized = make_asset(db, "e" * 16, title="TR14.Bhale Kaaki")
    assert titles.confirmed_titles(chapter) == {"te-IN": "అధ్యాయం 12", "en-IN": "Chapter 12"}
    assert titles.confirmed_titles(telugu) == {"te-IN": "కాకి హంస కాగలదా"}
    assert titles.missing(telugu) == ["en-IN"]
    assert titles.missing(romanized) == ["te-IN", "en-IN"]  # romanized Telugu is not taken for English
    assert titles.clean_source(romanized.title) == "Bhale Kaaki"


def test_suggestions_wait_for_an_editor_and_go_stale_on_rename(client, db):
    asset = make_asset(db, title="Bhale Kaaki", status="published")
    token = make_worker(db)
    make_user(db, "ed", "editor")
    login(client, "ed")
    assert client.post("/api/studio/titles/suggest", json={}).json() == {"queued": 1}
    assert client.post("/api/studio/titles/suggest", json={}).json() == {"queued": 0}  # already queued
    lease = run_job(client, token, "titles", {"title": "Bhale Kaaki", "model": "qwen/qwen3-8b",
                                              "titles": {"te-IN": "భలే కాకి", "en-IN": "The Clever Crow"}})
    assert lease["inputs"]["sourceTitle"] == "Bhale Kaaki" and lease["inputs"]["languages"] == ["te-IN", "en-IN"]

    db.expire_all()
    asset = db.get(AudioAsset, asset.id)
    assert titles.confirmed_titles(asset) == {}  # suggestions only: listeners still see the original
    listed = next(i for i in client.get("/api/studio/titles").json()["items"] if i["id"] == asset.id)
    assert listed["titles"]["en-IN"] == {"text": "The Clever Crow", "by": "ai:qwen/qwen3-8b", "confirmed": False}

    saved = client.post(f"/api/studio/titles/{asset.id}", json={"titles": {"te-IN": "భలే కాకి", "en-IN": "The Smart Crow"}})
    assert saved.json()["titles"] == {"te-IN": "భలే కాకి", "en-IN": "The Smart Crow"}
    db.expire_all()
    asset = db.get(AudioAsset, asset.id)
    asset.title = "Bhale Kaaki Katha"
    db.commit()
    assert titles.confirmed_titles(asset) == {} and titles.missing(asset) == ["te-IN", "en-IN"]


def test_result_for_an_old_title_is_ignored(client, db):
    asset = make_asset(db, title="Kappa Raju", status="published")
    token = make_worker(db)
    make_user(db, "ed", "editor")
    login(client, "ed")
    client.post("/api/studio/titles/suggest", json={"assetIds": [asset.id]})
    db.get(AudioAsset, asset.id).title = "Kappa Raani"
    db.commit()
    run_job(client, token, "titles", {"title": "Kappa Raju", "titles": {"en-IN": "The Frog King"}, "model": "m"})
    db.expire_all()
    assert db.get(AudioAsset, asset.id).title_translations == {}
    assert db.query(Job).filter_by(job_type="titles").one().status == "succeeded"
