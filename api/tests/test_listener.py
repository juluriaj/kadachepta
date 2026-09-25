import time
from urllib.parse import parse_qs, urlparse

from app.config import get_settings
from app.security import sign_media

from .conftest import login, make_asset, make_user


def test_catalog_lists_only_published_stories_with_approved_teasers(client, db):
    make_asset(db, "p" * 16, ready_to_publish=True, status="published")
    make_asset(db, "d" * 16, ready_to_publish=True, status="draft")
    make_asset(db, "n" * 16, status="published")  # no approved teaser
    make_user(db, "kid", "listener")
    login(client, "kid")
    items = client.get("/api/catalog").json()["items"]
    assert [item["id"] for item in items] == ["p" * 16]
    assert items[0]["longText"] == "ఒక మంచి కథ" and items[0]["audioUrl"].startswith("/media/")


def test_catalog_requires_login(client):
    assert client.get("/api/catalog").status_code == 401


def test_signed_media_supports_range_and_rejects_tampering(client, db):
    audio = bytes(range(256)) * 40
    make_asset(db, "m" * 16, ready_to_publish=True, status="published", audio_bytes=audio)
    make_user(db, "kid", "listener")
    login(client, "kid")
    url = client.get("/api/catalog").json()["items"][0]["audioUrl"]
    full = client.get(url)
    assert full.status_code == 200 and full.content == audio and full.headers["accept-ranges"] == "bytes"
    part = client.get(url, headers={"Range": "bytes=100-199"})
    assert part.status_code == 206 and part.content == audio[100:200]
    assert part.headers["content-range"] == f"bytes 100-199/{len(audio)}"
    assert client.get(url, headers={"Range": "bytes=-10"}).content == audio[-10:]
    assert client.get(url, headers={"Range": f"bytes={len(audio)}-"}).status_code == 416
    assert client.get(url.replace("s=", "s=x")).status_code == 403
    parsed = urlparse(url)
    expired, signature = sign_media(parsed.path.removeprefix("/media/"), get_settings().secret_key, -3600,
                                    now=time.time() - 7200)
    assert client.get(f"{parsed.path}?e={expired}&s={signature}").status_code == 403
    assert parse_qs(parsed.query)["e"]


def test_favorites_only_accept_published_stories(client, db):
    make_asset(db, "p" * 16, ready_to_publish=True, status="published")
    make_asset(db, "d" * 16)
    make_user(db, "parent1", "parent")
    login(client, "parent1")
    ids = client.post("/api/me/favorites", json={"assetIds": ["p" * 16, "d" * 16], "saved": True}).json()["ids"]
    assert ids == ["p" * 16]
    assert client.post("/api/me/favorites", json={"assetId": "p" * 16, "saved": False}).json()["ids"] == []


def test_listening_reports_are_capped_and_feed_stats(client, db):
    make_asset(db, "p" * 16, ready_to_publish=True, status="published", genres=["Moral", "Folklore"])
    make_user(db, "runner", "listener")
    login(client, "runner")
    base = {"assetId": "p" * 16, "position": 30}
    assert client.post("/api/me/listening", json={**base, "seconds": 45, "started": True, "day": "2026-09-21"}).status_code == 200
    client.post("/api/me/listening", json={**base, "seconds": 999, "completed": True, "day": "2026-09-22"})
    # sendBeacon posts without a JSON content type; the endpoint must still accept it.
    client.post("/api/me/listening", content=b'{"assetId": "' + b"p" * 16 + b'", "seconds": 5, "day": "2026-09-22"}',
                headers={"Content-Type": "text/plain"})
    stats = client.get("/api/me/stats?today=2026-09-22").json()
    assert stats["totalSeconds"] == 170 and stats["storiesStarted"] == 1 and stats["storiesCompleted"] == 1
    assert stats["streakDays"] == 1  # the 45 s day is under the one-minute streak threshold
    assert {g["genre"] for g in stats["genres"]} == {"Moral", "Folklore"}
    assert stats["recent"][0]["completed"] is True


def test_listening_rejects_unpublished_story(client, db):
    make_asset(db, "d" * 16)
    make_user(db, "runner", "listener")
    login(client, "runner")
    assert client.post("/api/me/listening", json={"assetId": "d" * 16, "seconds": 5}).status_code == 404


def test_read_along_only_when_captions_are_on_and_follows_the_audio(client, db):
    from sqlalchemy import select

    from app.models import AudioAsset, Transcript

    make_asset(db, "r" * 16, ready_to_publish=True, status="published")
    make_asset(db, "q" * 16, ready_to_publish=True, status="published")  # captions off
    make_user(db, "kid", "listener")
    transcript = db.scalars(select(Transcript).where(Transcript.audio_asset_id == "r" * 16)).one()
    transcript.text = "ఒక కాకి ఉండేది. అది తెలివైనది.\nఒక రోజు దాహం వేసింది. నీళ్ళు తాగింది."
    transcript.intro_removed = "కథచెప్తా.కామ్"
    transcript.segments = {"words": ["కథచెప్తా.కామ్ ఒక కాకి ఉండేది. అది తెలివైనది.", "ఒక రోజు దాహం వేసింది. నీళ్ళు తాగింది."],
                           "start_time_seconds": [0.0, 15.0], "end_time_seconds": [15.0, 29.5]}
    asset = db.get(AudioAsset, "r" * 16)
    asset.captions_enabled = True
    asset.qc = {"mastering": {"trimmedStart": 1.5}}
    db.commit()
    login(client, "kid")
    assert client.get(f"/api/stories/{'r' * 16}").json()["readAlong"] is True
    assert client.get(f"/api/stories/{'q' * 16}").json()["readAlong"] is False
    assert client.get(f"/api/stories/{'q' * 16}/read-along").status_code == 404
    text = client.get(f"/api/stories/{'r' * 16}/read-along").json()
    assert text["timed"] and text["passages"] == [
        {"start": 0.0, "end": 13.5, "text": "ఒక కాకి ఉండేది. అది తెలివైనది."},
        {"start": 13.5, "end": 28.0, "text": "ఒక రోజు దాహం వేసింది. నీళ్ళు తాగింది."},
    ]
