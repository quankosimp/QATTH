"""add recommendation feedback events

Revision ID: 20260715_0022
Revises: 20260715_0021
Create Date: 2026-07-15
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260715_0022"
down_revision: Union[str, None] = "20260715_0021"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "product_recommendation_feedback",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "run_id",
            sa.String(36),
            sa.ForeignKey("product_recommendation_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "match_id",
            sa.String(36),
            sa.ForeignKey("product_recommendation_matches.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("job_id", sa.String(36), sa.ForeignKey("product_jobs.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("event_type", sa.String(40), nullable=False),
        sa.Column("reason_code", sa.String(80), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("taxonomy_version", sa.String(40), nullable=False),
        sa.Column("ranking_version", sa.String(40), nullable=False),
        sa.Column("experiment_assignment", sa.JSON(), nullable=False),
        sa.Column("context_snapshot", sa.JSON(), nullable=False),
        sa.Column("training_eligible", sa.Boolean(), nullable=False),
        sa.Column("training_consent_snapshot", sa.JSON(), nullable=False),
        sa.Column("idempotency_key", sa.String(255), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("user_id", "idempotency_key", name="uq_product_recommendation_feedback_idempotency"),
    )
    op.create_index(
        "ix_product_recommendation_feedback_run_event",
        "product_recommendation_feedback",
        ["run_id", "event_type", "created_at"],
    )
    op.create_index(
        "ix_product_recommendation_feedback_user_created",
        "product_recommendation_feedback",
        ["user_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_product_recommendation_feedback_user_created", table_name="product_recommendation_feedback")
    op.drop_index("ix_product_recommendation_feedback_run_event", table_name="product_recommendation_feedback")
    op.drop_table("product_recommendation_feedback")
