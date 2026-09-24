"""Phase 2: resumable uploads, the automatic pipeline, and the narrator's view of it."""

from sqlalchemy import select

from app import jobs, mailer
from app.auth import utcnow
from app.models import AppSetting, AudioAsset, Job, Notification, TeaserDraft, Transcript, User

from .conftest import login, make_asset, make_user, make_worker

AUDIO = b"ID3" + bytes(range(256)) * 40
ATTESTATION = {"sourceType": "public-domain", "sourceReference": "Panchatantra"}


def worker_auth(token):
    return {"Authorization": f"Worker {token}"}


def upload(client, data=AUDIO, filename="story.m4a", purpose="audio"):
    created = client.post("/api/uploads", json={"filename": filename, "size": len(data), "purpose": purpose})
    assert created.status_code == 201, created.text
    upload_id = created.json()["id"]
    response = client.put(f"/api/uploads/{upload_id}?offset=0", content=data)
    assert response.json()["complete"], response.text
    return upload_id


def run_job(client, token, job_type, result, files=None):
    lease = client.post("/api/worker/lease", json={}, headers=worker_auth(token))
    assert lease.status_code == 200, f"expected a {job_type} job, got {lease.status_code}"
    lease = lease.json()
    assert lease["type"] == job_type, lease["type"]
    for name, content in (files or {}).items():
        key = client.post(f"/api/worker/jobs/{lease['id']}/files?name={name}", content=content,
                          headers=worker_auth(token)).json()["key"]
        result = {k: (key if v == f"<{name}>" else v) for k, v in result.items()}
        if "renditions" in result:
            result["renditions"] = {"standard": {"key": key, "bytes": len(content)}}
    response = client.post(f"/api/worker/jobs/{lease['id']}/complete", json={"result": result},
                           headers=worker_auth(token))
    assert response.status_code == 200, response.text
    return lease


MEDIA_OK = {"durationSeconds": 120, "renditions": {}, "waveform": [0.2], "qc": {"verdict": "pass", "checks": []}}
TELUGU = "కథచెప్తా.కామ్ నేను చెప్పబోయే కథ కాకి. " + " ".join(f"ఒక కాకి {i} వ చెట్టు మీద కూర్చుంది." for i in range(40))
DRAFTS = {"language": "te-IN", "texts": {"te-IN": {"short": "కాకి కథ", "long": "తెలివైన కాకి కథ"},
                                         "en-IN": {"short": "A crow", "long": "A clever crow"}},
          "themes": ["cleverness"], "mood": ["funny"], "ageSuggestion": "4-8", "contentWarnings": [],
          "moralTakeaway": "Think before you act.", "genres": ["Fable", "Nonsense"], "keywords": ["crow"],
          "listeningContexts": ["bedtime", "space"], "englishTitle": "The Crow",
          "safety": {"rating": "all-ages", "minAge": 3, "flags": [], "summary": "Gentle fable."},
          "provider": "lmstudio", "model": "qwen/qwen3-8b", "promptVersion": "drafts-v4"}


def narrate_to_review(client, db, token, **submission):
    upload_id = upload(client)
    body = {"uploadIds": [upload_id], "title": "కాకి", "language": "te-IN", "attestation": ATTESTATION, **submission}
    created = client.post("/api/narrator/submissions", json=body)
    assert created.status_code == 201, created.text
    asset_id = created.json()["id"]
    run_job(client, token, "media.process", dict(MEDIA_OK), {"standard.m4a": b"m4a"})
    run_job(client, token, "transcription", {"language": "te-IN", "text": TELUGU, "provider": "sarvam",
                                             "languageProbability": 0.97})
    run_job(client, token, "teaser", dict(DRAFTS))
    run_job(client, token, "artwork", {"key": "<cover.jpg>", "provider": "local-sdxl"}, {"cover.jpg": b"\xff\xd8\xff"})
    return asset_id


def test_resumable_upload_accepts_chunks_repeats_and_reports_gaps(client, db):
    make_user(db, "narr", "narrator")
    login(client, "narr")
    created = client.post("/api/uploads", json={"filename": "take.m4a", "size": 10}).json()
    url = f"/api/uploads/{created['id']}"
    assert client.put(f"{url}?offset=0", content=b"01234").json()["receivedBytes"] == 5
    assert client.put(f"{url}?offset=0", content=b"01234").json()["receivedBytes"] == 5  # repeated chunk
    gap = client.put(f"{url}?offset=8", content=b"89")
    assert gap.status_code == 409 and gap.json()["receivedBytes"] == 5
    assert client.put(f"{url}?offset=5", content=b"56789").json()["complete"] is True
    assert client.get(url).json()["receivedBytes"] == 10
    assert client.post("/api/uploads", json={"filename": "x.exe", "size": 5}).status_code == 400


