from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import BigInteger, Column, DateTime, Float, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR

from app.models.db import Base

try:
    from pgvector.sqlalchemy import Vector
except ImportError:
    def Vector(_dimensions: int):
        return JSON()


def _uuid() -> str:
    return str(uuid4())


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class JobSource(Base):
    __tablename__ = "product_job_sources"

    id = Column(String(36), primary_key=True, default=_uuid)
    key = Column(String(120), nullable=False, unique=True)
    display_name = Column(String(200), nullable=False)
    source_type = Column(String(40), nullable=False)
    base_domain = Column(String(255), nullable=False, unique=True)
    status = Column(String(24), nullable=False, default="active")
    access_policy = Column(JSON, nullable=False, default=dict)
    verification_ttl_seconds = Column(Integer, nullable=False, default=86400)
    quality_score = Column(Float, nullable=False, default=0.5)
    last_healthy_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow)


class ProductJob(Base):
    __tablename__ = "product_jobs"
    __table_args__ = (
        UniqueConstraint("canonical_fingerprint", name="uq_product_job_fingerprint"),
        Index("ix_product_jobs_status_expiry", "status", "expires_at"),
        Index("ix_product_jobs_company_title", "company_name", "title"),
        Index("ix_product_jobs_skills_gin", "skills", postgresql_using="gin"),
    )

    id = Column(String(36), primary_key=True, default=_uuid)
    canonical_fingerprint = Column(String(64), nullable=False)
    title = Column(String(500), nullable=False)
    company_name = Column(String(500), nullable=False)
    location_text = Column(String(500), nullable=True)
    remote_mode = Column(String(24), nullable=False, default="unknown")
    employment_type = Column(String(80), nullable=True)
    seniority = Column(String(80), nullable=True)
    salary_min_minor = Column(BigInteger, nullable=True)
    salary_max_minor = Column(BigInteger, nullable=True)
    salary_currency = Column(String(3), nullable=True)
    salary_period = Column(String(20), nullable=True)
    description_text = Column(Text, nullable=True)
    description_completeness = Column(String(24), nullable=False, default="partial")
    requirements = Column(JSON, nullable=False, default=dict)
    skills = Column(JSON().with_variant(JSONB(), "postgresql"), nullable=False, default=list)
    language = Column(String(16), nullable=True)
    status = Column(String(24), nullable=False, default="active")
    first_seen_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
    last_seen_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
    verified_at = Column(DateTime(timezone=True), nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=True)
    normalization_version = Column(String(40), nullable=False, default="job-v1")
    search_document = Column(TSVECTOR().with_variant(Text(), "sqlite"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow)


class JobSourceRecord(Base):
    __tablename__ = "product_job_source_records"
    __table_args__ = (
        UniqueConstraint("source_id", "source_job_id", name="uq_product_job_source_external"),
        UniqueConstraint("source_id", "url_fingerprint", name="uq_product_job_source_url"),
        Index("ix_product_job_source_records_job_checked", "job_id", "last_checked_at"),
    )

    id = Column(String(36), primary_key=True, default=_uuid)
    job_id = Column(String(36), ForeignKey("product_jobs.id", ondelete="CASCADE"), nullable=False)
    source_id = Column(String(36), ForeignKey("product_job_sources.id", ondelete="RESTRICT"), nullable=False)
    source_job_id = Column(String(255), nullable=True)
    source_url = Column(Text, nullable=False)
    url_fingerprint = Column(String(64), nullable=False)
    status = Column(String(24), nullable=False, default="unverified")
    first_seen_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
    last_seen_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
    last_checked_at = Column(DateTime(timezone=True), nullable=True)
    http_status = Column(Integer, nullable=True)
    fetch_outcome = Column(String(80), nullable=True)
    raw_file_id = Column(String(36), nullable=True)
    metadata_json = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow)


class JobSnapshot(Base):
    __tablename__ = "product_job_snapshots"
    __table_args__ = (
        UniqueConstraint("source_record_id", "content_hash", name="uq_product_job_snapshot_content"),
        Index("ix_product_job_snapshots_job_captured", "job_id", "captured_at"),
    )

    id = Column(String(36), primary_key=True, default=_uuid)
    job_id = Column(String(36), ForeignKey("product_jobs.id", ondelete="CASCADE"), nullable=False)
    source_record_id = Column(String(36), ForeignKey("product_job_source_records.id", ondelete="CASCADE"), nullable=False)
    content_hash = Column(String(64), nullable=False)
    normalized_payload = Column(JSON, nullable=False)
    raw_file_id = Column(String(36), nullable=True)
    raw_object_key = Column(String(1024), nullable=True)
    raw_content_type = Column(String(120), nullable=True)
    parser_version = Column(String(40), nullable=False)
    captured_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)


class JobEmbedding(Base):
    __tablename__ = "product_job_embeddings"
    __table_args__ = (
        UniqueConstraint("job_snapshot_id", "model", "model_version", name="uq_product_job_embedding_model"),
        Index("ix_product_job_embeddings_job", "job_id"),
    )

    id = Column(String(36), primary_key=True, default=_uuid)
    job_id = Column(String(36), ForeignKey("product_jobs.id", ondelete="CASCADE"), nullable=False)
    job_snapshot_id = Column(String(36), ForeignKey("product_job_snapshots.id", ondelete="CASCADE"), nullable=False)
    model = Column(String(160), nullable=False)
    model_version = Column(String(80), nullable=False)
    dimensions = Column(Integer, nullable=False)
    embedding = Column(Vector(1536), nullable=False)
    content_hash = Column(String(64), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)


