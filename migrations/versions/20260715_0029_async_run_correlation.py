"""persist correlation for asynchronous product runs

Revision ID: 20260715_0029
Revises: 20260715_0028
Create Date: 2026-07-15
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260715_0029"
down_revision: Union[str, None] = "20260715_0028"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_TABLES = (
    ("product_job_search_runs", "ix_product_job_search_runs_correlation"),
    ("product_recommendation_runs", "ix_product_recommendation_runs_correlation"),
    ("product_privacy_requests", "ix_product_privacy_requests_correlation"),
)


def upgrade() -> None:
    for table, index in _TABLES:
        op.add_column(table, sa.Column("correlation_id", sa.String(128), nullable=True))
        op.execute(sa.text(f"UPDATE {table} SET correlation_id = id WHERE correlation_id IS NULL"))
        op.alter_column(table, "correlation_id", existing_type=sa.String(128), nullable=False)
        op.create_index(index, table, ["correlation_id"])


def downgrade() -> None:
    for table, index in reversed(_TABLES):
        op.drop_index(index, table_name=table)
        op.drop_column(table, "correlation_id")