def test_listener_cannot_upload_story_audio(client, db):
    make_user(db, "lis", "listener")
    login(client, "lis")
    assert client.post("/api/uploads", json={"filename": "a.m4a", "size": 5}).status_code == 403


def test_submission_flows_through_the_pipeline_to_one_click_publish(client, db):
    narrator = make_user(db, "narr", "narrator", email="narr@example.com")
    token = make_worker(db)
    login(client, "narr")
    asset_id = narrate_to_review(client, db, token)

    db.expire_all()
    asset = db.get(AudioAsset, asset_id)
    assert asset.pipeline_stage == "ready" and asset.ready_for_review_at is not None
    transcript = db.scalars(select(Transcript)).one()
    assert transcript.text.startswith("నేను చెప్పబోయే కథ") and "కామ్" in transcript.intro_removed
    assert transcript.confidence >= 0.9
    assert asset.genres == ["Fable"] and asset.listening_contexts == ["bedtime"]  # unknown values dropped
    assert db.scalars(select(TeaserDraft)).one().safety["rating"] == "all-ages"
    home = client.get("/api/narrator/home").json()
    assert home["submissions"][0]["stageLabel"] == "With editor"
    detail = client.get(f"/api/narrator/submissions/{asset_id}").json()
    assert [step["state"] for step in detail["timeline"]] == ["done", "done", "done", "current", "todo"]

    make_user(db, "ed", "editor")
    login(client, "ed")
    review = client.get(f"/api/studio/review/{asset_id}").json()
    assert review["transcript"]["reviewRequired"] is False and review["rights"]["attestation"]["sourceType"] == "public-domain"
    blocked = client.post(f"/api/studio/review/{asset_id}/publish", json={"rights": "attestation"})
    assert blocked.status_code == 409 and any("checklist" in p for p in blocked.json()["problems"])
    db.expire_all()
    assert db.get(AudioAsset, asset_id).metadata_review_status == "not-reviewed"  # nothing half-approved
    checklist = ["listened", "age", "voice", "teaser"]
    published = client.post(f"/api/studio/review/{asset_id}/publish", json={
        "rights": "attestation", "checklist": checklist,
        "teaser": {"te-IN": {"short": "కాకి", "long": "తెలివైన కాకి"}}, "metadata": {"audienceAgeRange": "4-8"}})
    assert published.status_code == 200, published.text
    db.expire_all()
    asset = db.get(AudioAsset, asset_id)
    assert asset.status == "published" and asset.pipeline_stage == "published"
    assert db.scalars(select(Transcript)).one().status == "accepted"
    assert db.scalars(select(TeaserDraft)).one().long_text == "తెలివైన కాకి"
    kinds = [n.kind for n in db.scalars(select(Notification).where(Notification.user_id == narrator.id))]
    assert "with-editor" in kinds and "published" in kinds
    assert any("is published" in message["Subject"] for message in mailer.sent_messages)


def test_failed_sound_check_stops_before_paid_transcription(client, db):
    make_user(db, "narr", "narrator", email="n@example.com")
    token = make_worker(db)
    login(client, "narr")
    asset_id = client.post("/api/narrator/submissions", json={
        "uploadIds": [upload(client)], "title": "Quiet", "attestation": ATTESTATION}).json()["id"]
    qc = {"verdict": "fail", "checks": [{"level": "fail", "code": "too-quiet", "message": "Very quiet",
                                         "tip": "Move closer to the microphone."}]}
    run_job(client, token, "media.process", {**MEDIA_OK, "qc": qc}, {"standard.m4a": b"m4a"})
    db.expire_all()
    assert db.get(AudioAsset, asset_id).pipeline_stage == "needs-fix"
    assert db.scalar(select(Job).where(Job.job_type == "transcription")) is None
    assert any("Move closer" in message.get_content() for message in mailer.sent_messages)
    assert client.post(f"/api/narrator/submissions/{asset_id}/submit").status_code == 409
    replaced = client.post(f"/api/narrator/submissions/{asset_id}/replace-audio",
                           json={"uploadIds": [upload(client, AUDIO + b"louder")]})
    assert replaced.json()["stage"] == "checking"
    run_job(client, token, "media.process", dict(MEDIA_OK), {"standard.m4a": b"m4a"})
    db.expire_all()
    assert db.get(AudioAsset, asset_id).pipeline_stage == "transcribing"


