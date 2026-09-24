"""narrator studio and automated pipeline: settings, series, uploads, notifications, review fields

Revision ID: 0004
Revises: 0003
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

JSONB_EMPTY = sa.text("'{}'::jsonb")


def upgrade() -> None:
    op.create_table(
        "app_settings",
        sa.Column("key", sa.String(64), primary_key=True),
        sa.Column("value", postgresql.JSONB(), nullable=False),
        sa.Column("updated_by", sa.Text()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "series",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("language", sa.String(16), nullable=False, server_default="te-IN"),
        sa.Column("narrator_user_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="SET NULL"), index=True),
        sa.Column("created_by", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "uploads",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("filename", sa.Text(), nullable=False),
        sa.Column("purpose", sa.String(16), nullable=False, server_default="audio"),
        sa.Column("total_bytes", sa.BigInteger(), nullable=False),
        sa.Column("received_bytes", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(16), nullable=False, server_default="open"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "notifications",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("body", sa.Text()),
        sa.Column("audio_asset_id", sa.String(32), sa.ForeignKey("audio_assets.id", ondelete="CASCADE")),
        sa.Column("read_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.add_column("audio_assets", sa.Column("pipeline_stage", sa.String(24), nullable=False, server_default="none"))
    op.add_column("audio_assets", sa.Column("pipeline_error", sa.Text()))
    op.add_column("audio_assets", sa.Column("ready_for_review_at", sa.DateTime(timezone=True)))
    op.add_column("audio_assets", sa.Column("changes_requested", postgresql.JSONB(), nullable=False,
                                            server_default=JSONB_EMPTY))
    op.add_column("audio_assets", sa.Column("captions_enabled", sa.Boolean(), nullable=False,
                                            server_default=sa.text("false")))
    op.add_column("audio_assets", sa.Column("source_text", sa.Text()))
    op.add_column("audio_assets", sa.Column("series_id", sa.BigInteger(),
                                            sa.ForeignKey("series.id", ondelete="SET NULL")))
    op.add_column("audio_assets", sa.Column("series_position", sa.Integer()))
    op.create_index("ix_audio_assets_pipeline_stage", "audio_assets", ["pipeline_stage"])
    op.create_index("ix_audio_assets_series_id", "audio_assets", ["series_id"])

    op.add_column("narrator_profiles", sa.Column("trust_level", sa.String(16), nullable=False, server_default="new"))
    op.add_column("narrator_profiles", sa.Column("agreement_version", sa.String(16)))
    op.add_column("narrator_profiles", sa.Column("agreement_accepted_at", sa.DateTime(timezone=True)))
    op.add_column("narrator_profiles", sa.Column("onboarded_at", sa.DateTime(timezone=True)))
    op.add_column("narrator_profiles", sa.Column("sample_key", sa.Text()))

    op.add_column("asset_rights", sa.Column("attestation", postgresql.JSONB(), nullable=False,
                                            server_default=JSONB_EMPTY))
    op.add_column("asset_rights", sa.Column("evidence_key", sa.Text()))

    op.add_column("transcripts", sa.Column("confidence", sa.Float()))
    op.add_column("transcripts", sa.Column("quality", postgresql.JSONB(), nullable=False, server_default=JSONB_EMPTY))
    op.add_column("transcripts", sa.Column("intro_removed", sa.Text()))

    op.add_column("teaser_drafts", sa.Column("safety", postgresql.JSONB(), nullable=False, server_default=JSONB_EMPTY))
    op.add_column("teaser_drafts", sa.Column("suggestions", postgresql.JSONB(), nullable=False,
                                             server_default=JSONB_EMPTY))

    # Existing stories: published and rejected ones already have a final pipeline position.
    op.execute("UPDATE audio_assets SET pipeline_stage = status WHERE status IN ('published', 'rejected')")
    op.execute("UPDATE audio_assets SET pipeline_stage = 'published' WHERE status = 'archived'")
    # Narrators who were set up before onboarding existed count as onboarded.
    op.execute("UPDATE narrator_profiles SET onboarded_at = now()")


def downgrade() -> None:
    for column in ("safety", "suggestions"):
        op.drop_column("teaser_drafts", column)
    for column in ("confidence", "quality", "intro_removed"):
        op.drop_column("transcripts", column)
    for column in ("attestation", "evidence_key"):
        op.drop_column("asset_rights", column)
    for column in ("trust_level", "agreement_version", "agreement_accepted_at", "onboarded_at", "sample_key"):
        op.drop_column("narrator_profiles", column)
    op.drop_index("ix_audio_assets_series_id", "audio_assets")
    op.drop_index("ix_audio_assets_pipeline_stage", "audio_assets")
    for column in ("pipeline_stage", "pipeline_error", "ready_for_review_at", "changes_requested", "captions_enabled",
                   "source_text", "series_id", "series_position"):
        op.drop_column("audio_assets", column)
    for table in ("notifications", "uploads", "series", "app_settings"):
        op.drop_table(table)
