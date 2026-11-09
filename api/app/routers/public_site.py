"""The public website at kathachepta.com: what search engines and first-time visitors see.

Plain server-rendered pages (the app itself is an empty page until JavaScript runs). Caddy serves this host by
adding /site to every path, so these routes never clash with the app's. Links and redirects use the public address.
"""

from __future__ import annotations

import json
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import unquote
from xml.sax.saxutils import escape

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, RedirectResponse, Response
from jinja2 import Environment, FileSystemLoader
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..models import Profile
from ..services import public_site
from ..services.public_site import Catalog, Group, Story
from ..storage import StorageError, get_storage
from .listener import published_stories

SITE_FILES = Path(__file__).parents[1] / "site"
templates = Environment(loader=FileSystemLoader(SITE_FILES / "templates"), autoescape=True, auto_reload=False)
router = APIRouter(prefix="/site", include_in_schema=False)

SITE_NAME = "KathaChepta"
PAGE_CACHE = {"Cache-Control": "public, max-age=300"}
ART_CACHE = {"Cache-Control": "public, max-age=31536000, immutable"}
CACHE_SECONDS = 300  # crawlers shouldn't cost a catalog query per page on a small server
HOME_STORIES = 12
HOME_SETS = 12
# WordPress's own addresses: gone for good, so search engines drop them.
GONE = re.compile(r"^(wp-|xmlrpc|feed$|comments/feed|.*/feed$|.*\.php$)")

_snapshot: tuple[float, Catalog] | None = None


def forget() -> None:
    global _snapshot
    _snapshot = None


def _catalog(db: Session) -> Catalog:
    global _snapshot
    now = time.monotonic()
    if _snapshot is None or now - _snapshot[0] > CACHE_SECONDS:
        _snapshot = (now, public_site.build(db, published_stories(db, Profile(kind="adult"))))
    return _snapshot[1]


def page(path: str):
    return router.api_route(path, methods=["GET", "HEAD"], response_class=HTMLResponse)


def _site() -> str:
    return get_settings().public_site_url.rstrip("/")


def _app() -> str:
    return get_settings().public_base_url.rstrip("/")


def _art_url(kind: str, identifier: Any, art: public_site.Art | None, width: int | None = None) -> str:
    if art is None:
        return f"{_site()}/logo.png"
    query = "&".join(part for part in (f"w={width}" if width else "", f"v={art.version}" if art.version else "") if part)
    return f"{_site()}/art/{kind}/{identifier}.jpg" + (f"?{query}" if query else "")


def _clip(text: str, limit: int = 158) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[:limit - 1].rsplit(" ", 1)[0].rstrip(" ,;:.") + "…"


def _duration(seconds: float) -> str:
    return f"PT{round(seconds)}S"


def _people(names: tuple[str, ...]) -> list[dict[str, str]]:
    return [{"@type": "Person", "name": name} for name in names]


def _breadcrumbs(*trail: tuple[str, str]) -> dict[str, Any]:
    return {"@type": "BreadcrumbList", "itemListElement": [
        {"@type": "ListItem", "position": number, "name": name, "item": f"{_site()}{path}"}
        for number, (name, path) in enumerate(trail, 1)]}


def _publisher() -> dict[str, Any]:
    return {"@type": "Organization", "name": SITE_NAME, "url": f"{_site()}/", "logo": f"{_site()}/logo.png"}


def _render(template: str, *, title: str, description: str, path: str, image: str | None = None,
            schema: list[dict[str, Any]] | None = None, og_type: str = "website", status: int = 200,
            indexable: bool = True, **context: Any) -> HTMLResponse:
    graph = {"@context": "https://schema.org", "@graph": schema} if schema else None
    # "<" can't appear raw in a script element: a title containing </script> must not end it.
    jsonld = json.dumps(graph, ensure_ascii=False, default=str).replace("<", "\\u003c") if graph else None
    html = templates.get_template(template).render(
        site=_site(), app=_app(), site_name=SITE_NAME, title=title, description=_clip(description),
        canonical=f"{_site()}{path}", image=image or f"{_site()}/logo.png", jsonld=jsonld, og_type=og_type,
        indexable=indexable, art=_art_url, **context)
    return HTMLResponse(html, status_code=status, headers=PAGE_CACHE if status == 200 else None)


