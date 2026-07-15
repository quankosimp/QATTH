"""product job catalog and search

Revision ID: 20260714_0010
Revises: 20260714_0009
Create Date: 2026-07-14
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

try:
    from pgvector.sqlalchemy import Vector
except ImportError:
    Vector = None

revision: str = "20260714_0010"
down_revision: Union[str, None] = "20260714_0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    is_postgres = op.get_bind().dialect.name == "postgresql"
    if is_postgres:
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    vector_type = Vector(1536) if is_postgres and Vector else sa.JSON()
    search_type = postgresql.TSVECTOR() if is_postgres else sa.Text()

    op.create_table("product_job_sources",
        sa.Column("id", sa.String(36), primary_key=True), sa.Column("key", sa.String(120), nullable=False, unique=True),
        sa.Column("display_name", sa.String(200), nullable=False), sa.Column("source_type", sa.String(40), nullable=False),
        sa.Column("base_domain", sa.String(255), nullable=False, unique=True), sa.Column("status", sa.String(24), nullable=False),
        sa.Column("access_policy", sa.JSON(), nullable=False), sa.Column("verification_ttl_seconds", sa.Integer(), nullable=False),
        sa.Column("quality_score", sa.Float(), nullable=False), sa.Column("last_healthy_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False))
    op.create_table("product_jobs",
        sa.Column("id", sa.String(36), primary_key=True), sa.Column("canonical_fingerprint", sa.String(64), nullable=False),
        sa.Column("title", sa.String(500), nullable=False), sa.Column("company_name", sa.String(500), nullable=False),
        sa.Column("location_text", sa.String(500)), sa.Column("remote_mode", sa.String(24), nullable=False),
        sa.Column("employment_type", sa.String(80)), sa.Column("seniority", sa.String(80)),
        sa.Column("salary_min_minor", sa.BigInteger()), sa.Column("salary_max_minor", sa.BigInteger()),
        sa.Column("salary_currency", sa.String(3)), sa.Column("salary_period", sa.String(20)),
        sa.Column("description_text", sa.Text()), sa.Column("description_completeness", sa.String(24), nullable=False),
        sa.Column("requirements", sa.JSON(), nullable=False), sa.Column("skills", postgresql.JSONB() if is_postgres else sa.JSON(), nullable=False),
        sa.Column("language", sa.String(16)), sa.Column("status", sa.String(24), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False), sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True)), sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("normalization_version", sa.String(40), nullable=False), sa.Column("search_document", search_type),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("canonical_fingerprint", name="uq_product_job_fingerprint"))
    op.create_index("ix_product_jobs_status_expiry", "product_jobs", ["status", "expires_at"])
    op.create_index("ix_product_jobs_company_title", "product_jobs", ["company_name", "title"])
    if is_postgres:
        op.execute("CREATE INDEX ix_product_jobs_skills_gin ON product_jobs USING gin (skills)")
        op.execute("CREATE INDEX ix_product_jobs_search_document ON product_jobs USING gin (search_document)")
        op.execute("CREATE FUNCTION product_jobs_search_document_update() RETURNS trigger AS $$ BEGIN NEW.search_document := to_tsvector('simple', coalesce(NEW.title,'') || ' ' || coalesce(NEW.company_name,'') || ' ' || coalesce(NEW.location_text,'') || ' ' || coalesce(NEW.description_text,'')); RETURN NEW; END $$ LANGUAGE plpgsql")
        op.execute("CREATE TRIGGER trg_product_jobs_search_document BEFORE INSERT OR UPDATE OF title, company_name, location_text, description_text ON product_jobs FOR EACH ROW EXECUTE FUNCTION product_jobs_search_document_update()")

    op.create_table("product_job_source_records",
        sa.Column("id", sa.String(36), primary_key=True), sa.Column("job_id", sa.String(36), sa.ForeignKey("product_jobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_id", sa.String(36), sa.ForeignKey("product_job_sources.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("source_job_id", sa.String(255)), sa.Column("source_url", sa.Text(), nullable=False), sa.Column("url_fingerprint", sa.String(64), nullable=False),
        sa.Column("status", sa.String(24), nullable=False), sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False), sa.Column("last_checked_at", sa.DateTime(timezone=True)),
        sa.Column("http_status", sa.Integer()), sa.Column("fetch_outcome", sa.String(80)), sa.Column("raw_file_id", sa.String(36)),
        sa.Column("metadata_json", sa.JSON(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("source_id", "source_job_id", name="uq_product_job_source_external"),
        sa.UniqueConstraint("source_id", "url_fingerprint", name="uq_product_job_source_url"))
    op.create_index("ix_product_job_source_records_job_checked", "product_job_source_records", ["job_id", "last_checked_at"])
    op.create_table("product_job_snapshots",
        sa.Column("id", sa.String(36), primary_key=True), sa.Column("job_id", sa.String(36), sa.ForeignKey("product_jobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_record_id", sa.String(36), sa.ForeignKey("product_job_source_records.id", ondelete="CASCADE"), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False), sa.Column("normalized_payload", sa.JSON(), nullable=False),
        sa.Column("raw_file_id", sa.String(36)), sa.Column("raw_object_key", sa.String(1024)),
        sa.Column("raw_content_type", sa.String(120)), sa.Column("parser_version", sa.String(40), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("source_record_id", "content_hash", name="uq_product_job_snapshot_content"))
    op.create_index("ix_product_job_snapshots_job_captured", "product_job_snapshots", ["job_id", "captured_at"])
    op.create_table("product_job_embeddings",
        sa.Column("id", sa.String(36), primary_key=True), sa.Column("job_id", sa.String(36), sa.ForeignKey("product_jobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("job_snapshot_id", sa.String(36), sa.ForeignKey("product_job_snapshots.id", ondelete="CASCADE"), nullable=False),
        sa.Column("model", sa.String(160), nullable=False), sa.Column("model_version", sa.String(80), nullable=False),
        sa.Column("dimensions", sa.Integer(), nullable=False), sa.Column("embedding", vector_type, nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("job_snapshot_id", "model", "model_version", name="uq_product_job_embedding_model"))
    op.create_index("ix_product_job_embeddings_job", "product_job_embeddings", ["job_id"])
    if is_postgres:
        op.execute("CREATE INDEX ix_product_job_embeddings_hnsw ON product_job_embeddings USING hnsw (embedding vector_cosine_ops)")

    op.create_table("product_candidate_profiles",
        sa.Column("id", sa.String(36), primary_key=True), sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False), sa.Column("cv_version_id", sa.String(36), sa.ForeignKey("product_cv_versions.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("preference_version", sa.Integer(), nullable=False), sa.Column("preference_snapshot", sa.JSON(), nullable=False),
        sa.Column("interview_report_ids", sa.JSON(), nullable=False), sa.Column("profile_json", sa.JSON(), nullable=False),
        sa.Column("embedding", vector_type), sa.Column("embedding_model", sa.String(160)), sa.Column("generation_version", sa.String(80), nullable=False),
        sa.Column("status", sa.String(24), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("user_id", "version", name="uq_product_candidate_profile_version"))
    op.create_index("ix_product_candidate_profiles_user_status", "product_candidate_profiles", ["user_id", "status"])

    op.create_table("product_job_search_runs",
        sa.Column("id", sa.String(36), primary_key=True), sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(24), nullable=False), sa.Column("mode", sa.String(16), nullable=False), sa.Column("query_text", sa.String(500), nullable=False),
        sa.Column("filters", sa.JSON(), nullable=False), sa.Column("maximum_results", sa.Integer(), nullable=False),
        sa.Column("cv_version_id", sa.String(36), sa.ForeignKey("product_cv_versions.id", ondelete="SET NULL")),
        sa.Column("candidate_profile_id", sa.String(36), sa.ForeignKey("product_candidate_profiles.id", ondelete="SET NULL")),
        sa.Column("provider", sa.String(80)), sa.Column("query_version", sa.String(40), nullable=False), sa.Column("ranking_version", sa.String(40), nullable=False),
        sa.Column("idempotency_key", sa.String(255)), sa.Column("request_hash", sa.String(64)),
        sa.Column("progress", sa.JSON(), nullable=False), sa.Column("degraded_reasons", sa.JSON(), nullable=False), sa.Column("error", sa.JSON()),
        sa.Column("started_at", sa.DateTime(timezone=True)), sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("user_id", "idempotency_key", name="uq_product_job_search_idempotency"))
    op.create_index("ix_product_job_search_runs_user_status", "product_job_search_runs", ["user_id", "status"])
    op.create_table("product_job_search_dispatches",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("run_id", sa.String(36), sa.ForeignKey("product_job_search_runs.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("topic", sa.String(120), nullable=False), sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False), sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False), sa.Column("last_error", sa.Text()),
        sa.Column("published_at", sa.DateTime(timezone=True)), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_product_job_search_dispatches_pending", "product_job_search_dispatches", ["status", "available_at"])
    op.create_table("product_job_search_events",
        sa.Column("id", sa.String(36), primary_key=True), sa.Column("run_id", sa.String(36), sa.ForeignKey("product_job_search_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False), sa.Column("event_type", sa.String(80), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("run_id", "sequence", name="uq_product_job_search_event_sequence"))
    op.create_index("ix_product_job_search_events_run_sequence", "product_job_search_events", ["run_id", "sequence"])
    op.create_table("product_job_search_results",
        sa.Column("id", sa.String(36), primary_key=True), sa.Column("run_id", sa.String(36), sa.ForeignKey("product_job_search_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("job_id", sa.String(36), sa.ForeignKey("product_jobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("job_snapshot_id", sa.String(36), sa.ForeignKey("product_job_snapshots.id", ondelete="SET NULL")), sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("lexical_score", sa.Float(), nullable=False), sa.Column("vector_score", sa.Float(), nullable=False),
        sa.Column("freshness_score", sa.Float(), nullable=False), sa.Column("source_score", sa.Float(), nullable=False),
        sa.Column("rerank_score", sa.Float(), nullable=False), sa.Column("final_score", sa.Float(), nullable=False),
        sa.Column("reasons", sa.JSON(), nullable=False), sa.Column("gaps", sa.JSON(), nullable=False),
        sa.Column("explanation_status", sa.String(24), nullable=False), sa.Column("explanation", sa.JSON()),
        sa.Column("result_snapshot", sa.JSON(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("run_id", "job_id", name="uq_product_job_search_result_job"),
        sa.UniqueConstraint("run_id", "rank", name="uq_product_job_search_result_rank"))
    op.create_index("ix_product_job_search_results_run_rank", "product_job_search_results", ["run_id", "rank"])


def downgrade() -> None:
    op.drop_table("product_job_search_results")
    op.drop_table("product_job_search_events")
    op.drop_table("product_job_search_dispatches")
    op.drop_table("product_job_search_runs")
    op.drop_table("product_candidate_profiles")
    op.drop_table("product_job_embeddings")
    op.drop_table("product_job_snapshots")
    op.drop_table("product_job_source_records")
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS trg_product_jobs_search_document ON product_jobs")
        op.execute("DROP FUNCTION IF EXISTS product_jobs_search_document_update")
    op.drop_table("product_jobs")
    op.drop_table("product_job_sources")
