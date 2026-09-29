"""listener playlists

Revision ID: 0009
Revises: 0008
"""
import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None

NOW = sa.text("now()")


def upgrade() -> None:
    # Playlists belong to one listener profile (a parent's "Car trip", a child's "Bedtime favourites").
    op.create_table(
        "playlists",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("profile_id", sa.BigInteger, sa.ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
    )
    op.create_table(
        "playlist_items",
        sa.Column("playlist_id", sa.BigInteger, sa.ForeignKey("playlists.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("audio_asset_id", sa.String(32), sa.ForeignKey("audio_assets.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("position", sa.Integer, nullable=False, server_default="0"),
        sa.Column("added_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
    )


def downgrade() -> None:
    op.drop_table("playlist_items")
    op.drop_table("playlists")
