"""What the public website shows: the published catalog as plain values, its URLs, and the old site's links.

Only titles, teasers, narrators' names and artwork are public. Audio and transcripts stay behind sign-in.
Chapters have no page of their own: like Home in the app, the site shows each book once.
"""

from __future__ import annotations

import hashlib
import io
import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageOps
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import AudioAsset, Collection, TeaserDraft
from ..storage import get_storage
from . import story_sets
from .assets import narrator_people
from .titles import clean_source, confirmed_titles

SITE_FILES = Path(__file__).parents[1] / "site"
OLD_URLS: dict[str, str] = json.loads((SITE_FILES / "old_urls.json").read_text(encoding="utf-8"))
# What the page says about a book or collection, by its English title, until editors write their own.
DESCRIPTIONS: dict[str, dict[str, str]] = json.loads((SITE_FILES / "descriptions.json").read_text(encoding="utf-8"))
THUMB_WIDTHS = (320, 640)


def slugify(text: str, fallback: str) -> str:
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-")[:60].strip("-") or fallback


def _version(moment: datetime | None) -> int | None:
    return int(moment.timestamp()) if moment else None


@dataclass(frozen=True)
class Art:
    key: str
    version: int | None


@dataclass(frozen=True)
class Story:
    id: str
    title: str
    title_te: str | None
    title_en: str | None
    short_te: str | None
    long_te: str | None
    short_en: str | None
    long_en: str | None
    narrators: tuple[str, ...]
    seconds: float
    age: str | None
    published_at: datetime | None
    updated_at: datetime
    art: Art | None
    book_id: int | None
    chapter: int | None

    @property
    def path(self) -> str:
        return f"/stories/{slugify(self.title, 'story')}-{self.id}"

    @property
    def minutes(self) -> int:
        return max(1, round(self.seconds / 60))

    @property
    def heading(self) -> str:
        return self.title_te or self.title

    @property
    def subtitle(self) -> str | None:
        """The romanized title people search for, with its English meaning when that says something different."""
        names = [name for name in (self.title if self.title_te else None, self.title_en)
                 if name and name != self.heading]
        return " · ".join(dict.fromkeys(names)) or None


@dataclass(frozen=True)
class Group:
    """A book or a story set: the fields both kinds of page need."""
    id: int
    kind: str  # "book" | "set"
    title: str
    title_te: str | None
    about_te: str | None
    about_en: str | None
    stories: tuple[Story, ...]
    art: Art | None

    @property
    def path(self) -> str:
        section = "books" if self.kind == "book" else "collections"
        return f"/{section}/{slugify(self.title, section)}-{self.id}"

    @property
    def heading(self) -> str:
        return self.title_te or self.title

    @property
    def subtitle(self) -> str | None:
        return self.title if self.title_te else None

    @property
    def count_label(self) -> str:
        singular, plural = ("chapter", "chapters") if self.kind == "book" else ("story", "stories")
        count = len(self.stories)
        return f"{count} {singular if count == 1 else plural}"

    @property
    def seconds(self) -> float:
        return sum(story.seconds for story in self.stories)

    @property
    def hours(self) -> str:
        hours = self.seconds / 3600
        return f"{hours:.1f}".removesuffix(".0") if hours >= 1 else f"{max(1, round(self.seconds / 60))} min"

    @property
    def narrators(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(name for story in self.stories for name in story.narrators))

    @property
    def updated_at(self) -> datetime:
        return max(story.updated_at for story in self.stories)


@dataclass(frozen=True)
class Catalog:
    stories: dict[str, Story]  # every public story, chapters included
    books: dict[int, Group]
    sets: dict[int, Group]

    @property
    def standalone(self) -> list[Story]:
        return sorted((story for story in self.stories.values() if story.book_id is None), key=lambda s: s.title.casefold())

    @property
    def newest(self) -> list[Story]:
        return sorted((story for story in self.stories.values() if story.book_id is None and story.published_at),
                      key=lambda s: s.published_at, reverse=True)

    def book_named(self, title: str) -> Group | None:
        return next((book for book in self.books.values() if book.title == title), None)

    def set_named(self, title: str) -> Group | None:
        return next((group for group in self.sets.values() if group.title == title), None)

    def art(self, kind: str, identifier: str) -> Art | None:
        if kind == "story":
            story = self.stories.get(identifier)
            return story.art if story else None
        groups = {"book": self.books, "set": self.sets}.get(kind)
        group = groups.get(int(identifier)) if groups is not None and identifier.isdigit() else None
        return group.art if group else None


