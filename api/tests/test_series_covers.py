"""Book covers: one cover for every chapter, where it came from, our own cover as a swap, and taking a book down."""

import io

from PIL import Image, features
from sqlalchemy import select

from app.models import AudioAsset, EditorialEvent, Series, Transcript
from app.services import covers

from .conftest import login, make_user, make_worker
from .test_pipeline import run_job
from .test_story_sets import book


def jpeg(color=(40, 120, 60), size=(640, 900)) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", size, color).save(out, format="JPEG")
    return out.getvalue()


def editor(client, db):
    if not hasattr(db, "_editor_made"):
        make_user(db, "ed", "editor")
        db._editor_made = True
    login(client, "ed")


def listener(client, db):
    if not hasattr(db, "_listener_made"):
        make_user(db, "amma", "listener")
        db._listener_made = True
    login(client, "amma")


def path(url: str) -> str:
    return url.split("?")[0]  # media links are signed with an expiry


def test_our_own_cover_sets_the_telugu_title_on_a_paper_band():
    assert features.check("raqm"), "the API image needs libfribidi0 for Telugu layout"
    cover = Image.open(io.BytesIO(covers.compose_own_cover(jpeg(), "బారిష్టర్ పార్వతీశం", "Barister Parvateesam")))
    assert cover.size == (1024, 1024)
    assert all(abs(a - b) <= 3 for a, b in zip(cover.getpixel((12, 1010)), (247, 238, 222), strict=True))  # paper
    assert cover.getpixel((512, 200))[1] > 100  # the illustration above it
    band = cover.crop((0, 760, 1024, 1024)).convert("L")
    assert min(band.getdata()) < 120  # dark ink: the title was drawn


def test_a_book_cover_stands_for_every_chapter_and_records_its_source(client, db):
    series = book(db, chapters=2)
    db.commit()
    editor(client, db)
    refused = client.put(f"/api/studio/series/{series.id}/cover?source=Visalandhra 1982 edition", content=b"not an image")
    assert refused.status_code == 422 and "JPEG, PNG, or WebP" in refused.json()["error"]
    assert client.put(f"/api/studio/series/{series.id}/cover", content=jpeg()).status_code == 422  # source needed

    saved = client.put(f"/api/studio/series/{series.id}/cover?source=Visalandhra 1982 edition", content=jpeg()).json()
    assert saved["cover"]["kind"] == "book-cover" and saved["cover"]["source"] == "Visalandhra 1982 edition"
    assert saved["chapters"] == 2 and saved["published"] == 2
    url = path(saved["cover"]["url"])
    assert url.startswith("/media/series/") and url.endswith("-book-cover.jpg")

    listener(client, db)
    assert path(client.get(f"/api/stories/{'c2'.ljust(16, '0')}").json()["artworkUrl"]) == url
    assert path(client.get(f"/api/books/{series.id}").json()["artworkUrl"]) == url
    events = db.scalars(select(EditorialEvent).where(EditorialEvent.entity_type == "series")).all()
    assert [e.action for e in events] == ["series:book-cover"] and "Visalandhra 1982 edition" in events[0].notes


def test_our_own_cover_comes_from_the_worker_with_the_spoken_title(client, db):
    series = book(db, chapters=2)
    db.add(Transcript(audio_asset_id="c1".ljust(16, "0"), version=2, language="te-IN", status="approved",
                      text="బారిష్టర్ పార్వతీశం. మొదటి భాగం.", source_audio_checksum="0" * 64))
    db.commit()
    token = make_worker(db)
    editor(client, db)
    assert client.get(f"/api/studio/series/{series.id}").json()["suggestedCoverTitle"] == "బారిష్టర్ పార్వతీశం"
    assert client.post(f"/api/studio/series/{series.id}/cover/generate").json()["cover"]["pending"] is True
    assert client.post(f"/api/studio/series/{series.id}/cover/generate").status_code == 409  # one at a time

    lease = run_job(client, token, "artwork", {"key": "<cover.jpg>", "provider": "local-sdxl", "model": "sdxl"},
                    files={"cover.jpg": jpeg()})
    assert lease["payload"] == {"seriesId": series.id} and lease["inputs"]["assetId"] == "c1".ljust(16, "0")
    db.expire_all()
    series = db.get(Series, series.id)
    assert series.artwork_kind == "own-cover" and series.cover_title == "బారిష్టర్ పార్వతీశం"
    assert series.artwork_key.endswith("-own-cover.jpg") and series.artwork_source == covers.OWN_COVER_SOURCE
    page = client.get("/api/studio/series").json()["items"][0]
    assert page["cover"]["pending"] is False and page["cover"]["kind"] == "own-cover"

    removed = client.delete(f"/api/studio/series/{series.id}/cover").json()
    assert removed["cover"]["url"] is None  # chapters show their own artwork again


def test_a_claimed_book_comes_down_and_back_in_one_step(client, db):
    series = book(db, chapters=3)
    db.commit()
    editor(client, db)
    taken = client.post(f"/api/studio/series/{series.id}/withdraw", json={"reason": "Claim from the publisher"}).json()
    assert taken["withdrawn"] == 3 and taken["published"] == 0 and taken["withdrawnReason"] == "Claim from the publisher"
    assert {a.status for a in db.scalars(select(AudioAsset).where(AudioAsset.series_id == series.id))} == {"withdrawn"}

    listener(client, db)
    assert client.get(f"/api/books/{series.id}").status_code == 404
    assert client.get(f"/api/stories/{'c1'.ljust(16, '0')}").status_code == 404

    editor(client, db)
    back = client.post(f"/api/studio/series/{series.id}/restore").json()
    assert back["published"] == 3 and back["withdrawnAt"] is None
    listener(client, db)
    assert client.get(f"/api/books/{series.id}").json()["chapterCount"] == 3
