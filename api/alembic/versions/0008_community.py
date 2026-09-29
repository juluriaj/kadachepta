"""Phase 3: ratings, reviews, follows, embeddings, collections, imagination prompts

Revision ID: 0008
Revises: 0007
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None

JSONB = postgresql.JSONB()
NOW = sa.text("now()")
EMPTY = sa.text("'{}'::jsonb")


def upgrade() -> None:
    # One rating per listener (profile) per story. Adults rate the story and the narration (1-5);
    # children tap an emoji reaction, which is shown to parents but kept out of the scores.
    op.create_table(
        "story_ratings",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("profile_id", sa.BigInteger, sa.ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("household_id", sa.BigInteger, sa.ForeignKey("households.id", ondelete="CASCADE"), nullable=False),
        sa.Column("audio_asset_id", sa.String(32), sa.ForeignKey("audio_assets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("story_rating", sa.SmallInteger),
        sa.Column("narration_rating", sa.SmallInteger),
        sa.Column("reaction", sa.String(16)),
        sa.Column("weight", sa.Float, nullable=False, server_default="1"),
        sa.Column("excluded", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.UniqueConstraint("profile_id", "audio_asset_id", name="uq_story_ratings_profile_asset"),
        sa.CheckConstraint("story_rating BETWEEN 1 AND 5", name="ck_story_rating"),
        sa.CheckConstraint("narration_rating BETWEEN 1 AND 5", name="ck_narration_rating"),
    )
    op.create_index("ix_story_ratings_asset", "story_ratings", ["audio_asset_id", "created_at"])

    # A burst of ratings that doesn't look like normal listening: held out of the scores until an editor decides.
    op.create_table(
        "rating_flags",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("audio_asset_id", sa.String(32), sa.ForeignKey("audio_assets.id", ondelete="CASCADE"), nullable=False,
                  index=True),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("details", JSONB, nullable=False, server_default=EMPTY),
        sa.Column("status", sa.String(16), nullable=False, server_default="open"),  # open | cleared | confirmed
        sa.Column("resolved_by", sa.Text),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
    )

    op.create_table(
        "reviews",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("profile_id", sa.BigInteger, sa.ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("household_id", sa.BigInteger, sa.ForeignKey("households.id", ondelete="CASCADE"), nullable=False),
        sa.Column("audio_asset_id", sa.String(32), sa.ForeignKey("audio_assets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("text", sa.Text, nullable=False),
        # pending (waiting for the automatic check) | published | held (editor decides) | rejected | hidden
        sa.Column("status", sa.String(16), nullable=False, server_default="pending", index=True),
        sa.Column("moderation", JSONB, nullable=False, server_default=EMPTY),
        sa.Column("reply", sa.Text),
        sa.Column("reply_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.UniqueConstraint("profile_id", "audio_asset_id", name="uq_reviews_profile_asset"),
    )
    op.create_index("ix_reviews_asset", "reviews", ["audio_asset_id", "status"])
    op.create_table(
        "review_reports",
        sa.Column("review_id", sa.BigInteger, sa.ForeignKey("reviews.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("household_id", sa.BigInteger, sa.ForeignKey("households.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("reason", sa.String(24), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
    )

    op.create_table(
        "narrator_follows",
        sa.Column("user_id", sa.BigInteger, sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("narrator_user_id", sa.BigInteger, sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
    )
    op.create_index("ix_narrator_follows_narrator", "narrator_follows", ["narrator_user_id"])

    # Story embeddings for "because you finished" (pgvector; the dimension follows the model).
    op.create_table(
        "story_embeddings",
        sa.Column("audio_asset_id", sa.String(32), sa.ForeignKey("audio_assets.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("model", sa.Text, nullable=False),
        sa.Column("source_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
    )
    op.execute("ALTER TABLE story_embeddings ADD COLUMN embedding vector NOT NULL")

    op.create_table(
        "collections",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("kind", sa.String(16), nullable=False, server_default="theme"),  # festival | theme | age
        sa.Column("titles", JSONB, nullable=False, server_default=EMPTY),  # {"te-IN": ..., "en-IN": ...}
        sa.Column("descriptions", JSONB, nullable=False, server_default=EMPTY),
        sa.Column("starts_on", sa.Date),
        sa.Column("ends_on", sa.Date),
        sa.Column("position", sa.Integer, nullable=False, server_default="0"),
        sa.Column("published", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("created_by", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
    )
    op.create_table(
        "collection_items",
        sa.Column("collection_id", sa.BigInteger, sa.ForeignKey("collections.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("audio_asset_id", sa.String(32), sa.ForeignKey("audio_assets.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("position", sa.Integer, nullable=False, server_default="0"),
    )

    # Conversation starters for parents: {"texts": {"te-IN": [...], "en-IN": [...]}, "status", "by", "model"}
    op.add_column("audio_assets", sa.Column("imagination_prompts", JSONB, nullable=False, server_default=EMPTY))


def downgrade() -> None:
    op.drop_column("audio_assets", "imagination_prompts")
    for table in ("collection_items", "collections", "story_embeddings", "narrator_follows", "review_reports",
                  "reviews", "rating_flags", "story_ratings"):
        op.drop_table(table)
