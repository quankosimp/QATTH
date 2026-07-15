"""add provider usage observability

Revision ID: 20260714_0019
Revises: 20260714_0018
Create Date: 2026-07-14
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "20260714_0019"
down_revision: Union[str, None] = "20260714_0018"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "product_provider_usage_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("provider", sa.String(40), nullable=False),
        sa.Column("purpose", sa.String(80), nullable=False),
        sa.Column("model", sa.String(160), nullable=True),
        sa.Column("model_configuration_id", sa.String(36), nullable=True),
        sa.Column("correlation_id", sa.String(128), nullable=False),
        sa.Column("resource_type", sa.String(80), nullable=False),
        sa.Column("resource_id", sa.String(80), nullable=False),
        sa.Column("provider_run_id", sa.String(255), nullable=True),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("usage_json", sa.JSON(), nullable=False),
        sa.Column("estimated_cost_minor", sa.Integer(), nullable=True),
        sa.Column("error_code", sa.String(120), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("provider", "provider_run_id", name="uq_product_provider_usage_run"),
    )
    op.create_index("ix_product_provider_usage_correlation", "product_provider_usage_events", ["correlation_id"])
    op.create_index("ix_product_provider_usage_provider_time", "product_provider_usage_events", ["provider", "purpose", "occurred_at"])
    op.create_index("ix_product_provider_usage_user_time", "product_provider_usage_events", ["user_id", "occurred_at"])


def downgrade() -> None:
    op.drop_index("ix_product_provider_usage_user_time", table_name="product_provider_usage_events")
    op.drop_index("ix_product_provider_usage_provider_time", table_name="product_provider_usage_events")
    op.drop_index("ix_product_provider_usage_correlation", table_name="product_provider_usage_events")
    op.drop_table("product_provider_usage_events")
