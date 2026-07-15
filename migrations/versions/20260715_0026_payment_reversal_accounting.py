"""add cumulative payment reversal accounting and reviews

Revision ID: 20260715_0026
Revises: 20260715_0025
Create Date: 2026-07-15
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260715_0026"
down_revision: Union[str, None] = "20260715_0025"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "product_payment_reversal_states",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("provider", sa.String(40), nullable=False),
        sa.Column("period_reference", sa.String(255), nullable=False),
        sa.Column("bucket_id", sa.String(36), sa.ForeignKey("product_credit_buckets.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("original_amount_minor", sa.Integer(), nullable=False),
        sa.Column("reversed_amount_minor", sa.Integer(), nullable=False),
        sa.Column("reversed_credits", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("provider", "period_reference", name="uq_product_payment_reversal_period"),
        sa.UniqueConstraint("bucket_id", name="uq_product_payment_reversal_bucket"),
        sa.CheckConstraint("original_amount_minor > 0", name="ck_product_payment_reversal_original_positive"),
        sa.CheckConstraint("reversed_amount_minor >= 0", name="ck_product_payment_reversal_amount_nonnegative"),
        sa.CheckConstraint("reversed_credits >= 0", name="ck_product_payment_reversal_credits_nonnegative"),
    )
    op.create_table(
        "product_credit_account_reviews",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("account_id", sa.String(36), sa.ForeignKey("product_credit_accounts.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("provider", sa.String(40), nullable=False),
        sa.Column("provider_event_id", sa.String(255), nullable=False),
        sa.Column("reason", sa.String(80), nullable=False),
        sa.Column("debt_credits", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("provider", "provider_event_id", name="uq_product_credit_account_review_event"),
        sa.CheckConstraint("debt_credits > 0", name="ck_product_credit_account_review_debt_positive"),
    )
    op.create_index(
        "ix_product_credit_account_reviews_account_status",
        "product_credit_account_reviews",
        ["account_id", "status", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_product_credit_account_reviews_account_status", table_name="product_credit_account_reviews")
    op.drop_table("product_credit_account_reviews")
    op.drop_table("product_payment_reversal_states")
