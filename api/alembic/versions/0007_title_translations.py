"""story titles per app language (Epic L)

Revision ID: 0007
Revises: 0006
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # {"te-IN": {"text", "by", "from", "confirmed"}, ...}: see app/services/titles.py
    op.add_column("audio_assets", sa.Column("title_translations", postgresql.JSONB(), nullable=False,
                                            server_default=sa.text("'{}'::jsonb")))


def downgrade() -> None:
    op.drop_column("audio_assets", "title_translations")
