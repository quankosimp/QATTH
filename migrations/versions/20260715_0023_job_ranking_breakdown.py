"""add auditable job ranking breakdown

Revision ID: 20260715_0023
Revises: 20260715_0022
Create Date: 2026-07-15
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260715_0023"
down_revision: Union[str, None] = "20260715_0022"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "product_job_search_results",
        sa.Column("score_breakdown", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
    )
    op.alter_column("product_job_search_results", "score_breakdown", server_default=None)


def downgrade() -> None:
    op.drop_column("product_job_search_results", "score_breakdown")
