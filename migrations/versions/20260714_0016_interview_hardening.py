"""harden interview lifecycle and evaluation attempts

Revision ID: 20260714_0016
Revises: 20260714_0015
Create Date: 2026-07-14
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "20260714_0016"
down_revision: Union[str, None] = "20260714_0015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("product_interviews", sa.Column("ended_reason", sa.String(40), nullable=True))
    op.drop_constraint("uq_product_interview_report_rubric", "product_interview_reports", type_="unique")
    op.add_column("product_interview_reports", sa.Column("parent_report_id", sa.String(36), nullable=True))
    op.add_column("product_interview_reports", sa.Column("attempt_number", sa.Integer(), nullable=False, server_default="1"))
    op.add_column("product_interview_reports", sa.Column("model_configuration_id", sa.String(36), nullable=True))
    op.add_column("product_interview_reports", sa.Column("usage_json", sa.JSON(), nullable=True))
    op.add_column("product_interview_reports", sa.Column("estimated_cost_minor", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_product_interview_reports_parent",
        "product_interview_reports",
        "product_interview_reports",
        ["parent_report_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_unique_constraint(
        "uq_product_interview_report_attempt",
        "product_interview_reports",
        ["interview_id", "rubric_version", "attempt_number"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_product_interview_report_attempt", "product_interview_reports", type_="unique")
    op.drop_constraint("fk_product_interview_reports_parent", "product_interview_reports", type_="foreignkey")
    for column in ("estimated_cost_minor", "usage_json", "model_configuration_id", "attempt_number", "parent_report_id"):
        op.drop_column("product_interview_reports", column)
    op.create_unique_constraint(
        "uq_product_interview_report_rubric",
        "product_interview_reports",
        ["interview_id", "rubric_version"],
    )
    op.drop_column("product_interviews", "ended_reason")