def _moved(path: str) -> RedirectResponse:
    return RedirectResponse(f"{_site()}{path}", status_code=301)


def _not_found(catalog: Catalog) -> HTMLResponse:
    return _render("not_found.html", title=f"Page not found | {SITE_NAME}", path="/404", status=404, indexable=False,
                   description="This page isn't here any more. Browse Telugu audio stories on KathaChepta.",
                   books=list(catalog.books.values())[:6])


# --- Files search engines ask for ---

@router.api_route("/robots.txt", methods=["GET", "HEAD"])
def robots():
    return PlainTextResponse(f"User-agent: *\nAllow: /\n\nSitemap: {_site()}/sitemap.xml\n", headers=PAGE_CACHE)


def _url_entry(path: str, updated: datetime | None) -> str:
    modified = f"<lastmod>{updated.date().isoformat()}</lastmod>" if updated else ""
    return f"<url><loc>{escape(_site() + path)}</loc>{modified}</url>"


@router.api_route("/sitemap.xml", methods=["GET", "HEAD"])
def sitemap(db: Session = Depends(get_db)):
    catalog = _catalog(db)
    latest = max((story.updated_at for story in catalog.stories.values()), default=None)
    entries = [_url_entry(path, latest) for path in ("/", "/books", "/collections", "/stories")]
    entries += [_url_entry(group.path, group.updated_at) for group in [*catalog.books.values(), *catalog.sets.values()]]
    entries += [_url_entry(story.path, story.updated_at) for story in catalog.standalone]
    body = ('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
            + "".join(entries) + "</urlset>\n")
    return Response(body, media_type="application/xml", headers=PAGE_CACHE)


@router.api_route("/logo.png", methods=["GET", "HEAD"])
def logo():
    return FileResponse(SITE_FILES / "logo.png", media_type="image/png", headers=ART_CACHE)


@router.api_route("/favicon.ico", methods=["GET", "HEAD"])
def favicon():
    icon = get_settings().app_root / "favicon.ico"
    return FileResponse(icon if icon.is_file() else SITE_FILES / "logo.png", headers=PAGE_CACHE)


@router.api_route("/art/{kind}/{name}", methods=["GET", "HEAD"])
def artwork(kind: str, name: str, w: int | None = None, db: Session = Depends(get_db)):
    """Artwork of public stories and books only, under addresses that don't expire (app media links do)."""
    catalog = _catalog(db)
    art = catalog.art(kind, name.removesuffix(".jpg"))
    if art is None or (w is not None and w not in public_site.THUMB_WIDTHS):
        return _not_found(catalog)
    try:
        path = public_site.thumbnail(art, w) if w else get_storage().path(art.key)
    except (OSError, StorageError):
        return _not_found(catalog)
    return FileResponse(path, media_type="image/jpeg", headers=ART_CACHE)


# --- Pages ---

@page("")
@page("/")
def home(db: Session = Depends(get_db)):
    catalog = _catalog(db)
    sets = sorted(catalog.sets.values(), key=lambda group: -len(group.stories))
    website = {"@type": "WebSite", "name": SITE_NAME, "alternateName": "కథ చెప్తా", "url": f"{_site()}/", "inLanguage": ["te", "en"],
               "publisher": _publisher()}
    return _render("home.html", path="/", title=f"తెలుగు కథలు ఆడియో | Telugu Audio Stories for Kids | {SITE_NAME}",
                   description="Telugu audio stories for kids and families: Chandamama, Panchatantra, Tenali Ramakrishna, "
                               "Akbar Birbal and audiobooks, told by real narrators.",
                   schema=[website, _publisher()], books=sorted(catalog.books.values(), key=lambda b: -len(b.stories)),
                   sets=sets[:HOME_SETS], more_sets=len(sets) > HOME_SETS, newest=catalog.newest[:HOME_STORIES],
                   title_count=len(catalog.standalone) + len(catalog.books))


