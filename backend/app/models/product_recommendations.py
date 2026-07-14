from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint

from app.models.db import Base


def _uuid() -> str:
    return str(uuid4())


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class JobInteraction(Base):
    __tablename__ = "product_job_interactions"
    __table_args__ = (
        UniqueConstraint("user_id", "job_id", "interaction_type", name="uq_product_job_interaction_type"),
        Index("ix_product_job_interactions_user_created", "user_id", "created_at"),
    )

    id = Column(String(36), primary_key=True, default=_uuid)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    job_id = Column(String(36), ForeignKey("product_jobs.id", ondelete="CASCADE"), nullable=False)
    interaction_type = Column(String(24), nullable=False)
    reason_code = Column(String(80), nullable=True)
    note = Column(Text, nullable=True)
    context = Column(JSON, nullable=False, default=dict)
    taxonomy_version = Column(String(40), nullable=False, default="job-feedback-v1")
    experiment_assignment = Column(JSON, nullable=False, default=dict)
    training_eligible = Column(String(8), nullable=False, default="false")
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow)


class JobModerationCase(Base):
    __tablename__ = "product_job_moderation_cases"
    __table_args__ = (Index("ix_product_job_moderation_cases_status_created", "status", "created_at"),)

    id = Column(String(36), primary_key=True, default=_uuid)
    interaction_id = Column(String(36), ForeignKey("product_job_interactions.id", ondelete="CASCADE"), nullable=False, unique=True)
    job_id = Column(String(36), ForeignKey("product_jobs.id", ondelete="CASCADE"), nullable=False)
    reporter_user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    reason_code = Column(String(80), nullable=False)
    details = Column(Text, nullable=True)
    status = Column(String(24), nullable=False, default="open")
    assigned_to_user_id = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    resolution = Column(JSON, nullable=True)
    resolved_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow)


class JobApplication(Base):
    __tablename__ = "product_job_applications"
    __table_args__ = (
        UniqueConstraint("user_id", "idempotency_key", name="uq_product_job_application_idempotency"),
        Index("ix_product_job_applications_user_status", "user_id", "status"),
    )

    id = Column(String(36), primary_key=True, default=_uuid)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    job_id = Column(String(36), ForeignKey("product_jobs.id", ondelete="RESTRICT"), nullable=False)
    status = Column(String(24), nullable=False, default="planned")
    version = Column(Integer, nullable=False, default=1)
    source_url = Column(Text, nullable=True)
    notes = Column(Text, nullable=True)
    job_snapshot = Column(JSON, nullable=False)
    idempotency_key = Column(String(255), nullable=True)
    request_hash = Column(String(64), nullable=True)
    applied_at = Column(DateTime(timezone=True), nullable=True)
    closed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow)


class JobApplicationEvent(Base):
    __tablename__ = "product_job_application_events"
    __table_args__ = (
        UniqueConstraint("application_id", "sequence", name="uq_product_job_application_event_sequence"),
        Index("ix_product_job_application_events_application", "application_id", "sequence"),
    )

    id = Column(String(36), primary_key=True, default=_uuid)
    application_id = Column(String(36), ForeignKey("product_job_applications.id", ondelete="CASCADE"), nullable=False)
    sequence = Column(Integer, nullable=False)
    from_status = Column(String(24), nullable=True)
    to_status = Column(String(24), nullable=False)
    actor_type = Column(String(24), nullable=False, default="user")
    actor_user_id = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    reason_code = Column(String(80), nullable=True)
    metadata_json = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)


