"""Story sets (standalone stories of one character or series) and audiobooks (chapters heard in order)."""

import importlib.util
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.models import AudioAsset, Collection, CollectionItem, ListeningProgress, Series
from app.services import story_sets

from .conftest import API_ROOT, login, make_asset, make_user

MIGRATION = API_ROOT / "alembic" / "versions" / "0011_story_sets.py"


def _migration():
    spec = importlib.util.spec_from_file_location("migration_0011", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def story(db, asset_id: str, collection: str | None = None, **fields) -> AudioAsset:
    return make_asset(db, asset_id, ready_to_publish=True, status="published", collection=collection, album=collection,
                      **fields)


def listener(client, db, name: str = "amma"):
    make_user(db, name, "listener")
    login(client, name)


def hear(client, asset_id: str, position: float, completed: bool = False):
    response = client.post("/api/me/listening", json={"assetId": asset_id, "seconds": 5, "position": position,
                                                      "started": True, "completed": completed})
    assert response.status_code == 200, response.text


def book(db, title: str = "Barister Parvateesam", chapters: int = 3, prefix: str = "c") -> Series:
    series = Series(title=title, description="A lawyer's adventures.")
    db.add(series)
    db.flush()
    for position in range(1, chapters + 1):
        story(db, f"{prefix}{position}".ljust(16, "0"), title, title=f"{title} {position}", series_id=series.id,
              series_position=position)
    return series


# --- Promoting the catalog's free-text collections (migration 0011) ---

def test_migration_promotes_collections_and_merges_spellings(db):
    story(db, "p1".ljust(16, "0"), "Paropakaari Papanna", title="Papanna 2")
    story(db, "p2".ljust(16, "0"), "Paropakari Papanna", title="Papanna 10")
    story(db, "p3".ljust(16, "0"), "Paropakaari Paapanna", title="Papanna 1")
    story(db, "b1".ljust(16, "0"), "Balamitra Kadalu")
    story(db, "b2".ljust(16, "0"), "Balamitra Kathalu")
    story(db, "t1".ljust(16, "0"), "Tenali  Ramakrishna", title="TR10.Nalla Kukka")
    story(db, "t2".ljust(16, "0"), "tenali ramakrishna", title="TR6.Vikatakavi")
    make_asset(db, "d1".ljust(16, "0"), collection="Paropakari Papanna")  # a draft: renamed, not in the set yet
    book(db, "Chandamama Ramayanam", chapters=2)  # chapters belong to their book, not to a set
    editors = Collection(kind="theme", titles={"en-IN": "Tenali Ramakrishna", "te-IN": "తెనాలి"}, published=False)
    db.add(editors)
    db.flush()
    db.add(CollectionItem(collection_id=editors.id, audio_asset_id="t1".ljust(16, "0"), position=0))
    db.commit()

    _migration().promote(db.connection())
    db.commit()

    sets = {c.titles["en-IN"]: c for c in db.scalars(select(Collection).where(Collection.kind == "set"))}
    assert set(sets) == {"Paropakaari Papanna", "Balamitra Kathalu", "Tenali Ramakrishna"}
    papanna = sets["Paropakaari Papanna"]
    assert papanna.titles["te-IN"] == "పరోపకారి పాపన్న" and papanna.published
    assert set(papanna.source_names) == {"Paropakaari Papanna", "Paropakari Papanna", "Paropakaari Paapanna"}
    assert [item.audio_asset_id[:2] for item in papanna.items] == ["p3", "p1", "p2"]  # 1, 2, 10: numbers sort as numbers
    assert db.get(AudioAsset, "d1".ljust(16, "0")).collection == "Paropakaari Papanna"
    assert db.get(AudioAsset, "b1".ljust(16, "0")).album == "Balamitra Kathalu"
    tenali = sets["Tenali Ramakrishna"]
    assert tenali.id == editors.id and tenali.titles["te-IN"] == "తెనాలి"  # the editor's collection, kept
    assert [item.audio_asset_id[:2] for item in tenali.items] == ["t1", "t2"]  # the editor's order first


def test_publishing_a_story_adds_it_to_its_set(client, db):
    make_user(db, "ed", "editor")
    login(client, "ed")
    for asset_id in ("a1", "a2"):
        make_asset(db, asset_id.ljust(16, "0"), ready_to_publish=True, collection="Akbar  Birbal")
    series = Series(title="Akbar Birbal")
    db.add(series)
    db.commit()
    make_asset(db, "ch".ljust(16, "0"), ready_to_publish=True, collection="Akbar Birbal", series_id=series.id)
    for asset_id in ("a1", "a2", "ch"):
        assert client.post("/api/content/publish", json={"audioAssetId": asset_id.ljust(16, "0")}).status_code == 200
    db.expire_all()
    (only,) = db.scalars(select(Collection).where(Collection.kind == "set")).all()
    assert only.titles == {"en-IN": "Akbar Birbal"} and only.published
    assert [item.audio_asset_id[:2] for item in only.items] == ["a1", "a2"]


# --- Listener API: story sets ---

def test_story_set_list_page_and_home_shelf(client, db):
    for index in range(3):
        story(db, f"t{index}".ljust(16, "0"), "Tenali Ramakrishna", artwork_key=f"artworks/t{index}.png" if index else None)
    story(db, "s1".ljust(16, "0"), "Bedtime")
    db.add_all([Collection(kind="set", titles={"en-IN": "Tenali Ramakrishna"}, source_names=["Tenali Ramakrishna"],
                           published=True),
                Collection(kind="set", titles={"en-IN": "Bedtime"}, source_names=["Bedtime"], published=True)])
    db.commit()
    for asset in db.scalars(select(AudioAsset).where(AudioAsset.collection.is_not(None)).order_by(AudioAsset.id)).all():
        story_sets.join_set(db, asset)
    db.commit()
    listener(client, db)
    hear(client, "t2".ljust(16, "0"), 300, completed=True)

    (tenali,) = client.get("/api/collections").json()["items"]  # a set of one story isn't listed
    assert tenali["titles"] == {"en-IN": "Tenali Ramakrishna"} and tenali["storyCount"] == 3 and tenali["heard"] == 1
    assert "artworks/t1.png" in tenali["artworkUrl"]  # the first story with a picture
    page = client.get(f"/api/collections/{tenali['id']}").json()
    assert [s["id"][:2] for s in page["stories"]] == ["t0", "t1", "t2"]
    assert page["stories"][2]["progress"]["completed"] is True

    shelves = {shelf["id"]: shelf for shelf in client.get("/api/home").json()["shelves"]}
    assert [s["id"] for s in shelves["sets"]["sets"]] == [tenali["id"]] and shelves["sets"]["items"] == []
    assert not any(key.startswith("collection-") for key in shelves)  # sets are tiles, not rows of stories

    detail = client.get(f"/api/stories/{'t1'.ljust(16, '0')}").json()
    assert detail["storySet"] == {"id": tenali["id"], "titles": tenali["titles"], "storyCount": 3}
    assert [s["id"][:2] for s in detail["upNext"]] == ["t0", "t2"]  # wraps round; t2 is heard, so it comes last
    assert client.get(f"/api/stories/{'s1'.ljust(16, '0')}").json()["storySet"] is None


def test_unpublished_set_is_hidden(client, db):
    for index in range(2):
        story(db, f"t{index}".ljust(16, "0"), "Tenali Ramakrishna")
    hidden = Collection(kind="set", titles={"en-IN": "Tenali Ramakrishna"}, source_names=["Tenali Ramakrishna"],
                        published=False)
    db.add(hidden)
    db.flush()
    db.add_all([CollectionItem(collection_id=hidden.id, audio_asset_id=f"t{i}".ljust(16, "0"), position=i) for i in range(2)])
    db.commit()
    listener(client, db)
    assert client.get("/api/collections").json()["items"] == []
    assert client.get(f"/api/collections/{hidden.id}").status_code == 404


# --- Audiobooks ---

def test_chapters_stay_out_of_home_shelves_and_search(client, db):
    series = book(db, chapters=3)
    story(db, "st".ljust(16, "0"), "Neeti Kathalu", title="Kaaki Kadha")
    listener(client, db)
    shelves = {shelf["id"]: shelf for shelf in client.get("/api/home").json()["shelves"]}
    assert [s["id"][:2] for s in shelves["new"]["items"]] == ["st"]
    assert [s["id"][:2] for s in shelves["short"]["items"]] == ["st"]
    (summary,) = shelves["books"]["books"]
    assert summary["id"] == series.id and summary["chapterCount"] == 3 and summary["duration"] == 900
    assert summary["resume"] == {"state": "start", "chapterId": "c1".ljust(16, "0"), "chapter": 1, "position": 0,
                                 "remaining": 300}
    found = client.get("/api/search?q=parvateesam").json()
    assert found["items"] == [] and [b["id"] for b in found["books"]] == [series.id]
    found = client.get("/api/search?q=kaaki").json()
    assert [s["id"][:2] for s in found["items"]] == ["st"] and found["books"] == []


def test_book_resumes_where_the_profile_left_off(client, db):
    series = book(db, chapters=3)
    listener(client, db)
    url = f"/api/books/{series.id}"
    first, second, third = (f"c{n}".ljust(16, "0") for n in (1, 2, 3))

    hear(client, first, 120)
    page = client.get(url).json()
    assert page["resume"] == {"state": "continue", "chapterId": first, "chapter": 1, "position": 120, "remaining": 180}
    assert page["description"] == "A lawyer's adventures." and page["narrator"] == "KathaChepta"
    assert [c["book"] for c in page["chapters"]][1] == {"id": series.id, "title": "Barister Parvateesam",
                                                         "chapter": 2, "chapters": 3}
    assert page["chapters"][0]["progress"]["position"] == 120 and page["chapters"][1]["progress"] is None

    hear(client, first, 300, completed=True)
    assert client.get(url).json()["resume"]["chapterId"] == second  # the next chapter, from its start
    continuing = {s["id"]: s for s in client.get("/api/home").json()["shelves"]}["continue"]["items"]
    assert [(c["id"], c["book"]["chapter"]) for c in continuing] == [(second, 2)]  # the book once, at chapter 2

    hear(client, third, 298)  # stopped in the last seconds: as good as finished
    hear(client, second, 40)
    resume = client.get(url).json()["resume"]
    assert resume["chapterId"] == second and resume["remaining"] == 260
    hear(client, second, 300, completed=True)
    assert client.get(url).json()["resume"]["state"] == "finished"
    assert "continue" not in {s["id"] for s in client.get("/api/home").json()["shelves"]}


def test_chapter_page_knows_its_book_and_plays_on(client, db):
    series = book(db, chapters=3)
    listener(client, db)
    detail = client.get(f"/api/stories/{'c2'.ljust(16, '0')}").json()
    assert detail["book"] == {"id": series.id, "title": "Barister Parvateesam", "chapter": 2, "chapters": 3}
    assert [s["id"][:2] for s in detail["upNext"]] == ["c3"] and detail["upNext"][0]["book"]["chapter"] == 3
    assert detail["storySet"] is None
    assert client.get("/api/books/999").status_code == 404


def test_book_resume_rules():
    def asset(asset_id):
        return AudioAsset(id=asset_id, title=asset_id, duration_seconds=600)

    def row(asset_id, position, minutes_ago, completed=False):
        return ListeningProgress(audio_asset_id=asset_id, last_position=position, completed=completed,
                                 last_listened_at=datetime.now(timezone.utc) - timedelta(minutes=minutes_ago))

    chapters = [asset("1"), asset("2"), asset("3")]
    assert story_sets.book_resume(chapters, {})["state"] == "start"
    # Finished chapter 3 most recently, chapter 1 earlier, chapter 2 never: wrap round to chapter 2.
    progress = {"1": row("1", 600, 10, True), "3": row("3", 600, 1, True)}
    assert story_sets.book_resume(chapters, progress) == {"state": "continue", "index": 1, "position": 0.0}
    progress["2"] = row("2", 30, 20)
    assert story_sets.book_resume(chapters, progress) == {"state": "continue", "index": 1, "position": 30}