def test_manual_submit_and_multi_take_recordings(client, db):
    make_user(db, "narr", "narrator")
    token = make_worker(db)
    login(client, "narr")
    takes = [upload(client, AUDIO + b"1", "take1.m4a"), upload(client, AUDIO + b"2", "take2.m4a")]
    asset_id = client.post("/api/narrator/submissions", json={
        "uploadIds": takes, "title": "Takes", "attestation": ATTESTATION, "autoSubmit": False}).json()["id"]
    lease = client.post("/api/worker/lease", json={}, headers=worker_auth(token)).json()
    assert [part["filename"] for part in lease["inputs"]["parts"]] == ["01-take1.m4a", "02-take2.m4a"]
    joined = client.post(f"/api/worker/jobs/{lease['id']}/files?name=original.m4a", content=b"joined",
                         headers=worker_auth(token)).json()["key"]
    standard = client.post(f"/api/worker/jobs/{lease['id']}/files?name=standard.m4a", content=b"std",
                           headers=worker_auth(token)).json()["key"]
    client.post(f"/api/worker/jobs/{lease['id']}/complete", headers=worker_auth(token), json={"result": {
        **MEDIA_OK, "sourceKey": joined, "renditions": {"standard": {"key": standard}}}})
    db.expire_all()
    asset = db.get(AudioAsset, asset_id)
    assert asset.source_key == joined and asset.pipeline_stage == "awaiting-submit"
    assert client.post(f"/api/narrator/submissions/{asset_id}/submit").json()["stage"] == "transcribing"


def test_changes_requested_then_resubmitted(client, db):
    make_user(db, "narr", "narrator")
    token = make_worker(db)
    login(client, "narr")
    asset_id = narrate_to_review(client, db, token)
    make_user(db, "ed", "editor")
    login(client, "ed")
    assert client.post(f"/api/studio/review/{asset_id}/request-changes",
                       json={"reasons": ["bogus"]}).status_code == 400
    response = client.post(f"/api/studio/review/{asset_id}/request-changes",
                           json={"reasons": ["audio-noise"], "note": "Fan noise at 2:10"})
    assert response.json()["stage"] == "changes-requested"
    login(client, "narr")
    detail = client.get(f"/api/narrator/submissions/{asset_id}").json()
    assert detail["changesRequested"]["note"] == "Fan noise at 2:10" and detail["timeline"][3]["state"] == "blocked"
    assert client.post(f"/api/narrator/submissions/{asset_id}/submit").json()["stage"] == "ready"


def test_catalog_prepare_never_transcribes_without_admin(client, db):
    make_asset(db, "c" * 16, media_status="ready").duration_seconds = 600
    make_asset(db, "d" * 16, media_status="ready")
    db.add(Transcript(audio_asset_id="d" * 16, version=1, language="te-IN", text=TELUGU, status="needs-review",
                      source_audio_checksum="0" * 64))
    db.commit()
    make_user(db, "ed", "editor")
    login(client, "ed")
    assert client.post("/api/studio/prepare", json={"allowTranscription": True}).status_code == 403
    result = client.post("/api/studio/prepare", json={}).json()
    assert result["stages"] == {"waiting-transcript": 1, "drafting": 1} and result["untranscribedMinutes"] == 10
    assert db.scalar(select(Job).where(Job.job_type == "transcription")) is None
    make_user(db, "boss", "admin")
    login(client, "boss")
    result = client.post("/api/studio/prepare", json={"assetIds": ["c" * 16], "allowTranscription": True}).json()
    assert result["stages"] == {"transcribing": 1} and result["transcriptionMinutes"] == 10


def test_daily_transcription_limit_defers_jobs(client, db):
    make_user(db, "narr", "narrator")
    db.add(AppSetting(key="pipeline.dailyTranscriptionMinutes", value=1))
    db.commit()
    token = make_worker(db)
    login(client, "narr")
    client.post("/api/narrator/submissions", json={"uploadIds": [upload(client)], "title": "Long",
                                                   "attestation": ATTESTATION})
    run_job(client, token, "media.process", {**MEDIA_OK, "durationSeconds": 600}, {"standard.m4a": b"m4a"})
    job = db.scalars(select(Job).where(Job.job_type == "transcription")).one()
    assert job.run_after > utcnow() and job.run_after.hour == 0


