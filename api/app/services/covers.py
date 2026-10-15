"""Book covers: one cover for every chapter of an audiobook (series).

Two kinds:
  book-cover  a photo or scan of the printed book, uploaded in the studio with a note on where it came from,
              so a claim against it can be answered quickly (swap it for our own, or take the book down)
  own-cover   KathaChepta's own: the GPU worker paints an illustration in the house style and the title is set
              here in code. SDXL can't write Telugu, and Pillow lays out Telugu (conjuncts, vowel signs) only
              with libraqm, which needs FriBiDi (libfribidi0 in api/Dockerfile).
"""

from __future__ import annotations

import io
import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps, features
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import utcnow
from ..models import AudioAsset, EditorialEvent, Series, Transcript
from ..storage import get_storage
from . import titles

FONTS = Path(__file__).resolve().parents[1] / "assets" / "fonts"
TELUGU_FONT, LATIN_FONT = FONTS / "NotoSansTelugu_700Bold.ttf", FONTS / "DMSans_700Bold.ttf"
TELUGU = re.compile(r"[ఀ-౿]")
PAPER, INK, MUTED = (247, 238, 222), (74, 44, 24), (124, 92, 64)
SIZE = 1024
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
OWN_COVER_SOURCE = "KathaChepta's own cover: AI illustration in the house style, title set in Noto Sans Telugu"


class CoverError(ValueError):
    pass


def image_extension(data: bytes) -> str:
    """jpg, png, or webp from the file's first bytes; anything else is refused."""
    if data[:3] == b"\xff\xd8\xff":
        return "jpg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    raise CoverError("Upload a JPEG, PNG, or WebP image of the cover.")


def _font(path: Path, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(path), size, layout_engine=ImageFont.Layout.RAQM)


def _fit(draw: ImageDraw.ImageDraw, text: str, path: Path, width: float, height: float, start: int):
    """The largest font size (and one or two lines) at which ``text`` fits the box."""
    words = text.split()
    options = [[text]] + [[" ".join(words[:i]), " ".join(words[i:])] for i in range(1, len(words))]
    for size in range(start, 17, -2):
        font = _font(path, size)
        for lines in options:
            boxes = [draw.textbbox((0, 0), line, font=font) for line in lines]
            total = sum(b[3] - b[1] for b in boxes) + size * 0.25 * (len(lines) - 1)
            if max(b[2] - b[0] for b in boxes) <= width and total <= height:
                return font, lines
    font = _font(path, 18)
    return font, [text]


def compose_own_cover(illustration: bytes, title: str, subtitle: str | None = None) -> bytes:
    """The illustration with a paper band at the foot carrying the title (and the romanized title beneath)."""
    if not features.check("raqm"):
        raise CoverError("This server can't lay out Telugu text: Pillow needs libraqm and libfribidi0.")
    image = ImageOps.fit(Image.open(io.BytesIO(illustration)).convert("RGB"), (SIZE, SIZE))
    draw = ImageDraw.Draw(image)
    band = int(SIZE * 0.27)
    top = SIZE - band
    draw.rectangle([0, top, SIZE, SIZE], fill=PAPER)
    draw.line([(0, top), (SIZE, top)], fill=INK, width=4)

    title_font, lines = _fit(draw, title, TELUGU_FONT if TELUGU.search(title) else LATIN_FONT,
                             SIZE * 0.88, band * (0.56 if subtitle else 0.78), int(band * 0.42))
    sub_font = _font(TELUGU_FONT if subtitle and TELUGU.search(subtitle) else LATIN_FONT, int(band * 0.13))
    blocks = [(line, title_font, INK) for line in lines] + ([(subtitle, sub_font, MUTED)] if subtitle else [])
    heights = [draw.textbbox((0, 0), text, font=font)[3] - draw.textbbox((0, 0), text, font=font)[1]
               for text, font, _ in blocks]
    gap = int(band * 0.06)
    y = top + (band - sum(heights) - gap * (len(blocks) - 1)) / 2
    for (text, font, color), height in zip(blocks, heights, strict=True):
        left, upper, right, _ = draw.textbbox((0, 0), text, font=font)
        draw.text(((SIZE - (right - left)) / 2 - left, y - upper), text, font=font, fill=color)
        y += height + gap
    out = io.BytesIO()
    image.save(out, format="JPEG", quality=90, optimize=True)
    return out.getvalue()


def chapters(db: Session, series_id: int) -> list[AudioAsset]:
    return list(db.scalars(select(AudioAsset).where(AudioAsset.series_id == series_id, AudioAsset.status != "archived")
                           .order_by(AudioAsset.series_position.nulls_last(), AudioAsset.title)))


def suggested_title(db: Session, series: Series) -> str:
    """The Telugu title as the narrator says it at the start of the first chapters, else the series title."""
    if TELUGU.search(series.title):
        return series.title
    for chapter in chapters(db, series.id)[:3]:
        transcript = db.scalars(select(Transcript).where(Transcript.audio_asset_id == chapter.id)
                                .order_by(Transcript.version.desc())).first()
        spoken = titles.from_transcript(series.title, transcript.text) if transcript and transcript.text else None
        if spoken:
            return spoken
    return series.title


def event(db: Session, series: Series, action: str, actor: str, notes: str | None = None) -> None:
    db.add(EditorialEvent(entity_type="series", entity_id=str(series.id), action=action, actor=actor, notes=notes))


def set_cover(db: Session, series: Series, key: str, kind: str, source: str, actor: str) -> None:
    series.artwork_key, series.artwork_kind, series.artwork_source = key, kind, source
    series.artwork_updated_at = utcnow()
    event(db, series, f"series:{kind}", actor, f"{key} ({source})")


def save_book_cover(db: Session, series: Series, data: bytes, source: str, actor: str) -> str:
    if len(data) > MAX_UPLOAD_BYTES:
        raise CoverError("The image is larger than 10 MB.")
    key = f"series/{series.id}/{int(utcnow().timestamp())}-book-cover.{image_extension(data)}"
    get_storage().put_bytes(key, data)
    set_cover(db, series, key, "book-cover", source.strip(), actor)
    return key


def save_own_cover(db: Session, series: Series, illustration_key: str, actor: str) -> str:
    """Set the title on the worker's illustration and make it the book's cover."""
    illustration = get_storage().path(illustration_key).read_bytes()
    title = series.cover_title or suggested_title(db, series)
    subtitle = series.title if series.title != title else None
    key = f"series/{series.id}/{int(utcnow().timestamp())}-own-cover.jpg"
    get_storage().put_bytes(key, compose_own_cover(illustration, title, subtitle))
    if not series.cover_title:
        series.cover_title = title
    set_cover(db, series, key, "own-cover", OWN_COVER_SOURCE, actor)
    return key