@page("/books")
def books(db: Session = Depends(get_db)):
    catalog = _catalog(db)
    groups = sorted(catalog.books.values(), key=lambda book: book.title.casefold())
    return _render("listing.html", path="/books", title=f"తెలుగు ఆడియో పుస్తకాలు | Telugu Audiobooks | {SITE_NAME}",
                   description="Telugu novels and long stories as audiobooks, read chapter by chapter by real narrators.",
                   heading="నవలలు", subheading="Telugu audiobooks", groups=groups, breadcrumb="Audiobooks",
                   schema=[{"@type": "CollectionPage", "name": "Telugu audiobooks", "url": f"{_site()}/books", "inLanguage": "te"},
                           _breadcrumbs(("Home", "/"), ("Audiobooks", "/books"))])


@page("/collections")
def collections(db: Session = Depends(get_db)):
    catalog = _catalog(db)
    groups = sorted(catalog.sets.values(), key=lambda group: -len(group.stories))
    return _render("listing.html", path="/collections", title=f"తెలుగు కథల సంపుటాలు | Telugu Story Collections | {SITE_NAME}",
                   description="Telugu story collections to listen to: Chandamama, Panchatantra, Tenali Ramakrishna, "
                               "Akbar Birbal, moral stories and more.",
                   heading="కథల సంపుటాలు", subheading="Telugu story collections", groups=groups, breadcrumb="Collections",
                   schema=[{"@type": "CollectionPage", "name": "Telugu story collections", "url": f"{_site()}/collections", "inLanguage": "te"},
                           _breadcrumbs(("Home", "/"), ("Collections", "/collections"))])


@page("/stories")
def stories(db: Session = Depends(get_db)):
    catalog = _catalog(db)
    return _render("stories.html", path="/stories", title=f"అన్ని తెలుగు కథలు | All Telugu Audio Stories | {SITE_NAME}",
                   description=f"Every Telugu audio story on {SITE_NAME}, from A to Z, with a short note on each.",
                   stories=catalog.standalone,
                   schema=[{"@type": "CollectionPage", "name": "All Telugu audio stories", "url": f"{_site()}/stories", "inLanguage": "te"},
                           _breadcrumbs(("Home", "/"), ("Stories", "/stories"))])


def _group_page(catalog: Catalog, group: Group, section: tuple[str, str]) -> HTMLResponse:
    count = len(group.stories)
    narrated = ", ".join(group.narrators[:3])
    about = group.about_en or group.title
    if group.kind == "book":
        kind_label = "Telugu audiobook"
        description = f"{about.rstrip('.')}. A Telugu audiobook in {count} chapters, narrated by {narrated}."
        work: dict[str, Any] = {"@type": "Audiobook", "readBy": _people(group.narrators), "duration": _duration(group.seconds)}
    else:
        kind_label = "Telugu audio stories"
        description = f"{about.rstrip('.')}. {count} Telugu audio stories, told by {narrated}."
        work = {"@type": "CollectionPage", "mainEntity": {"@type": "ItemList", "numberOfItems": count, "itemListElement": [
            {"@type": "ListItem", "position": number, "url": f"{_site()}{story.path}", "name": story.title}
            for number, story in enumerate(group.stories, 1)]}}
    image = _art_url(group.kind, group.id, group.art)
    work.update({"name": group.title, "url": f"{_site()}{group.path}", "inLanguage": "te", "image": image,
                 "description": _clip(group.about_en or description, 300), "publisher": _publisher()})
    if group.title_te:
        work["alternateName"] = group.title_te
    title = f"{group.title_te} | {group.title} | {kind_label} | {SITE_NAME}" if group.title_te else f"{group.title} | {kind_label} | {SITE_NAME}"
    return _render("group.html", path=group.path, title=title, description=description, image=image,
                   og_type="book" if group.kind == "book" else "website", group=group, kind_label=kind_label, section=section,
                   open_url=f"{_app()}/{'book' if group.kind == 'book' else 'collection'}/{group.id}",
                   schema=[work, _breadcrumbs(("Home", "/"), section, (group.title, group.path))])


