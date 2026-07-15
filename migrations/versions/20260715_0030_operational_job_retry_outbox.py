"""add durable operational job retry outbox

Revision ID: 20260715_0030
Revises: 20260715_0029
Create Date: 2026-07-15
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260715_0030"
down_revision: Union[str, None] = "20260715_0029"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "product_operational_job_dispatches",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("job_id", sa.String(36), sa.ForeignKey("product_operational_jobs.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("task_name", sa.String(160), nullable=False),
        sa.Column("queue", sa.String(80), nullable=False),
        sa.Column("args_payload", sa.JSON(), nullable=False),
        sa.Column("correlation_id", sa.String(128), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_error", sa.String(120), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_product_operational_job_dispatches_pending",
        "product_operational_job_dispatches",
        ["status", "available_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_product_operational_job_dispatches_pending", table_name="product_operational_job_dispatches")
    op.drop_table("product_operational_job_dispatches")
