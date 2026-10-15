"""series covers: one cover per audiobook, where it came from, and taking a whole book down

A book's cover (a scan of the printed book, or KathaChepta's own illustrated cover) stands for every chapter.
``cover_source`` records where it came from so a claim can be answered quickly; ``withdrawn_*`` record why a
book was taken down (its chapters get the status "withdrawn" and come back with "restore").

Revision ID: 0013
Revises: 0012
"""
import sqlalchemy as sa
from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("series", sa.Column("artwork_key", sa.Text()))
    op.add_column("series", sa.Column("artwork_updated_at", sa.DateTime(timezone=True)))
    op.add_column("series", sa.Column("artwork_kind", sa.String(16)))  # book-cover | own-cover
    op.add_column("series", sa.Column("artwork_source", sa.Text()))
    op.add_column("series", sa.Column("cover_title", sa.Text()))  # the title printed on our own cover
    op.add_column("series", sa.Column("withdrawn_at", sa.DateTime(timezone=True)))
    op.add_column("series", sa.Column("withdrawn_reason", sa.Text()))


def downgrade() -> None:
    op.execute("UPDATE audio_assets SET status = 'published' WHERE status = 'withdrawn'")
    for column in ("withdrawn_reason", "withdrawn_at", "cover_title", "artwork_source", "artwork_kind",
                   "artwork_updated_at", "artwork_key"):
        op.drop_column("series", column)
