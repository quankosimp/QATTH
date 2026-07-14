"""product interview lifecycle

Revision ID: 20260714_0009
Revises: 20260714_0008
Create Date: 2026-07-14
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "20260714_0009"
down_revision: Union[str, None] = "20260714_0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "product_interviews",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("cv_version_id", sa.String(36), sa.ForeignKey("product_cv_versions.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("job_id", sa.String(36), nullable=True),
        sa.Column("target_role", sa.String(200), nullable=False),
        sa.Column("interview_type", sa.String(24), nullable=False),
        sa.Column("language", sa.String(8), nullable=False),
        sa.Column("duration_minutes", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("cv_snapshot", sa.JSON(), nullable=False),
        sa.Column("job_snapshot", sa.JSON(), nullable=True),
        sa.Column("plan_snapshot", sa.JSON(), nullable=False),
        sa.Column("rubric_version", sa.String(40), nullable=False),
        sa.Column("prompt_version", sa.String(40), nullable=False),
        sa.Column("gemini_model", sa.String(160), nullable=False),
        sa.Column("gemini_resumption_handle", sa.Text(), nullable=True),
        sa.Column("credit_reservation_id", sa.String(36), nullable=True),
        sa.Column("failure", sa.JSON(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reconnect_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_product_interviews_user_status_created", "product_interviews", ["user_id", "status", "created_at"])

    op.create_table(
        "interview_realtime_tokens",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("interview_id", sa.String(36), sa.ForeignKey("product_interviews.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("scope", sa.String(80), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("token_hash", name="uq_interview_realtime_token_hash"),
    )
    op.create_index("ix_interview_realtime_tokens_interview_expiry", "interview_realtime_tokens", ["interview_id", "expires_at"])

    op.create_table(
        "product_interview_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("interview_id", sa.String(36), sa.ForeignKey("product_interviews.id", ondelete="CASCADE"), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("direction", sa.String(16), nullable=False),
        sa.Column("event_type", sa.String(80), nullable=False),
        sa.Column("speaker", sa.String(24), nullable=True),
        sa.Column("text", sa.Text(), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("client_event_id", sa.String(128), nullable=True),
        sa.Column("provider_event_id", sa.String(255), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("interview_id", "sequence", name="uq_product_interview_event_sequence"),
        sa.UniqueConstraint("interview_id", "client_event_id", name="uq_product_interview_client_event"),
        sa.UniqueConstraint("interview_id", "provider_event_id", name="uq_product_interview_provider_event"),
    )
    op.create_index("ix_product_interview_events_timeline", "product_interview_events", ["interview_id", "sequence"])

    op.create_table(
        "product_interview_reports",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("interview_id", sa.String(36), sa.ForeignKey("product_interviews.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("rubric_version", sa.String(40), nullable=False),
        sa.Column("prompt_version", sa.String(40), nullable=False),
        sa.Column("model", sa.String(160), nullable=False),
        sa.Column("transcript_version", sa.Integer(), nullable=False),
        sa.Column("scores", sa.JSON(), nullable=True),
        sa.Column("strengths", sa.JSON(), nullable=True),
        sa.Column("gaps", sa.JSON(), nullable=True),
        sa.Column("actions", sa.JSON(), nullable=True),
        sa.Column("disclaimer", sa.Text(), nullable=True),
        sa.Column("provider_run_id", sa.String(255), nullable=True),
        sa.Column("error", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("interview_id", "rubric_version", name="uq_product_interview_report_rubric"),
    )
    op.create_index("ix_product_interview_reports_status_created", "product_interview_reports", ["status", "created_at"])

    op.create_table(
        "interview_feedback",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("interview_id", sa.String(36), sa.ForeignKey("product_interviews.id", ondelete="CASCADE"), nullable=False),
        sa.Column("report_id", sa.String(36), sa.ForeignKey("product_interview_reports.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("category", sa.String(80), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("event_ids", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_interview_feedback_report_created", "interview_feedback", ["report_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_interview_feedback_report_created", table_name="interview_feedback")
    op.drop_table("interview_feedback")
    op.drop_index("ix_product_interview_reports_status_created", table_name="product_interview_reports")
    op.drop_table("product_interview_reports")
    op.drop_index("ix_product_interview_events_timeline", table_name="product_interview_events")
    op.drop_table("product_interview_events")
    op.drop_index("ix_interview_realtime_tokens_interview_expiry", table_name="interview_realtime_tokens")
    op.drop_table("interview_realtime_tokens")
    op.drop_index("ix_product_interviews_user_status_created", table_name="product_interviews")
    op.drop_table("product_interviews")
