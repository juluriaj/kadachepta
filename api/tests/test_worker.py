from datetime import timedelta

from sqlalchemy import select

from app import jobs
from app.auth import utcnow
from app.models import AudioAsset, Job, TeaserDraft, Transcript

from .conftest import make_asset, make_worker


def auth(token):
    return {"Authorization": f"Worker {token}"}


def test_lease_requires_worker_token(client):
    assert client.post("/api/worker/lease", json={}).status_code == 401
    assert client.post("/api/worker/lease", json={}, headers=auth("nope")).status_code == 401


def test_media_job_round_trip(client, db):
    make_asset(db, "a" * 16)
    jobs.enqueue(db, "media.process", asset_id="a" * 16)
    db.commit()
    token = make_worker(db, capabilities=["media"])
    lease = client.post("/api/worker/lease", json={}, headers=auth(token)).json()
    assert lease["type"] == "media.process" and lease["inputs"]["sourceUrl"].startswith("http://testserver/media/")
    source = client.get(lease["inputs"]["sourceUrl"])
    assert source.status_code == 200
    key = client.post(f"/api/worker/jobs/{lease['id']}/files?name=standard.m4a", content=b"m4a-data",
                      headers=auth(token)).json()["key"]
    assert key == f"renditions/{'a' * 16}/v1/j{lease['id']}/standard.m4a"
    result = {"durationSeconds": 301.5, "renditions": {"standard": {"key": key, "bytes": 8}},
              "waveform": [0.1, 1.0], "qc": {"verdict": "pass", "checks": []}}
    assert client.post(f"/api/worker/jobs/{lease['id']}/complete", json={"result": result},
                       headers=auth(token)).status_code == 200
    db.expire_all()
    asset = db.get(AudioAsset, "a" * 16)
    assert asset.media_status == "ready" and asset.duration_seconds == 301.5
    assert asset.renditions["standard"]["key"] == key and db.get(Job, lease["id"]).status == "succeeded"
    assert client.post("/api/worker/lease", json={}, headers=auth(token)).status_code == 204


def test_worker_only_gets_jobs_it_can_run(client, db):
    make_asset(db, "a" * 16)
    jobs.enqueue(db, "teaser", asset_id="a" * 16)
    db.commit()
    media_only = make_worker(db, "media-only", capabilities=["media"])
    assert client.post("/api/worker/lease", json={}, headers=auth(media_only)).status_code == 204
    llm = make_worker(db, "llm", capabilities=["llm"])
    assert client.post("/api/worker/lease", json={}, headers=auth(llm)).json()["type"] == "teaser"


def test_result_cannot_reference_another_assets_file(client, db):
    make_asset(db, "a" * 16)
    jobs.enqueue(db, "artwork", asset_id="a" * 16)
    db.commit()
    token = make_worker(db)
    lease = client.post("/api/worker/lease", json={}, headers=auth(token)).json()
    response = client.post(f"/api/worker/jobs/{lease['id']}/complete",
                           json={"result": {"key": "artworks/someoneelse/x.jpg"}}, headers=auth(token))
    assert response.status_code == 400
    db.expire_all()
    assert db.get(Job, lease["id"]).status == "dead"


def test_failures_back_off_then_dead_letter(client, db):
    make_asset(db, "a" * 16)
    job = jobs.enqueue(db, "transcription", asset_id="a" * 16, max_attempts=2)
    db.commit()
    token = make_worker(db)
    lease = client.post("/api/worker/lease", json={}, headers=auth(token)).json()
    first = client.post(f"/api/worker/jobs/{lease['id']}/fail", json={"error": "timeout"}, headers=auth(token)).json()
    assert first["status"] == "failed"
    # Not leasable until the back-off passes.
    assert client.post("/api/worker/lease", json={}, headers=auth(token)).status_code == 204
    db.get(Job, job.id).run_after = utcnow() - timedelta(seconds=1)
    db.commit()
    lease = client.post("/api/worker/lease", json={}, headers=auth(token)).json()
    second = client.post(f"/api/worker/jobs/{lease['id']}/fail", json={"error": "timeout"}, headers=auth(token)).json()
    assert second["status"] == "dead"


