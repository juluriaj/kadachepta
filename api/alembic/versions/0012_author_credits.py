"""author credits: authors named in a catalog story's narrator credit move to its source

The catalog's free-text narrator credit sometimes names the story's author beside the narrator
("Vimala Mare, Leo Tolstoy"). Splitting co-narrators gave those authors narrator pages. Only stories without a
narrator account are touched; each change is recorded as an editorial event with the previous values.

Revision ID: 0012
Revises: 0011
"""
import re

import sqlalchemy as sa
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None

ACTOR = "migration:0012"

# Confirmed by the editor: authors, not narrators.
AUTHORS = ["Leo Tolstoy", "Amar Goswami", "Deepa Agarwal", "Kamakshi Balasubramanyam"]

NAME_SEPARATORS = re.compile(r"\s*[,&/]\s*")  # as services/assets.py splits the credit


def _key(name: str) -> str:
    return " ".join(name.split()).casefold()


def _source(current: str | None, authors: list[str]) -> str | None:
    """Add "story by <author>" to the source, in the "<label>: <reference>" form narrator uploads use."""
    missing = [name for name in authors if _key(name) not in _key(current or "")]
    if not missing:
        return current
    credit = "story by " + " and ".join(missing)
    if not (current or "").strip():
        return credit[0].upper() + credit[1:]
    return f"{current}; {credit}" if ":" in current else f"{current}: {credit}"


def fix(bind) -> int:
    authors = {_key(name): name for name in AUTHORS}
    pattern = "|".join(r"\s+".join(map(re.escape, name.split())) for name in AUTHORS)
    rows = bind.execute(sa.text(
        "SELECT id, narrator_name, source_adaptation FROM audio_assets "
        "WHERE narrator_user_id IS NULL AND narrator_name ~* :pattern ORDER BY id"), {"pattern": pattern}).all()
    changed = 0
    for asset_id, credit, source in rows:
        names = [" ".join(name.split()) for name in NAME_SEPARATORS.split(credit) if name.strip()]
        removed = [authors[_key(name)] for name in names if _key(name) in authors]
        if not removed:
            continue
        narrators = ", ".join(name for name in names if _key(name) not in authors) or None
        new_source = _source(source, removed)
        bind.execute(sa.text(
            "UPDATE audio_assets SET narrator_name = :narrators, source_adaptation = :source, updated_at = now() "
            "WHERE id = :id"), {"id": asset_id, "narrators": narrators, "source": new_source})
        bind.execute(sa.text(
            "INSERT INTO editorial_events (entity_type, entity_id, action, actor, notes) "
            "VALUES ('audio_asset', :id, 'credits:corrected', :actor, :notes)"),
            {"id": asset_id, "actor": ACTOR,
             "notes": f"Narrator credit {credit!r} -> {narrators!r}; {' and '.join(removed)} is the author, "
                      f"not a narrator. Source {source!r} -> {new_source!r}."})
        changed += 1
    return changed


def upgrade() -> None:
    fix(op.get_bind())


def downgrade() -> None:
    # Data correction: not undone. The editorial events (actor migration:0012) keep the previous values.
    pass
