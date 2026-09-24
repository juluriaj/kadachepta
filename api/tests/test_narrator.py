import hashlib

from sqlalchemy import select

from app.models import AudioAsset, Job
from app.storage import get_storage

from .conftest import login, make_user


def upload(client, content=b"RIFF" + b"\1" * 4000, name="story.wav", **fields):
    return client.post("/api/narrator/upload", files={"audio": (name, content, "audio/wav")},
                       data={"title": "My story", "genres": "Folklore, Bedtime", "language": "te", **fields})


def test_upload_stores_file_and_queues_audio_processing(client, db):
    make_user(db, "voice", "narrator")
    login(client, "voice")
    content = b"RIFF" + b"\2" * 5000
    response = upload(client, content)
    assert response.status_code == 201, response.text
    body = response.json()
    asset_id = hashlib.sha256(content).hexdigest()[:16]
    assert body["assetId"] == asset_id and body["metadata"]["genres"] == ["Folklore", "Bedtime"]
    asset = db.get(AudioAsset, asset_id)
    assert asset.language == "te-IN" and asset.status == "draft"
    assert get_storage().path(asset.source_key).read_bytes() == content
    jobs = db.scalars(select(Job).where(Job.audio_asset_id == asset_id)).all()
    assert [job.job_type for job in jobs] == ["media.process"]
    # Re-uploading the identical file doesn't create a second asset or job.
    assert upload(client, content).status_code == 201
    assert len(db.scalars(select(Job).where(Job.audio_asset_id == asset_id)).all()) == 1
    assets = client.get("/api/narrator/assets").json()["items"]
    assert assets[0]["mediaStatus"] == "pending" and assets[0]["audioUrl"].startswith("/media/")


def test_upload_rejects_bad_files(client, db):
    make_user(db, "voice", "narrator")
    login(client, "voice")
    assert upload(client, name="notes.txt").status_code == 400
    assert upload(client, content=b"").status_code == 400


def test_listeners_cannot_upload(client, db):
    make_user(db, "kid", "listener")
    login(client, "kid")
    assert upload(client).status_code == 403


def test_replacement_requires_own_published_parent(client, db):
    make_user(db, "voice", "narrator")
    login(client, "voice")
    first = upload(client, b"RIFF" + b"\3" * 3000).json()["assetId"]
    replacement = upload(client, b"RIFF" + b"\4" * 3000, parentAssetId=first)
    assert replacement.status_code == 409


def test_profile_update(client, db):
    make_user(db, "voice", "narrator")
    login(client, "voice")
    assert client.post("/api/narrator/profile", json={"displayName": "Sujata", "biography": "Storyteller",
                                                      "languages": ["te", "hi-in"]}).status_code == 200
    profile = client.get("/api/narrator/dashboard").json()["profile"]
    assert profile["displayName"] == "Sujata" and profile["languages"] == ["te-IN", "hi-IN"]
