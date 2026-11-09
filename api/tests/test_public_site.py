"""The public website: what search engines see, what they must not see, and links from the old site."""

import io
import json
import re

import pytest
from PIL import Image

from app import storage
from app.models import AudioAsset, Collection, CollectionItem, Series, TeaserDraft
from app.routers import public_site
from app.services import public_site as site_data

from .conftest import make_asset

SITE = "https://kathachepta.com"
STORY_ID = "aa11".ljust(16, "0")
CHAPTER_IDS = ["cc01".ljust(16, "0"), "cc02".ljust(16, "0")]


@pytest.fixture(autouse=True)
def fresh_snapshot():
    public_site.forget()
    yield
    public_site.forget()


def story(db, asset_id, **fields):
    asset = make_asset(db, asset_id, status="published", ready_to_publish=True, narrator_name="Vimala Mare", **fields)
    teaser = db.query(TeaserDraft).filter(TeaserDraft.audio_asset_id == asset_id).one()
    teaser.alternates = {"en-IN": {"short": "A crow learns to share.", "long": "A clever crow learns to share with friends."}}
    db.commit()
    return asset


@pytest.fixture
def catalog(db):
    tale = story(db, STORY_ID, title="Bhale Kaaki", collection="Neeti Kathalu", album="Neeti Kathalu")
    other = story(db, "aa22".ljust(16, "0"), title="Gadusu Nakka", collection="Neeti Kathalu", album="Neeti Kathalu")
    tales = Collection(kind="set", titles={"en-IN": "Neeti Kathalu", "te-IN": "నీతి కథలు"}, source_names=["Neeti Kathalu"], published=True)
    db.add(tales)
    db.flush()
    db.add_all([CollectionItem(collection_id=tales.id, audio_asset_id=tale.id, position=0),
                CollectionItem(collection_id=tales.id, audio_asset_id=other.id, position=1)])
    book = Series(title="Barister Parvateesam", cover_title="బారిస్టర్ పార్వతీశం")
    db.add(book)
    db.flush()
    for position, chapter_id in enumerate(CHAPTER_IDS, 1):
        story(db, chapter_id, title=f"Chapter {position}", series_id=book.id, series_position=position)
    make_asset(db, "dd11".ljust(16, "0"), title="Secret Draft")
    db.commit()
    return {"book": book, "set": tales}


def jsonld(html: str) -> dict:
    return json.loads(re.search(r'<script type="application/ld\+json">(.*?)</script>', html, re.S).group(1))


def types(html: str) -> set[str]:
    return {item["@type"] for item in jsonld(html)["@graph"]}


def test_home_is_real_html_with_search_metadata(client, catalog):
    response = client.get("/site/")
    html = response.text
    assert response.status_code == 200 and response.headers["cache-control"].startswith("public")
    assert '<html lang="te">' in html and '<div id="root"></div>' not in html
    assert f'<link rel="canonical" href="{SITE}/">' in html and 'name="description"' in html and 'property="og:image"' in html
    assert "బారిస్టర్ పార్వతీశం" in html and "నీతి కథలు" in html
    assert {"WebSite", "Organization"} <= types(html)
    assert "Secret Draft" not in html


def test_story_page(client, catalog):
    slug = f"bhale-kaaki-{STORY_ID}"
    response = client.get(f"/site/stories/{slug}")
    html = response.text
    assert response.status_code == 200
    assert f'href="{SITE}/stories/{slug}"' in html and "A clever crow learns to share" in html and "Vimala Mare" in html
    assert "ShortStory" in types(html) and "BreadcrumbList" in types(html)
    assert f"/story/{STORY_ID}" in html
    # Audio and signed media links stay behind sign-in.
    assert "/media/" not in html and ".mp3" not in html and ".m4a" not in html


def test_wrong_slug_redirects_to_the_canonical_address(client, catalog):
    response = client.get(f"/site/stories/old-name-{STORY_ID}", follow_redirects=False)
    assert response.status_code == 301 and response.headers["location"] == f"{SITE}/stories/bhale-kaaki-{STORY_ID}"


def test_draft_is_not_public(client, catalog):
    assert client.get(f"/site/stories/secret-draft-{'dd11'.ljust(16, '0')}").status_code == 404
    assert "secret-draft" not in client.get("/site/sitemap.xml").text


def test_book_lists_chapters_in_order_and_chapters_have_no_page_of_their_own(client, catalog):
    book = catalog["book"]
    path = f"/books/barister-parvateesam-{book.id}"
    html = client.get(f"/site{path}").text
    assert "Audiobook" in types(html) and "Mokkapati Narasimha Sastry" in html
    assert html.index("అధ్యాయం 1") < html.index("అధ్యాయం 2")
    chapter = client.get(f"/site/stories/chapter-1-{CHAPTER_IDS[0]}", follow_redirects=False)
    assert chapter.status_code == 301 and chapter.headers["location"] == f"{SITE}{path}"
    assert CHAPTER_IDS[0] not in client.get("/site/stories").text


