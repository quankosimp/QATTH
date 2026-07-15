"""add payment reconciliation lifecycle fields

Revision ID: 20260715_0020
Revises: 20260714_0019
Create Date: 2026-07-15
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260715_0020"
down_revision: Union[str, None] = "20260714_0019"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "product_payment_event_inbox",
        sa.Column("raw_payload_purged_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "product_payment_event_inbox",
        sa.Column("processing_started_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_product_payment_event_retention",
        "product_payment_event_inbox",
        ["raw_payload_expires_at", "raw_payload_purged_at"],
    )
    op.create_index(
        "ix_product_payment_event_processing",
        "product_payment_event_inbox",
        ["status", "processing_started_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_product_payment_event_processing", table_name="product_payment_event_inbox")
    op.drop_index("ix_product_payment_event_retention", table_name="product_payment_event_inbox")
    op.drop_column("product_payment_event_inbox", "processing_started_at")
    op.drop_column("product_payment_event_inbox", "raw_payload_purged_at")
