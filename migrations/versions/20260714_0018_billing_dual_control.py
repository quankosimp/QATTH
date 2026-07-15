"""add dual control for credit adjustments

Revision ID: 20260714_0018
Revises: 20260714_0017
Create Date: 2026-07-14
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "20260714_0018"
down_revision: Union[str, None] = "20260714_0017"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "product_credit_adjustment_approvals",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("requested_by_user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("approved_by_user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("target_user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("reference", sa.String(255), nullable=True),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("dual_control_required", sa.Boolean(), nullable=False),
        sa.Column("policy_threshold", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("decision_reason", sa.Text(), nullable=True),
        sa.Column("ledger_entry_id", sa.String(36), sa.ForeignKey("product_credit_ledger_entries.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("requested_by_user_id", "idempotency_key", name="uq_product_credit_adjustment_request"),
    )
    op.create_index(
        "ix_product_credit_adjustment_status_created",
        "product_credit_adjustment_approvals",
        ["status", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_product_credit_adjustment_status_created", table_name="product_credit_adjustment_approvals")
    op.drop_table("product_credit_adjustment_approvals")
