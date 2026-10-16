"""narrator ratings: grown-ups rate a narrator as a whole, not only the narration of each story

Keyed like follows ("id:<user>" or "name:<name>"), so narrators the catalog credits by name can be rated too.
Both kinds of rating feed the narrator's one narration score.

Revision ID: 0014
Revises: 0013
"""
import sqlalchemy as sa
from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "narrator_ratings",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("profile_id", sa.BigInteger(), sa.ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("household_id", sa.BigInteger(), sa.ForeignKey("households.id", ondelete="CASCADE"), nullable=False),
        sa.Column("narrator_key", sa.String(300), nullable=False),
        sa.Column("rating", sa.SmallInteger(), nullable=False),
        sa.Column("weight", sa.Float(), nullable=False, server_default="1"),
        sa.Column("excluded", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("profile_id", "narrator_key", name="uq_narrator_ratings_profile_narrator"),
        sa.CheckConstraint("rating BETWEEN 1 AND 5", name="ck_narrator_rating"),
    )
    op.create_index("ix_narrator_ratings_narrator_key", "narrator_ratings", ["narrator_key"])


def downgrade() -> None:
    op.drop_index("ix_narrator_ratings_narrator_key", table_name="narrator_ratings")
    op.drop_table("narrator_ratings")