def test_expired_lease_is_picked_up_again(client, db):
    make_asset(db, "a" * 16)
    job = jobs.enqueue(db, "media.process", asset_id="a" * 16)
    db.commit()
    token = make_worker(db)
    client.post("/api/worker/lease", json={}, headers=auth(token))
    db.expire_all()
    db.get(Job, job.id).lease_until = utcnow() - timedelta(seconds=1)
    db.commit()
    again = client.post("/api/worker/lease", json={}, headers=auth(token)).json()
    assert again["id"] == job.id and again["attempt"] == 2


def test_transcription_and_teaser_results_are_applied(client, db):
    make_asset(db, "t" * 16, language="te-IN")
    jobs.enqueue(db, "transcription", asset_id="t" * 16)
    db.commit()
    token = make_worker(db)
    lease = client.post("/api/worker/lease", json={}, headers=auth(token)).json()
    client.post(f"/api/worker/jobs/{lease['id']}/complete", headers=auth(token), json={"result": {
        "language": "te-IN", "text": "ఒకప్పుడు", "segments": [{"start": 0}], "provider": "sarvam", "model": "saaras:v4"}})
    transcript = db.scalars(select(Transcript)).one()
    assert transcript.status == "needs-review" and transcript.version == 1
    transcript.status = "approved"
    jobs.enqueue(db, "teaser", asset_id="t" * 16, payload={"transcriptId": transcript.id})
    db.commit()
    lease = client.post("/api/worker/lease", json={}, headers=auth(token)).json()
    assert lease["inputs"]["transcript"] == "ఒకప్పుడు" and lease["inputs"]["outputLanguages"] == ["te-IN", "en-IN"]
    result = {"language": "te-IN", "texts": {"te-IN": {"short": "చిన్న", "long": "పెద్ద"},
                                             "en-IN": {"short": "Short", "long": "Long"}},
              "themes": ["kindness"], "mood": ["calm"], "ageSuggestion": "4-8", "contentWarnings": [],
              "moralTakeaway": "Be kind.", "provider": "lmstudio", "model": "qwen/qwen3-8b", "promptVersion": "teaser-v2"}
    assert client.post(f"/api/worker/jobs/{lease['id']}/complete", json={"result": result},
                       headers=auth(token)).status_code == 200
    db.expire_all()
    teaser = db.scalars(select(TeaserDraft)).one()
    assert teaser.long_text == "పెద్ద" and teaser.alternates["en-IN"]["long"] == "Long"
    asset = db.get(AudioAsset, "t" * 16)
    assert asset.moral_takeaway == "Be kind." and asset.audience_age_range == "4-8" and asset.mood == "calm"
    assert asset.metadata_review_status == "not-reviewed"


def test_teaser_result_without_primary_language_is_rejected(client, db):
    make_asset(db, "t" * 16)
    jobs.enqueue(db, "teaser", asset_id="t" * 16)
    db.commit()
    token = make_worker(db)
    lease = client.post("/api/worker/lease", json={}, headers=auth(token)).json()
    response = client.post(f"/api/worker/jobs/{lease['id']}/complete", headers=auth(token),
                           json={"result": {"language": "te-IN", "texts": {"en-IN": {"short": "a", "long": "b"}}}})
    assert response.status_code == 422


def test_interactive_jobs_run_before_bulk_backfill(client, db):
    make_asset(db, "b" * 16)
    make_asset(db, "u" * 16)
    jobs.enqueue(db, "media.process", asset_id="b" * 16, priority=jobs.PRIORITY_BULK)
    urgent = jobs.enqueue(db, "media.process", asset_id="u" * 16, priority=jobs.PRIORITY_INTERACTIVE)
    db.commit()
    token = make_worker(db)
    assert client.post("/api/worker/lease", json={}, headers=auth(token)).json()["id"] == urgent.id


def test_workers_get_the_same_kind_of_job_as_last_time(client, db):
    make_asset(db, "a" * 16)
    make_asset(db, "b" * 16)
    jobs.enqueue(db, "teaser", asset_id="a" * 16)
    artwork = jobs.enqueue(db, "artwork", asset_id="b" * 16)
    db.commit()
    token = make_worker(db)
    lease = client.post("/api/worker/lease", json={"preferType": "artwork"}, headers=auth(token)).json()
    assert lease["id"] == artwork.id  # same priority: no model swap on a shared GPU
