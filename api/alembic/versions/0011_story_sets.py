"""story sets: the catalog's free-text collections become real, always-visible collections

Revision ID: 0011
Revises: 0010
"""
import json
import re

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None

# Spellings of the same set: every variant is rewritten to the canonical name (story collection and album).
MERGES = {
    "Paropakari Papanna": "Paropakaari Papanna",
    "Paropakaari Paapanna": "Paropakaari Papanna",
    "Balamitra Kadalu": "Balamitra Kathalu",
}

TELUGU = {
    "Chandamama": "చందమామ", "Neeti Kathalu": "నీతి కథలు", "Amma Neeti Kadalu": "అమ్మ నీతి కథలు",
    "Tenali Ramakrishna": "తెనాలి రామకృష్ణ", "Akbar Birbal": "అక్బర్ బీర్బల్", "Chitti Potti Kathalu": "చిట్టి పొట్టి కథలు",
    "Panchatantra Kathalu": "పంచతంత్ర కథలు", "Paropakaari Papanna": "పరోపకారి పాపన్న", "Balamitra Kathalu": "బాలమిత్ర కథలు",
    "Kathalante Maakistam": "కథలంటే మాకిష్టం", "Paramanandayya Sishyulu": "పరమానందయ్య శిష్యులు",
    "Bhetala Kathalu": "బేతాళ కథలు", "Chitti Chitti Kathalu": "చిట్టి చిట్టి కథలు", "Demon Stories": "రాక్షస కథలు",
    "Amaravathi Kathalu": "అమరావతి కథలు", "Bommala Pinni": "బొమ్మల పిన్ని", "Eetaram Kathalu": "ఈతరం కథలు",
    "Legends of Mahabharatam": "మహాభారత గాథలు",
}


def _key(name: str) -> str:
    return " ".join(name.split()).casefold()


def _natural(title: str) -> list:
    """TR6 before TR10: numbers in a title sort as numbers."""
    return [int(part) if part.isdigit() else part.casefold() for part in re.split(r"(\d+)", title or "")]


def promote(bind) -> None:
    for old, new in MERGES.items():
        bind.execute(sa.text("UPDATE audio_assets SET album = :new WHERE album = :old"), {"old": old, "new": new})
        bind.execute(sa.text("UPDATE audio_assets SET collection = :new WHERE collection = :old"), {"old": old, "new": new})
    rows = bind.execute(sa.text(
        "SELECT id, title, collection FROM audio_assets WHERE status = 'published' AND series_id IS NULL "
        "AND coalesce(trim(collection), '') <> ''")).all()
    groups: dict[str, list] = {}
    names: dict[str, str] = {}
    for asset_id, title, collection in rows:
        key = _key(collection)
        names.setdefault(key, " ".join(collection.split()))
        groups.setdefault(key, []).append((title, asset_id))
    existing = {_key(title): collection_id for collection_id, title in bind.execute(sa.text(
        "SELECT id, titles->>'en-IN' FROM collections WHERE titles ? 'en-IN'")).all()}
    for key, stories in groups.items():
        name = names[key]
        variants = [name, *(old for old, new in MERGES.items() if new == name)]
        collection_id = existing.get(key)
        if collection_id:  # an editor already made this collection: it becomes the set, keeping their titles
            bind.execute(sa.text(
                "UPDATE collections SET kind = 'set', published = true, source_names = :names WHERE id = :id"),
                {"names": variants, "id": collection_id})
            bind.execute(sa.text("DELETE FROM collection_items WHERE collection_id = :id"), {"id": collection_id})
        else:
            titles = {"en-IN": name, **({"te-IN": TELUGU[name]} if name in TELUGU else {})}
            collection_id = bind.execute(sa.text(
                "INSERT INTO collections (kind, titles, descriptions, published, source_names, created_by) "
                "VALUES ('set', CAST(:titles AS jsonb), '{}'::jsonb, true, :names, 'migration:0011') RETURNING id"),
                {"titles": json.dumps(titles, ensure_ascii=False), "names": variants}).scalar_one()
        ordered = sorted(stories, key=lambda pair: _natural(pair[0]))
        for position, (_, asset_id) in enumerate(ordered):
            bind.execute(sa.text("INSERT INTO collection_items (collection_id, audio_asset_id, position) "
                                 "VALUES (:c, :a, :p) ON CONFLICT DO NOTHING"),
                         {"c": collection_id, "a": asset_id, "p": position})


def upgrade() -> None:
    op.add_column("collections", sa.Column("source_names", postgresql.ARRAY(sa.Text()), nullable=False,
                                           server_default=sa.text("'{}'::text[]")))
    promote(op.get_bind())


def downgrade() -> None:
    # Spelling merges are not undone.
    op.execute("DELETE FROM collections WHERE kind = 'set' AND created_by = 'migration:0011'")
    op.execute("UPDATE collections SET kind = 'theme' WHERE kind = 'set'")
    op.drop_column("collections", "source_names")