class RecommendationRun(Base):
    __tablename__ = "product_recommendation_runs"
    __table_args__ = (
        UniqueConstraint("user_id", "idempotency_key", name="uq_product_recommendation_idempotency"),
        Index("ix_product_recommendation_runs_user_status", "user_id", "status"),
    )

    id = Column(String(36), primary_key=True, default=_uuid)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    cv_version_id = Column(String(36), ForeignKey("product_cv_versions.id", ondelete="SET NULL"), nullable=True)
    search_run_id = Column(String(36), ForeignKey("product_job_search_runs.id", ondelete="SET NULL"), nullable=True)
    candidate_profile_id = Column(String(36), ForeignKey("product_candidate_profiles.id", ondelete="RESTRICT"), nullable=False)
    candidate_profile_version = Column(Integer, nullable=False)
    status = Column(String(24), nullable=False, default="queued")
    maximum_results = Column(Integer, nullable=False, default=20)
    ranking_version = Column(String(40), nullable=False, default="recommendation-v1")
    experiment_assignment = Column(JSON, nullable=False, default=dict)
    input_snapshot = Column(JSON, nullable=False)
    idempotency_key = Column(String(255), nullable=True)
    request_hash = Column(String(64), nullable=True)
    error = Column(JSON, nullable=True)
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow)


class RecommendationDispatch(Base):
    __tablename__ = "product_recommendation_dispatches"
    __table_args__ = (Index("ix_product_recommendation_dispatches_pending", "status", "available_at"),)

    id = Column(String(36), primary_key=True, default=_uuid)
    run_id = Column(String(36), ForeignKey("product_recommendation_runs.id", ondelete="CASCADE"), nullable=False, unique=True)
    topic = Column(String(120), nullable=False, default="product.recommendations.generate")
    payload = Column(JSON, nullable=False)
    status = Column(String(24), nullable=False, default="pending")
    attempts = Column(Integer, nullable=False, default=0)
    available_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
    last_error = Column(Text, nullable=True)
    published_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)


class RecommendationMatch(Base):
    __tablename__ = "product_recommendation_matches"
    __table_args__ = (
        UniqueConstraint("run_id", "job_id", name="uq_product_recommendation_match_job"),
        UniqueConstraint("run_id", "rank", name="uq_product_recommendation_match_rank"),
        Index("ix_product_recommendation_matches_run_rank", "run_id", "rank"),
    )

    id = Column(String(36), primary_key=True, default=_uuid)
    run_id = Column(String(36), ForeignKey("product_recommendation_runs.id", ondelete="CASCADE"), nullable=False)
    job_id = Column(String(36), ForeignKey("product_jobs.id", ondelete="RESTRICT"), nullable=False)
    rank = Column(Integer, nullable=False)
    score = Column(Float, nullable=False)
    score_breakdown = Column(JSON, nullable=False)
    reasons = Column(JSON, nullable=False, default=list)
    gaps = Column(JSON, nullable=False, default=list)
    evidence = Column(JSON, nullable=False)
    result_snapshot = Column(JSON, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)


class RecommendationFeedback(Base):
    __tablename__ = "product_recommendation_feedback"
    __table_args__ = (
        UniqueConstraint("user_id", "idempotency_key", name="uq_product_recommendation_feedback_idempotency"),
        Index("ix_product_recommendation_feedback_run_event", "run_id", "event_type", "created_at"),
        Index("ix_product_recommendation_feedback_user_created", "user_id", "created_at"),
    )

    id = Column(String(36), primary_key=True, default=_uuid)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    run_id = Column(String(36), ForeignKey("product_recommendation_runs.id", ondelete="CASCADE"), nullable=False)
    match_id = Column(String(36), ForeignKey("product_recommendation_matches.id", ondelete="CASCADE"), nullable=False)
    job_id = Column(String(36), ForeignKey("product_jobs.id", ondelete="RESTRICT"), nullable=False)
    event_type = Column(String(40), nullable=False)
    reason_code = Column(String(80), nullable=True)
    note = Column(Text, nullable=True)
    taxonomy_version = Column(String(40), nullable=False, default="recommendation-feedback-v1")
    ranking_version = Column(String(40), nullable=False)
    experiment_assignment = Column(JSON, nullable=False)
    context_snapshot = Column(JSON, nullable=False)
    training_eligible = Column(Boolean, nullable=False, default=False)
    training_consent_snapshot = Column(JSON, nullable=False)
    idempotency_key = Column(String(255), nullable=False)
    request_hash = Column(String(64), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
