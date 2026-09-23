"""job priority

Revision ID: 0002
Revises: 0001
"""
import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("priority", sa.Integer(), server_default="50", nullable=False))
    op.drop_index("ix_jobs_ready", table_name="jobs")
    op.create_index("ix_jobs_ready", "jobs", ["status", "job_type", "priority", "run_after"])
    # Jobs created by the bulk backfill before priorities existed.
    op.execute("UPDATE jobs SET priority = 100 WHERE job_type = 'media.process' AND created_by = 'admin' "
               "AND status IN ('queued', 'failed')")
    op.execute("UPDATE jobs SET priority = 10 WHERE job_type = 'media.process' AND created_by <> 'admin' "
               "AND status IN ('queued', 'failed')")


def downgrade() -> None:
    op.drop_index("ix_jobs_ready", table_name="jobs")
    op.create_index("ix_jobs_ready", "jobs", ["status", "job_type", "run_after"])
    op.drop_column("jobs", "priority")