class CandidateProfile(Base):
    __tablename__ = "product_candidate_profiles"
    __table_args__ = (
        UniqueConstraint("user_id", "version", name="uq_product_candidate_profile_version"),
        Index("ix_product_candidate_profiles_user_status", "user_id", "status"),
    )

    id = Column(String(36), primary_key=True, default=_uuid)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    version = Column(Integer, nullable=False)
    cv_version_id = Column(String(36), ForeignKey("product_cv_versions.id", ondelete="RESTRICT"), nullable=False)
    preference_version = Column(Integer, nullable=False)
    preference_snapshot = Column(JSON, nullable=False)
    interview_report_ids = Column(JSON, nullable=False, default=list)
    profile_json = Column(JSON, nullable=False)
    embedding = Column(Vector(1536), nullable=True)
    embedding_model = Column(String(160), nullable=True)
    generation_version = Column(String(80), nullable=False)
    status = Column(String(24), nullable=False, default="fresh")
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)


class JobSearchRun(Base):
    __tablename__ = "product_job_search_runs"
    __table_args__ = (
        UniqueConstraint("user_id", "idempotency_key", name="uq_product_job_search_idempotency"),
        Index("ix_product_job_search_runs_user_status", "user_id", "status"),
    )

    id = Column(String(36), primary_key=True, default=_uuid)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    status = Column(String(24), nullable=False, default="queued")
    mode = Column(String(16), nullable=False)
    query_text = Column(String(500), nullable=False)
    filters = Column(JSON, nullable=False, default=dict)
    maximum_results = Column(Integer, nullable=False)
    cv_version_id = Column(String(36), ForeignKey("product_cv_versions.id", ondelete="SET NULL"), nullable=True)
    candidate_profile_id = Column(String(36), ForeignKey("product_candidate_profiles.id", ondelete="SET NULL"), nullable=True)
    provider = Column(String(80), nullable=True)
    query_version = Column(String(40), nullable=False, default="job-query-v1")
    ranking_version = Column(String(40), nullable=False, default="job-rank-v1")
    idempotency_key = Column(String(255), nullable=True)
    request_hash = Column(String(64), nullable=True)
    progress = Column(JSON, nullable=False, default=dict)
    degraded_reasons = Column(JSON, nullable=False, default=list)
    error = Column(JSON, nullable=True)
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow)


class JobSearchDispatch(Base):
    __tablename__ = "product_job_search_dispatches"
    __table_args__ = (Index("ix_product_job_search_dispatches_pending", "status", "available_at"),)

    id = Column(String(36), primary_key=True, default=_uuid)
    run_id = Column(String(36), ForeignKey("product_job_search_runs.id", ondelete="CASCADE"), nullable=False, unique=True)
    topic = Column(String(120), nullable=False, default="product.jobs.search")
    payload = Column(JSON, nullable=False)
    status = Column(String(24), nullable=False, default="pending")
    attempts = Column(Integer, nullable=False, default=0)
    available_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
    last_error = Column(Text, nullable=True)
    published_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)


class JobSearchEvent(Base):
    __tablename__ = "product_job_search_events"
    __table_args__ = (
        UniqueConstraint("run_id", "sequence", name="uq_product_job_search_event_sequence"),
        Index("ix_product_job_search_events_run_sequence", "run_id", "sequence"),
    )

    id = Column(String(36), primary_key=True, default=_uuid)
    run_id = Column(String(36), ForeignKey("product_job_search_runs.id", ondelete="CASCADE"), nullable=False)
    sequence = Column(Integer, nullable=False)
    event_type = Column(String(80), nullable=False)
    payload = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)


class JobSearchResult(Base):
    __tablename__ = "product_job_search_results"
    __table_args__ = (
        UniqueConstraint("run_id", "job_id", name="uq_product_job_search_result_job"),
        UniqueConstraint("run_id", "rank", name="uq_product_job_search_result_rank"),
        Index("ix_product_job_search_results_run_rank", "run_id", "rank"),
    )

    id = Column(String(36), primary_key=True, default=_uuid)
    run_id = Column(String(36), ForeignKey("product_job_search_runs.id", ondelete="CASCADE"), nullable=False)
    job_id = Column(String(36), ForeignKey("product_jobs.id", ondelete="CASCADE"), nullable=False)
    job_snapshot_id = Column(String(36), ForeignKey("product_job_snapshots.id", ondelete="SET NULL"), nullable=True)
    rank = Column(Integer, nullable=False)
    lexical_score = Column(Float, nullable=False, default=0)
    vector_score = Column(Float, nullable=False, default=0)
    freshness_score = Column(Float, nullable=False, default=0)
    source_score = Column(Float, nullable=False, default=0)
    rerank_score = Column(Float, nullable=False, default=0)
    final_score = Column(Float, nullable=False)
    reasons = Column(JSON, nullable=False, default=list)
    gaps = Column(JSON, nullable=False, default=list)
    explanation_status = Column(String(24), nullable=False, default="not_requested")
    explanation = Column(JSON, nullable=True)
    result_snapshot = Column(JSON, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
