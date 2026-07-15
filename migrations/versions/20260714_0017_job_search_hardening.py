"""harden job search filters and provider lineage

Revision ID: 20260714_0017
Revises: 20260714_0016
Create Date: 2026-07-14
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "20260714_0017"
down_revision: Union[str, None] = "20260714_0016"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "product_job_catalog_maintenance_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("operation", sa.String(80), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("scanned_count", sa.Integer(), nullable=False),
        sa.Column("affected_count", sa.Integer(), nullable=False),
        sa.Column("error", sa.JSON(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_product_job_maintenance_operation_created",
        "product_job_catalog_maintenance_runs",
        ["operation", "created_at"],
    )
    for name, column in (
        ("provider_run_id", sa.String(255)),
        ("provider_model", sa.String(160)),
        ("provider_model_configuration_id", sa.String(36)),
        ("provider_usage", sa.JSON()),
        ("provider_estimated_cost_minor", sa.Integer()),
    ):
        op.add_column("product_job_search_runs", sa.Column(name, column, nullable=True))
    for name, column in (
        ("explanation_provider", sa.String(80)),
        ("explanation_model", sa.String(160)),
        ("explanation_model_configuration_id", sa.String(36)),
        ("explanation_prompt_version", sa.String(80)),
        ("explanation_provider_run_id", sa.String(255)),
        ("explanation_usage", sa.JSON()),
        ("explanation_estimated_cost_minor", sa.Integer()),
    ):
        op.add_column("product_job_search_results", sa.Column(name, column, nullable=True))


def downgrade() -> None:
    for column in (
        "explanation_estimated_cost_minor",
        "explanation_usage",
        "explanation_provider_run_id",
        "explanation_prompt_version",
        "explanation_model_configuration_id",
        "explanation_model",
        "explanation_provider",
    ):
        op.drop_column("product_job_search_results", column)
    for column in (
        "provider_estimated_cost_minor",
        "provider_usage",
        "provider_model_configuration_id",
        "provider_model",
        "provider_run_id",
    ):
        op.drop_column("product_job_search_runs", column)
    op.drop_index("ix_product_job_maintenance_operation_created", table_name="product_job_catalog_maintenance_runs")
    op.drop_table("product_job_catalog_maintenance_runs")
