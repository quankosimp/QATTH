"""product recommendations, interactions, and applications

Revision ID: 20260714_0011
Revises: 20260714_0010
"""

from alembic import op
import sqlalchemy as sa


revision = "20260714_0011"
down_revision = "20260714_0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "product_job_interactions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("job_id", sa.String(36), sa.ForeignKey("product_jobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("interaction_type", sa.String(24), nullable=False),
        sa.Column("reason_code", sa.String(80)),
        sa.Column("note", sa.Text()),
        sa.Column("context", sa.JSON(), nullable=False),
        sa.Column("taxonomy_version", sa.String(40), nullable=False),
        sa.Column("experiment_assignment", sa.JSON(), nullable=False),
        sa.Column("training_eligible", sa.String(8), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("user_id", "job_id", "interaction_type", name="uq_product_job_interaction_type"),
    )
    op.create_index("ix_product_job_interactions_user_created", "product_job_interactions", ["user_id", "created_at"])
    op.create_table(
        "product_job_moderation_cases",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("interaction_id", sa.String(36), sa.ForeignKey("product_job_interactions.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("job_id", sa.String(36), sa.ForeignKey("product_jobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("reporter_user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("reason_code", sa.String(80), nullable=False),
        sa.Column("details", sa.Text()),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("assigned_to_user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("resolution", sa.JSON()),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_product_job_moderation_cases_status_created", "product_job_moderation_cases", ["status", "created_at"])
    op.create_table(
        "product_job_applications",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("job_id", sa.String(36), sa.ForeignKey("product_jobs.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("source_url", sa.Text()),
        sa.Column("notes", sa.Text()),
        sa.Column("job_snapshot", sa.JSON(), nullable=False),
        sa.Column("idempotency_key", sa.String(255)),
        sa.Column("request_hash", sa.String(64)),
        sa.Column("applied_at", sa.DateTime(timezone=True)),
        sa.Column("closed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("user_id", "idempotency_key", name="uq_product_job_application_idempotency"),
    )
    op.create_index("ix_product_job_applications_user_status", "product_job_applications", ["user_id", "status"])
    op.create_table(
        "product_job_application_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("application_id", sa.String(36), sa.ForeignKey("product_job_applications.id", ondelete="CASCADE"), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("from_status", sa.String(24)),
        sa.Column("to_status", sa.String(24), nullable=False),
        sa.Column("actor_type", sa.String(24), nullable=False),
        sa.Column("actor_user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("reason_code", sa.String(80)),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("application_id", "sequence", name="uq_product_job_application_event_sequence"),
    )
    op.create_index("ix_product_job_application_events_application", "product_job_application_events", ["application_id", "sequence"])
    op.create_table(
        "product_recommendation_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("cv_version_id", sa.String(36), sa.ForeignKey("product_cv_versions.id", ondelete="SET NULL")),
        sa.Column("search_run_id", sa.String(36), sa.ForeignKey("product_job_search_runs.id", ondelete="SET NULL")),
        sa.Column("candidate_profile_id", sa.String(36), sa.ForeignKey("product_candidate_profiles.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("candidate_profile_version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("maximum_results", sa.Integer(), nullable=False),
        sa.Column("ranking_version", sa.String(40), nullable=False),
        sa.Column("experiment_assignment", sa.JSON(), nullable=False),
        sa.Column("input_snapshot", sa.JSON(), nullable=False),
        sa.Column("idempotency_key", sa.String(255)),
        sa.Column("request_hash", sa.String(64)),
        sa.Column("error", sa.JSON()),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("user_id", "idempotency_key", name="uq_product_recommendation_idempotency"),
    )
    op.create_index("ix_product_recommendation_runs_user_status", "product_recommendation_runs", ["user_id", "status"])
    op.create_table(
        "product_recommendation_dispatches",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("run_id", sa.String(36), sa.ForeignKey("product_recommendation_runs.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("topic", sa.String(120), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_error", sa.Text()),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_product_recommendation_dispatches_pending", "product_recommendation_dispatches", ["status", "available_at"])
    op.create_table(
        "product_recommendation_matches",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("run_id", sa.String(36), sa.ForeignKey("product_recommendation_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("job_id", sa.String(36), sa.ForeignKey("product_jobs.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("score_breakdown", sa.JSON(), nullable=False),
        sa.Column("reasons", sa.JSON(), nullable=False),
        sa.Column("gaps", sa.JSON(), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("result_snapshot", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("run_id", "job_id", name="uq_product_recommendation_match_job"),
        sa.UniqueConstraint("run_id", "rank", name="uq_product_recommendation_match_rank"),
    )
    op.create_index("ix_product_recommendation_matches_run_rank", "product_recommendation_matches", ["run_id", "rank"])


def downgrade() -> None:
    op.drop_table("product_recommendation_matches")
    op.drop_table("product_recommendation_dispatches")
    op.drop_table("product_recommendation_runs")
    op.drop_table("product_job_application_events")
    op.drop_table("product_job_applications")
    op.drop_table("product_job_moderation_cases")
    op.drop_table("product_job_interactions")
