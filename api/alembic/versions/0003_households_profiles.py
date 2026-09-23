"""households and profiles; listening data keyed by profile

Revision ID: 0003
Revises: 0002
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

LISTENING_TABLES = {
    "listener_favorites": ("listener_favorites_pkey", ["audio_asset_id"]),
    "listening_progress": ("listening_progress_pkey", ["audio_asset_id"]),
    "listening_daily": ("listening_daily_pkey", ["day"]),
}


def upgrade() -> None:
    op.create_table(
        "households",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("owner_user_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="CASCADE"),
                  nullable=False, unique=True),
        sa.Column("name", sa.String(120)),
        sa.Column("parental_pin_hash", sa.Text()),
        sa.Column("onboarded_at", sa.DateTime(timezone=True)),
        sa.Column("moments", postgresql.ARRAY(sa.String(16)), server_default="{}", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "profiles",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("household_id", sa.BigInteger(), sa.ForeignKey("households.id", ondelete="CASCADE"),
                  nullable=False, index=True),
        sa.Column("name", sa.String(60), nullable=False),
        sa.Column("kind", sa.String(8), server_default="adult", nullable=False),
        sa.Column("age_band", sa.String(8)),
        sa.Column("avatar", sa.String(24), server_default="peacock", nullable=False),
        sa.Column("listening_languages", postgresql.ARRAY(sa.String(16)),
                  server_default=sa.text("ARRAY['te-IN']::varchar[]"), nullable=False),
        sa.Column("queue", postgresql.ARRAY(sa.String(32)), server_default="{}", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
    )
    # Every existing account gets a household with one adult profile.
    op.execute("INSERT INTO households (owner_user_id, name) SELECT id, COALESCE(display_name, username, email) FROM users")
    op.execute("INSERT INTO profiles (household_id, name, kind, listening_languages) "
               "SELECT h.id, COALESCE(u.display_name, u.username, 'Me'), 'adult', u.listening_languages "
               "FROM households h JOIN users u ON u.id = h.owner_user_id")
    for table, (pkey, rest) in LISTENING_TABLES.items():
        op.add_column(table, sa.Column("profile_id", sa.BigInteger(),
                                       sa.ForeignKey("profiles.id", ondelete="CASCADE")))
        op.execute(f"UPDATE {table} t SET profile_id = p.id FROM households h JOIN profiles p ON p.household_id = h.id "
                   f"WHERE h.owner_user_id = t.user_id")
        op.alter_column(table, "profile_id", nullable=False)
        op.drop_constraint(pkey, table, type_="primary")
        op.create_primary_key(pkey, table, ["profile_id", *rest])
        op.create_index(f"ix_{table}_user_id", table, ["user_id"])
    for table in ("listening_progress", "listening_daily"):
        op.add_column(table, sa.Column("screen_off_seconds", sa.Float(), server_default="0", nullable=False))


def downgrade() -> None:
    for table in ("listening_progress", "listening_daily"):
        op.drop_column(table, "screen_off_seconds")
    for table, (pkey, rest) in LISTENING_TABLES.items():
        op.drop_index(f"ix_{table}_user_id", table_name=table)
        op.drop_constraint(pkey, table, type_="primary")
        # Keep one row per account (the owner's adult profile) when collapsing back to user keys.
        op.execute(f"DELETE FROM {table} t USING profiles p WHERE p.id = t.profile_id AND p.kind <> 'adult'")
        op.create_primary_key(pkey, table, ["user_id", *rest])
        op.drop_column(table, "profile_id")
    op.drop_table("profiles")
    op.drop_table("households")
