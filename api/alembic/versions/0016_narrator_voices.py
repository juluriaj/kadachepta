"""narrator photos and bios, editor-narrator threads, thank-you notes to narrators, narrator rating alerts

- narrator_profiles: an approved photo, one waiting for an editor, and whether the narrator takes notes from families
- credited_narrators: the bio and photo editors add for narrators the catalog credits by name only
- submission_messages: the two-way thread on each submission between editors and its narrator (P3-11)
- narrator_messages, narrator_blocks: thank-you notes from grown-ups to narrators, and households a narrator blocked
- rating_flags: a burst of ratings for a narrator (narrator_key) as well as for a story (P3-13)

Revision ID: 0016
Revises: 0015
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("narrator_profiles", sa.Column("photo_key", sa.Text()))
    op.add_column("narrator_profiles", sa.Column("photo_pending_key", sa.Text()))
    op.add_column("narrator_profiles", sa.Column("photo_updated_at", sa.DateTime(timezone=True)))
    op.add_column("narrator_profiles", sa.Column("accepts_messages", sa.Boolean(), nullable=False,
                                                 server_default=sa.text("false")))
    op.create_table(
        "credited_narrators",
        sa.Column("narrator_key", sa.String(300), primary_key=True),
        sa.Column("biography", sa.Text()),
        sa.Column("photo_key", sa.Text()),
        sa.Column("photo_updated_at", sa.DateTime(timezone=True)),
        sa.Column("updated_by", sa.Text()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "submission_messages",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("audio_asset_id", sa.String(32), sa.ForeignKey("audio_assets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("author_user_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("author_role", sa.String(16), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_submission_messages_audio_asset_id", "submission_messages", ["audio_asset_id"])
    op.create_table(
        "narrator_messages",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("narrator_user_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("household_id", sa.BigInteger(), sa.ForeignKey("households.id", ondelete="CASCADE"), nullable=False),
        sa.Column("profile_id", sa.BigInteger(), sa.ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("audio_asset_id", sa.String(32), sa.ForeignKey("audio_assets.id", ondelete="SET NULL")),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("moderation", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("reply", sa.Text()),
        sa.Column("reply_at", sa.DateTime(timezone=True)),
        sa.Column("read_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_narrator_messages_narrator_user_id", "narrator_messages", ["narrator_user_id"])
    op.create_index("ix_narrator_messages_household_id", "narrator_messages", ["household_id"])
    op.create_index("ix_narrator_messages_status", "narrator_messages", ["status"])
    op.create_table(
        "narrator_blocks",
        sa.Column("narrator_user_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("household_id", sa.BigInteger(), sa.ForeignKey("households.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.alter_column("rating_flags", "audio_asset_id", nullable=True)
    op.add_column("rating_flags", sa.Column("narrator_key", sa.String(300)))
    op.create_index("ix_rating_flags_narrator_key", "rating_flags", ["narrator_key"])


def downgrade() -> None:
    op.drop_index("ix_rating_flags_narrator_key", table_name="rating_flags")
    op.drop_column("rating_flags", "narrator_key")
    op.execute("DELETE FROM rating_flags WHERE audio_asset_id IS NULL")
    op.alter_column("rating_flags", "audio_asset_id", nullable=False)
    op.drop_table("narrator_blocks")
    op.drop_table("narrator_messages")
    op.drop_table("submission_messages")
    op.drop_table("credited_narrators")
    for column in ("accepts_messages", "photo_updated_at", "photo_pending_key", "photo_key"):
        op.drop_column("narrator_profiles", column)
