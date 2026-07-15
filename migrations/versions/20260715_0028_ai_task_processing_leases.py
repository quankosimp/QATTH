"""add AI task processing leases

Revision ID: 20260715_0028
Revises: 20260715_0027
Create Date: 2026-07-15
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260715_0028"
down_revision: Union[str, None] = "20260715_0027"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _add_lease(table: str, index: str) -> None:
    op.add_column(table, sa.Column("processing_lease_id", sa.String(255), nullable=True))
    op.add_column(table, sa.Column("processing_lease_expires_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index(index, table, ["status", "processing_lease_expires_at"])


def upgrade() -> None:
    _add_lease("product_cv_scans", "ix_product_cv_scans_processing_lease")
    _add_lease("product_cv_analyses", "ix_product_cv_analyses_processing_lease")
    _add_lease("product_interview_reports", "ix_product_interview_reports_processing_lease")


def downgrade() -> None:
    for table, index in (
        ("product_interview_reports", "ix_product_interview_reports_processing_lease"),
        ("product_cv_analyses", "ix_product_cv_analyses_processing_lease"),
        ("product_cv_scans", "ix_product_cv_scans_processing_lease"),
    ):
        op.drop_index(index, table_name=table)
        op.drop_column(table, "processing_lease_expires_at")
        op.drop_column(table, "processing_lease_id")
