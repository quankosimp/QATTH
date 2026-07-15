"""enforce a single open billing catalog schedule tail

Revision ID: 20260715_0025
Revises: 20260715_0024
Create Date: 2026-07-15
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260715_0025"
down_revision: Union[str, None] = "20260715_0024"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        WITH ordered AS (
            SELECT id,
                   LEAD(effective_from) OVER (
                       PARTITION BY market, currency
                       ORDER BY effective_from, id
                   ) AS next_effective_from
            FROM product_billing_catalog_versions
            WHERE status = 'active'
        )
        UPDATE product_billing_catalog_versions
        SET effective_to = (
            SELECT next_effective_from
            FROM ordered
            WHERE ordered.id = product_billing_catalog_versions.id
        )
        WHERE id IN (
            SELECT id FROM ordered WHERE next_effective_from IS NOT NULL
        )
          AND effective_to IS NULL
        """
    )
    op.create_index(
        "uq_product_billing_catalog_open_tail",
        "product_billing_catalog_versions",
        ["market", "currency"],
        unique=True,
        postgresql_where=sa.text("status = 'active' AND effective_to IS NULL"),
        sqlite_where=sa.text("status = 'active' AND effective_to IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_product_billing_catalog_open_tail", table_name="product_billing_catalog_versions")