def _story(asset: AudioAsset, teaser: TeaserDraft, chapter: int | None) -> Story:
    versions = {teaser.language: {"short": teaser.short_text, "long": teaser.long_text}, **(teaser.alternates or {})}
    telugu, english = versions.get("te-IN") or {}, versions.get("en-IN") or {}
    titles = confirmed_titles(asset)
    return Story(
        id=asset.id, title=clean_source(asset.title), title_te=titles.get("te-IN"), title_en=titles.get("en-IN"),
        short_te=telugu.get("short"), long_te=telugu.get("long"), short_en=english.get("short"), long_en=english.get("long"),
        narrators=tuple(person["name"] for person in narrator_people(asset)), seconds=asset.duration_seconds or 0,
        age=asset.audience_age_range, published_at=asset.published_at, updated_at=asset.updated_at,
        art=Art(asset.artwork_key, _version(asset.artwork_updated_at)) if asset.artwork_key else None,
        book_id=asset.series_id, chapter=chapter)


def build(db: Session, pairs: list[tuple[AudioAsset, TeaserDraft]]) -> Catalog:
    """Plain values, so a snapshot can outlive the database session. `pairs` are the stories an adult listener can hear."""
    pairs = [pair for pair in pairs if not (pair[0].series_id and pair[0].series and pair[0].series.withdrawn_at)]
    raw_books = story_sets.books_of(db, pairs)
    stories = {asset.id: _story(asset, teaser, None) for asset, teaser in pairs if not asset.series_id}
    telugu_names = {story_sets.name_key(source): collection.titles.get("te-IN")
                    for collection in db.scalars(select(Collection).where(Collection.kind == story_sets.SET_KIND))
                    for source in collection.source_names}

    books: dict[int, Group] = {}
    for series_id, book in raw_books.items():
        chapters = tuple(_story(asset, teaser, number) for number, (asset, teaser) in enumerate(book.chapters, 1))
        stories.update({chapter.id: chapter for chapter in chapters})
        art = Art(book.series.artwork_key, _version(book.series.artwork_updated_at)) if book.series.artwork_key \
            else next((chapter.art for chapter in chapters if chapter.art), None)
        about = DESCRIPTIONS.get(book.series.title, {})
        books[series_id] = Group(id=series_id, kind="book", title=book.series.title,
                                 title_te=book.series.cover_title or telugu_names.get(story_sets.name_key(book.series.title)),
                                 about_te=about.get("te"), about_en=book.series.description or about.get("en"),
                                 stories=chapters, art=art)

    sets: dict[int, Group] = {}
    for collection, members in story_sets.listed_sets(db, pairs):
        chosen = tuple(stories[asset.id] for asset, _ in members)
        title = story_sets.set_title(collection)
        about = DESCRIPTIONS.get(title, {})
        sets[collection.id] = Group(id=collection.id, kind="set", title=title, title_te=collection.titles.get("te-IN"),
                                    about_te=collection.descriptions.get("te-IN") or about.get("te"),
                                    about_en=collection.descriptions.get("en-IN") or about.get("en"),
                                    stories=chosen, art=next((story.art for story in chosen if story.art), None))
    return Catalog(stories=stories, books=books, sets=sets)


def old_target(catalog: Catalog, address: str) -> tuple[str, str, int] | None:
    """Where a link into the old WordPress site goes now: (base, path, status), base being "site" or "app".

    A target that isn't public yet gets a temporary redirect to its section, so publishing it later needs no change.
    """
    target = OLD_URLS.get(address)
    if not target:
        return None
    kind, _, value = target.partition(":")
    if kind in ("page", "app"):
        return ("site" if kind == "page" else "app", value, 301)
    if kind == "book":
        book = catalog.book_named(value)
        return ("site", book.path, 301) if book else ("site", "/books", 302)
    if kind == "set":
        group = catalog.set_named(value)
        return ("site", group.path, 301) if group else ("site", "/collections", 302)
    story = catalog.stories.get(value)
    if story is None:
        return ("site", "/stories", 302)
    return ("site", catalog.books[story.book_id].path if story.book_id else story.path, 301)


def thumbnail(art: Art, width: int) -> Path:
    """A smaller copy of the artwork, made once: full-size art is too heavy for a page of covers."""
    storage = get_storage()
    name = hashlib.sha1(f"{art.key}:{art.version}:{width}".encode()).hexdigest()[:24]
    key = f"site-thumbs/{name[:2]}/{name}.jpg"
    if not storage.exists(key):
        with Image.open(storage.path(art.key)) as source:
            image = ImageOps.exif_transpose(source).convert("RGB")
        image.thumbnail((width, width))
        buffer = io.BytesIO()
        image.save(buffer, "JPEG", quality=76, optimize=True, progressive=True)
        storage.put_bytes(key, buffer.getvalue())
    return storage.path(key)