def test_bulk_publish_only_for_trusted_narrators_and_owned_catalog(client, db):
    narrator = make_user(db, "narr", "narrator")
    token = make_worker(db)
    login(client, "narr")
    first = narrate_to_review(client, db, token)
    make_user(db, "ed", "editor")
    login(client, "ed")
    assert client.post("/api/studio/bulk-publish", json={"assetIds": [first]}).status_code == 409
    result = client.post("/api/studio/bulk-publish", json={"assetIds": [first], "spotChecked": True}).json()
    assert result["published"] == 0 and "narrator isn't trusted yet" in result["results"][0]["problems"]
    assert client.post(f"/api/studio/narrators/{narrator.id}/trust", json={"trustLevel": "trusted"}).status_code == 200
    queue = client.get("/api/studio/queue?view=review").json()
    assert queue["items"][0]["bulkEligible"] is True and queue["counts"]["review"] == 1
    result = client.post("/api/studio/bulk-publish", json={"assetIds": [first], "spotChecked": True}).json()
    assert result["published"] == 1, result
    db.expire_all()
    assert db.get(AudioAsset, first).status == "published"


def test_new_narrators_have_an_in_progress_limit(client, db):
    make_user(db, "narr", "narrator")
    db.add(AppSetting(key="narrators.newInProgressLimit", value=1))
    db.commit()
    login(client, "narr")
    assert client.post("/api/narrator/submissions", json={"uploadIds": [upload(client)], "title": "One",
                                                          "attestation": ATTESTATION}).status_code == 201
    second = client.post("/api/narrator/submissions", json={"uploadIds": [upload(client, AUDIO + b"2")],
                                                            "title": "Two", "attestation": ATTESTATION})
    assert second.status_code == 409 and "at a time" in second.json()["error"]


def test_listener_becomes_narrator_with_sample(client, db):
    user = make_user(db, "lis", "listener")
    login(client, "lis")
    agreement = client.get("/api/narrator/agreement").json()
    sample = upload(client, filename="sample.m4a", purpose="sample")
    response = client.post("/api/narrator/apply", json={
        "displayName": "Lakshmi", "languages": ["te"], "agreementVersion": agreement["version"],
        "sampleUploadId": sample})
    assert response.status_code == 200, response.text
    db.expire_all()
    assert db.get(User, user.id).role == "narrator" and response.json()["profile"]["sampleUrl"]
    assert client.get("/api/narrator/home").status_code == 200
    assert client.post("/api/narrator/apply", json={"displayName": "x", "languages": ["te"],
                                                    "agreementVersion": "old"}).status_code == 409


def test_settings_are_validated_audited_and_sent_with_jobs(client, db):
    make_user(db, "boss", "admin")
    make_user(db, "ed", "editor")
    login(client, "ed")
    assert client.get("/api/studio/settings").status_code == 403
    login(client, "boss")
    page = client.get("/api/studio/settings").json()
    assert page["values"]["ai.drafts.promptVersion"] == "drafts-v4"
    bad = client.put("/api/studio/settings", json={"values": {"ai.artwork.provider": "midjourney"}})
    assert bad.status_code == 422
    ok = client.put("/api/studio/settings", json={"values": {"ai.llm.model": "google/gemma-3-12b",
                                                             "ai.llm.modelByLanguage": {"hi-IN": "sarvam-m"}}})
    assert set(ok.json()["changed"]) == {"ai.llm.model", "ai.llm.modelByLanguage"}
    make_asset(db, "h" * 16, language="hi-IN")
    make_asset(db, "t" * 16, language="te-IN")
    for asset_id in ("h" * 16, "t" * 16):
        db.add(Transcript(audio_asset_id=asset_id, version=1, language="te-IN", text="x", status="needs-review",
                          source_audio_checksum="0" * 64))
    db.commit()
    token = make_worker(db)
    tested = client.post("/api/studio/settings/test", json={"task": "drafts", "assetId": "t" * 16,
                                                            "values": {"ai.llm.model": "qwen/qwen3-4b"}}).json()
    lease = client.post("/api/worker/lease", json={}, headers=worker_auth(token)).json()
    assert lease["id"] == tested["jobId"] and lease["inputs"]["settings"]["ai.llm.model"] == "qwen/qwen3-4b"
    client.post(f"/api/worker/jobs/{lease['id']}/complete", headers=worker_auth(token), json={"result": DRAFTS})
    assert db.scalars(select(TeaserDraft)).first() is None  # a test never changes the story
    assert client.get(f"/api/studio/jobs/{tested['jobId']}").json()["result"]["texts"]["en-IN"]["short"] == "A crow"
    jobs.enqueue(db, "teaser", asset_id="h" * 16, payload={"transcriptId": 1})
    db.commit()
    lease = client.post("/api/worker/lease", json={}, headers=worker_auth(token)).json()
    assert lease["inputs"]["settings"]["ai.llm.model"] == "sarvam-m"
