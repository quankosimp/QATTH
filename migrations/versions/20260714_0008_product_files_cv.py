"""product files and cv lifecycle

Revision ID: 20260714_0008
Revises: 20260714_0007
Create Date: 2026-07-14
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "20260714_0008"
down_revision: Union[str, None] = "20260714_0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "product_file_assets",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("purpose", sa.String(40), nullable=False),
        sa.Column("original_filename", sa.String(255), nullable=False),
        sa.Column("content_type", sa.String(120), nullable=False),
        sa.Column("declared_size_bytes", sa.Integer(), nullable=False),
        sa.Column("actual_size_bytes", sa.Integer(), nullable=True),
        sa.Column("declared_sha256", sa.String(64), nullable=False),
        sa.Column("verified_sha256", sa.String(64), nullable=True),
        sa.Column("bucket", sa.String(255), nullable=False),
        sa.Column("object_key", sa.String(1024), nullable=False, unique=True),
        sa.Column("storage_backend", sa.String(32), nullable=False),
        sa.Column("upload_status", sa.String(24), nullable=False),
        sa.Column("security_status", sa.String(24), nullable=False),
        sa.Column("provider_etag", sa.String(255), nullable=True),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_product_file_assets_user_created", "product_file_assets", ["user_id", "created_at"])
    op.create_index("ix_product_file_assets_lifecycle", "product_file_assets", ["upload_status", "security_status", "expires_at"])

    op.create_table(
        "product_cvs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("active_version_id", sa.String(36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_product_cvs_user_status_created", "product_cvs", ["user_id", "status", "created_at"])

    op.create_table(
        "product_cv_scans",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("file_id", sa.String(36), sa.ForeignKey("product_file_assets.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("cv_id", sa.String(36), sa.ForeignKey("product_cvs.id", ondelete="SET NULL"), nullable=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("schema_version", sa.String(32), nullable=False),
        sa.Column("locale_hint", sa.String(16), nullable=True),
        sa.Column("provider", sa.String(40), nullable=True),
        sa.Column("provider_run_id", sa.String(255), nullable=True),
        sa.Column("error", sa.JSON(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("file_id", "schema_version", name="uq_product_cv_scan_file_schema"),
    )
    op.create_index("ix_product_cv_scans_user_status", "product_cv_scans", ["user_id", "status"])

    op.create_table(
        "product_cv_drafts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("scan_id", sa.String(36), sa.ForeignKey("product_cv_scans.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("schema_version", sa.String(32), nullable=False),
        sa.Column("content", sa.JSON(), nullable=False),
        sa.Column("field_confidence", sa.JSON(), nullable=False),
        sa.Column("warnings", sa.JSON(), nullable=False),
        sa.Column("checksum", sa.String(64), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "product_cv_versions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("cv_id", sa.String(36), sa.ForeignKey("product_cvs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_scan_id", sa.String(36), sa.ForeignKey("product_cv_scans.id", ondelete="SET NULL"), nullable=True),
        sa.Column("source_file_id", sa.String(36), sa.ForeignKey("product_file_assets.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("schema_version", sa.String(32), nullable=False),
        sa.Column("content", sa.JSON(), nullable=False),
        sa.Column("checksum", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("cv_id", "version", name="uq_product_cv_version"),
        sa.UniqueConstraint("source_scan_id", name="uq_product_cv_version_source_scan"),
    )
    op.create_index("ix_product_cv_versions_user_created", "product_cv_versions", ["user_id", "created_at"])
    op.create_foreign_key("fk_product_cvs_active_version", "product_cvs", "product_cv_versions", ["active_version_id"], ["id"], ondelete="SET NULL")

    op.create_table(
        "product_cv_analyses",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("cv_version_id", sa.String(36), sa.ForeignKey("product_cv_versions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("scores", sa.JSON(), nullable=True),
        sa.Column("findings", sa.JSON(), nullable=True),
        sa.Column("provider", sa.String(40), nullable=True),
        sa.Column("provider_run_id", sa.String(255), nullable=True),
        sa.Column("error", sa.JSON(), nullable=True),
        sa.Column("credit_reservation_id", sa.String(36), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_product_cv_analyses_user_status", "product_cv_analyses", ["user_id", "status"])


def downgrade() -> None:
    op.drop_index("ix_product_cv_analyses_user_status", table_name="product_cv_analyses")
    op.drop_table("product_cv_analyses")
    op.drop_constraint("fk_product_cvs_active_version", "product_cvs", type_="foreignkey")
    op.drop_index("ix_product_cv_versions_user_created", table_name="product_cv_versions")
    op.drop_table("product_cv_versions")
    op.drop_table("product_cv_drafts")
    op.drop_index("ix_product_cv_scans_user_status", table_name="product_cv_scans")
    op.drop_table("product_cv_scans")
    op.drop_index("ix_product_cvs_user_status_created", table_name="product_cvs")
    op.drop_table("product_cvs")
    op.drop_index("ix_product_file_assets_lifecycle", table_name="product_file_assets")
    op.drop_index("ix_product_file_assets_user_created", table_name="product_file_assets")
    op.drop_table("product_file_assets")