def _trailing_id(slug: str) -> int | None:
    last = slug.rsplit("-", 1)[-1]
    return int(last) if last.isdigit() else None


def _redirect_old(catalog: Catalog, address: str) -> Response | None:
    found = public_site.old_target(catalog, address)
    if found is None:
        return None
    base, path, status = found
    return RedirectResponse(f"{_site() if base == 'site' else _app()}{path}", status_code=status)


@page("/books/{slug}")
def book(slug: str, db: Session = Depends(get_db)):
    catalog = _catalog(db)
    group = catalog.books.get(_trailing_id(slug) or 0)
    if group is None:
        return _not_found(catalog)
    if group.path != f"/books/{slug}":
        return _moved(group.path)
    return _group_page(catalog, group, ("Audiobooks", "/books"))


@page("/collections/{slug}")
def collection(slug: str, db: Session = Depends(get_db)):
    catalog = _catalog(db)
    group = catalog.sets.get(_trailing_id(slug) or 0)
    if group is None:
        return _not_found(catalog)
    if group.path != f"/collections/{slug}":
        return _moved(group.path)
    return _group_page(catalog, group, ("Collections", "/collections"))


def _related(catalog: Catalog, story: Story) -> tuple[Group | None, list[Story]]:
    home_set = next((group for group in catalog.sets.values() if any(item.id == story.id for item in group.stories)), None)
    return home_set, [item for item in home_set.stories if item.id != story.id][:6] if home_set else []


@page("/stories/{slug}")
def story_page(slug: str, db: Session = Depends(get_db)):
    catalog = _catalog(db)
    if slug.isdigit():  # the old site's /stories/<post id>
        return _redirect_old(catalog, f"stories/{slug}") or _not_found(catalog)
    story = catalog.stories.get(slug.rsplit("-", 1)[-1])
    if story is None:
        return _not_found(catalog)
    if story.book_id:  # chapters are read through their book
        return _moved(catalog.books[story.book_id].path)
    if story.path != f"/stories/{slug}":
        return _moved(story.path)
    home_set, related = _related(catalog, story)
    image = _art_url("story", story.id, story.art)
    trail = [("Home", "/"), *([("Collections", "/collections"), (home_set.title, home_set.path)] if home_set else [("Stories", "/stories")]),
             (story.title, story.path)]
    work: dict[str, Any] = {"@type": "ShortStory", "name": story.title, "url": f"{_site()}{story.path}", "inLanguage": "te", "image": image,
                            "description": _clip(story.long_en or story.short_en or story.title, 300), "contributor": _people(story.narrators),
                            "timeRequired": _duration(story.seconds), "publisher": _publisher()}
    if story.title_te:
        work["alternateName"] = story.title_te
    if story.age:
        work["typicalAgeRange"] = story.age
    if story.published_at:
        work["datePublished"] = story.published_at.date().isoformat()
    if home_set:
        work["isPartOf"] = {"@type": "CreativeWorkSeries", "name": home_set.title, "url": f"{_site()}{home_set.path}"}
    title = f"{story.title_te} | {story.title} | {SITE_NAME}" if story.title_te else f"{story.title} | Telugu Audio Story | {SITE_NAME}"
    return _render("story.html", path=story.path, title=title, description=f"{story.short_en or story.title} Listen in Telugu on {SITE_NAME}.",
                   image=image, og_type="article", story=story, home_set=home_set, related=related, open_url=f"{_app()}/story/{story.id}",
                   schema=[work, _breadcrumbs(*trail)])


@router.api_route("/{rest:path}", methods=["GET", "HEAD"])
def everything_else(rest: str, db: Session = Depends(get_db)):
    """Links from the old site, then addresses that end in a slash, then a real 404 (not a redirect to Home)."""
    catalog = _catalog(db)
    address = unquote(rest).strip("/").lower()
    redirect = _redirect_old(catalog, address)
    if redirect is not None:
        return redirect
    if GONE.match(address):
        return PlainTextResponse("Gone.", status_code=410)
    if rest.endswith("/") and rest.strip("/"):
        return _moved("/" + rest.strip("/"))
    return _not_found(catalog)
