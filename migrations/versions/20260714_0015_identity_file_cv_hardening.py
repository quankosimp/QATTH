"""harden identity file and cv product boundaries

Revision ID: 20260714_0015
Revises: 20260714_0014
Create Date: 2026-07-14
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "20260714_0015"
down_revision: Union[str, None] = "20260714_0014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint("uq_product_cv_scan_file_schema", "product_cv_scans", type_="unique")
    op.add_column("product_cv_scans", sa.Column("parent_scan_id", sa.String(36), nullable=True))
    op.add_column("product_cv_scans", sa.Column("attempt_number", sa.Integer(), nullable=False, server_default="1"))
    op.create_foreign_key(
        "fk_product_cv_scans_parent",
        "product_cv_scans",
        "product_cv_scans",
        ["parent_scan_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_unique_constraint(
        "uq_product_cv_scan_file_schema_attempt",
        "product_cv_scans",
        ["file_id", "schema_version", "attempt_number"],
    )

    op.add_column("product_cv_analyses", sa.Column("parent_analysis_id", sa.String(36), nullable=True))
    op.add_column("product_cv_analyses", sa.Column("attempt_number", sa.Integer(), nullable=False, server_default="1"))
    op.add_column("product_cv_analyses", sa.Column("model_name", sa.String(255), nullable=True))
    op.add_column("product_cv_analyses", sa.Column("model_configuration_id", sa.String(36), nullable=True))
    op.add_column("product_cv_analyses", sa.Column("prompt_version", sa.String(80), nullable=True))
    op.add_column("product_cv_analyses", sa.Column("usage_json", sa.JSON(), nullable=True))
    op.add_column("product_cv_analyses", sa.Column("disclaimer", sa.Text(), nullable=True))
    op.create_foreign_key(
        "fk_product_cv_analyses_parent",
        "product_cv_analyses",
        "product_cv_analyses",
        ["parent_analysis_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_product_cv_analyses_parent", "product_cv_analyses", type_="foreignkey")
    for column in (
        "disclaimer",
        "usage_json",
        "prompt_version",
        "model_configuration_id",
        "model_name",
        "attempt_number",
        "parent_analysis_id",
    ):
        op.drop_column("product_cv_analyses", column)

    op.drop_constraint("uq_product_cv_scan_file_schema_attempt", "product_cv_scans", type_="unique")
    op.drop_constraint("fk_product_cv_scans_parent", "product_cv_scans", type_="foreignkey")
    op.drop_column("product_cv_scans", "attempt_number")
    op.drop_column("product_cv_scans", "parent_scan_id")
    op.create_unique_constraint(
        "uq_product_cv_scan_file_schema",
        "product_cv_scans",
        ["file_id", "schema_version"],
    )
