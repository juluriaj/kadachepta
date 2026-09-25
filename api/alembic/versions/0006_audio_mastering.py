"""per-story mastering choice (P2-18)

Revision ID: 0006
Revises: 0005
"""
import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # NULL: decided automatically from the recording; full | light | none: an editor's choice for this story.
    op.add_column("audio_assets", sa.Column("audio_mastering", sa.String(8)))
    op.execute("DELETE FROM app_settings WHERE key = 'audio.noiseReduction'")  # replaced by audio.mastering


def downgrade() -> None:
    op.drop_column("audio_assets", "audio_mastering")
