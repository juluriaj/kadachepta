"""contact details on every account: phone and preferred contact channel

Revision ID: 0005
Revises: 0004
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("phone", sa.String(20)))
    op.add_column("users", sa.Column("contact_preferences", postgresql.JSONB(), nullable=False,
                                     server_default=sa.text("'{}'::jsonb")))


def downgrade() -> None:
    op.drop_column("users", "contact_preferences")
    op.drop_column("users", "phone")
