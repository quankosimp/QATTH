"""product privacy export and deletion workflows

Revision ID: 20260714_0013
Revises: 20260714_0012
"""

from alembic import op
import sqlalchemy as sa


revision = "20260714_0013"
down_revision = "20260714_0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("product_privacy_requests", sa.Column("id", sa.String(36), primary_key=True), sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False), sa.Column("request_type", sa.String(24), nullable=False), sa.Column("status", sa.String(32), nullable=False), sa.Column("idempotency_key", sa.String(255), nullable=False), sa.Column("request_hash", sa.String(64), nullable=False), sa.Column("reason", sa.Text()), sa.Column("checkpoints", sa.JSON(), nullable=False), sa.Column("retention_exceptions", sa.JSON(), nullable=False), sa.Column("error", sa.JSON()), sa.Column("attempts", sa.Integer(), nullable=False), sa.Column("lease_expires_at", sa.DateTime(timezone=True)), sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False), sa.Column("started_at", sa.DateTime(timezone=True)), sa.Column("completed_at", sa.DateTime(timezone=True)), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False), sa.UniqueConstraint("user_id", "request_type", "idempotency_key", name="uq_product_privacy_request_idempotency"))
    op.create_index("ix_product_privacy_requests_user_status", "product_privacy_requests", ["user_id", "status"])
    op.create_table("product_privacy_artifacts", sa.Column("id", sa.String(36), primary_key=True), sa.Column("request_id", sa.String(36), sa.ForeignKey("product_privacy_requests.id", ondelete="CASCADE"), nullable=False, unique=True), sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False), sa.Column("object_key", sa.String(1024), nullable=False, unique=True), sa.Column("content_type", sa.String(120), nullable=False), sa.Column("size_bytes", sa.Integer(), nullable=False), sa.Column("sha256", sa.String(64), nullable=False), sa.Column("encryption_version", sa.String(40), nullable=False), sa.Column("download_token_hash", sa.String(64)), sa.Column("download_token_expires_at", sa.DateTime(timezone=True)), sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False), sa.Column("deleted_at", sa.DateTime(timezone=True)), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_product_privacy_artifacts_expiry", "product_privacy_artifacts", ["expires_at", "deleted_at"])
    op.create_table("product_privacy_dispatches", sa.Column("id", sa.String(36), primary_key=True), sa.Column("request_id", sa.String(36), sa.ForeignKey("product_privacy_requests.id", ondelete="CASCADE"), nullable=False, unique=True), sa.Column("topic", sa.String(120), nullable=False), sa.Column("payload", sa.JSON(), nullable=False), sa.Column("status", sa.String(24), nullable=False), sa.Column("attempts", sa.Integer(), nullable=False), sa.Column("available_at", sa.DateTime(timezone=True), nullable=False), sa.Column("last_error", sa.Text()), sa.Column("published_at", sa.DateTime(timezone=True)), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_product_privacy_dispatches_pending", "product_privacy_dispatches", ["status", "available_at"])
    op.create_table("product_privacy_events", sa.Column("id", sa.String(36), primary_key=True), sa.Column("request_id", sa.String(36), sa.ForeignKey("product_privacy_requests.id", ondelete="CASCADE"), nullable=False), sa.Column("sequence", sa.Integer(), nullable=False), sa.Column("event_type", sa.String(80), nullable=False), sa.Column("payload", sa.JSON(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.UniqueConstraint("request_id", "sequence", name="uq_product_privacy_event_sequence"))
    op.create_index("ix_product_privacy_events_request_sequence", "product_privacy_events", ["request_id", "sequence"])
    op.create_table("product_deletion_tombstones", sa.Column("id", sa.String(36), primary_key=True), sa.Column("request_id", sa.String(36), sa.ForeignKey("product_privacy_requests.id", ondelete="RESTRICT"), nullable=False, unique=True), sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, unique=True), sa.Column("pseudonymous_subject", sa.String(64), nullable=False, unique=True), sa.Column("retention_exceptions", sa.JSON(), nullable=False), sa.Column("deletion_manifest", sa.JSON(), nullable=False), sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))


def downgrade() -> None:
    op.drop_table("product_deletion_tombstones")
    op.drop_table("product_privacy_events")
    op.drop_table("product_privacy_dispatches")
    op.drop_table("product_privacy_artifacts")
    op.drop_table("product_privacy_requests")