def test_collection_page(client, catalog):
    html = client.get(f"/site/collections/neeti-kathalu-{catalog['set'].id}").text
    assert "CollectionPage" in types(html) and "Gadusu Nakka" in html


def test_robots_and_sitemap(client, catalog):
    assert f"Sitemap: {SITE}/sitemap.xml" in client.get("/site/robots.txt").text
    response = client.get("/site/sitemap.xml")
    assert response.headers["content-type"].startswith("application/xml")
    for path in ("/books", f"/stories/bhale-kaaki-{STORY_ID}", f"/collections/neeti-kathalu-{catalog['set'].id}",
                 f"/books/barister-parvateesam-{catalog['book'].id}"):
        assert f"<loc>{SITE}{path}</loc>" in response.text
    assert CHAPTER_IDS[0] not in response.text


def test_pages_answer_head_requests(client, catalog):
    assert client.head("/site/").status_code == 200 and client.head("/site/robots.txt").status_code == 200


def test_titles_cannot_break_out_of_the_page(client, db):
    title = '</script><script>alert(1)</script>'
    story(db, "ee11".ljust(16, "0"), title=title)
    html = client.get(f"/site/stories/script-script-alert-1-script-{'ee11'.ljust(16, '0')}").text
    assert "<script>alert(1)" not in html
    assert jsonld(html)["@graph"][0]["name"] == title


def test_old_site_links(client, catalog, db, monkeypatch):
    monkeypatch.setitem(site_data.OLD_URLS, "stories/4242", f"story:{STORY_ID}")
    monkeypatch.setitem(site_data.OLD_URLS, "stories/4243", f"story:{'dd11'.ljust(16, '0')}")
    book = f"{SITE}/books/barister-parvateesam-{catalog['book'].id}"

    def get(path):
        return client.get(path, follow_redirects=False)

    assert (get("/site/barrister").status_code, get("/site/barrister").headers["location"]) == (301, book)
    assert get("/site/BARRISTER/").headers["location"] == book
    assert get("/site/stories/4242").headers["location"] == f"{SITE}/stories/bhale-kaaki-{STORY_ID}"
    # Not public yet: a temporary redirect, so publishing it later needs no change.
    unpublished = get("/site/stories/4243")
    assert (unpublished.status_code, unpublished.headers["location"]) == (302, f"{SITE}/stories")
    assert (get("/site/kanchukota").status_code, get("/site/kanchukota").headers["location"]) == (302, f"{SITE}/books")
    assert get("/site/login").headers["location"].endswith("/sign-in")


def test_unknown_addresses_are_real_errors(client, catalog):
    missing = client.get("/site/no-such-page")
    assert missing.status_code == 404 and missing.headers["content-type"].startswith("text/html") and "noindex" in missing.text
    assert client.get("/site/stories/99999999").status_code == 404
    for path in ("/site/wp-login.php", "/site/feed/", "/site/wp-content/uploads/Chapter-43.mp3", "/site/xmlrpc.php"):
        assert client.get(path).status_code == 410, path


def test_trailing_slash_redirects_without_exposing_the_internal_prefix(client, catalog):
    response = client.get("/site/books/", follow_redirects=False)
    assert response.status_code == 301 and response.headers["location"] == f"{SITE}/books"


def test_artwork_only_for_public_stories(client, db, catalog):
    key = "artworks/test/picture.jpg"
    path = storage.get_storage().path(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (1024, 1024), "orange").save(path, "JPEG")
    make_asset(db, "ff11".ljust(16, "0"), title="Hidden art", artwork_key=key)
    db.get(AudioAsset, STORY_ID).artwork_key = key
    db.commit()
    public_site.forget()

    full = client.get(f"/site/art/story/{STORY_ID}.jpg")
    assert full.status_code == 200 and full.headers["content-type"] == "image/jpeg" and "immutable" in full.headers["cache-control"]
    small = client.get(f"/site/art/story/{STORY_ID}.jpg?w=320")
    assert small.status_code == 200 and len(small.content) < len(full.content) * 2
    assert Image.open(io.BytesIO(small.content)).size == (320, 320)
    assert client.get(f"/site/art/story/{STORY_ID}.jpg?w=7").status_code == 404
    assert client.get(f"/site/art/story/{'ff11'.ljust(16, '0')}.jpg").status_code == 404  # a draft's artwork


def test_old_url_table_points_at_real_kinds():
    assert len(site_data.OLD_URLS) > 400
    assert {value.split(":")[0] for value in site_data.OLD_URLS.values()} == {"book", "set", "story", "page", "app"}
    assert "stories" not in site_data.OLD_URLS  # the new list page, never a redirect
