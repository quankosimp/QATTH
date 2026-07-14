"""make AI task dispatch durable

Revision ID: 20260715_0027
Revises: 20260715_0026
Create Date: 2026-07-15
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260715_0027"
down_revision: Union[str, None] = "20260715_0026"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("outbox_events", sa.Column("deduplication_key", sa.String(255), nullable=True))
    op.add_column(
        "outbox_events",
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_unique_constraint("uq_outbox_events_deduplication_key", "outbox_events", ["deduplication_key"])
    op.create_index("ix_outbox_dispatch_available", "outbox_events", ["published_at", "available_at"])
    op.alter_column("outbox_events", "available_at", server_default=None)


def downgrade() -> None:
    op.drop_index("ix_outbox_dispatch_available", table_name="outbox_events")
    op.drop_constraint("uq_outbox_events_deduplication_key", "outbox_events", type_="unique")
    op.drop_column("outbox_events", "available_at")
    op.drop_column("outbox_events", "deduplication_key")
