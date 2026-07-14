"""add interview billable boundary

Revision ID: 20260715_0021
Revises: 20260715_0020
Create Date: 2026-07-15
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260715_0021"
down_revision: Union[str, None] = "20260715_0020"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "product_interviews",
        sa.Column("billable_started_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "product_interviews",
        sa.Column("billable_event_id", sa.String(36), nullable=True),
    )
    op.create_index(
        "ix_product_interviews_billable_started",
        "product_interviews",
        ["billable_started_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_product_interviews_billable_started", table_name="product_interviews")
    op.drop_column("product_interviews", "billable_event_id")
    op.drop_column("product_interviews", "billable_started_at")
