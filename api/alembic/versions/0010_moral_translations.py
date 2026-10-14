"""the idea behind a story (moral) per app language

Revision ID: 0010
Revises: 0009
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # {"te-IN": {"text", "by", "from"}, ...}: see app/services/morals.py
    op.add_column("audio_assets", sa.Column("moral_translations", postgresql.JSONB(), nullable=False,
                                            server_default=sa.text("'{}'::jsonb")))


def downgrade() -> None:
    op.drop_column("audio_assets", "moral_translations")
