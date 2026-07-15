from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint

from app.models.db import Base


def _uuid() -> str:
    return str(uuid4())


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ProductInterview(Base):
    __tablename__ = "product_interviews"
    __table_args__ = (Index("ix_product_interviews_user_status_created", "user_id", "status", "created_at"),)

    id = Column(String(36), primary_key=True, default=_uuid)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    cv_version_id = Column(String(36), ForeignKey("product_cv_versions.id", ondelete="RESTRICT"), nullable=False)
    job_id = Column(String(36), nullable=True)
    target_role = Column(String(200), nullable=False)
    interview_type = Column(String(24), nullable=False)
    language = Column(String(8), nullable=False, default="vi")
    duration_minutes = Column(Integer, nullable=False)
    status = Column(String(32), nullable=False, default="created")
    cv_snapshot = Column(JSON, nullable=False)
    job_snapshot = Column(JSON, nullable=True)
    plan_snapshot = Column(JSON, nullable=False)
    rubric_version = Column(String(40), nullable=False)
    prompt_version = Column(String(40), nullable=False)
    gemini_model = Column(String(160), nullable=False)
    gemini_resumption_handle = Column(Text, nullable=True)
    credit_reservation_id = Column(String(36), nullable=True)
    billable_started_at = Column(DateTime(timezone=True), nullable=True)
    billable_event_id = Column(String(36), nullable=True)
    failure = Column(JSON, nullable=True)
    ended_reason = Column(String(40), nullable=True)
    started_at = Column(DateTime(timezone=True), nullable=True)
    ended_at = Column(DateTime(timezone=True), nullable=True)
    reconnect_until = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow)


class InterviewRealtimeToken(Base):
    __tablename__ = "interview_realtime_tokens"
    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_interview_realtime_token_hash"),
        Index("ix_interview_realtime_tokens_interview_expiry", "interview_id", "expires_at"),
    )

    id = Column(String(36), primary_key=True, default=_uuid)
    interview_id = Column(String(36), ForeignKey("product_interviews.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    token_hash = Column(String(64), nullable=False)
    scope = Column(String(80), nullable=False, default="interview:realtime")
    expires_at = Column(DateTime(timezone=True), nullable=False)
    consumed_at = Column(DateTime(timezone=True), nullable=True)
    revoked_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)


class ProductInterviewEvent(Base):
    __tablename__ = "product_interview_events"
    __table_args__ = (
        UniqueConstraint("interview_id", "sequence", name="uq_product_interview_event_sequence"),
        UniqueConstraint("interview_id", "client_event_id", name="uq_product_interview_client_event"),
        UniqueConstraint("interview_id", "provider_event_id", name="uq_product_interview_provider_event"),
        Index("ix_product_interview_events_timeline", "interview_id", "sequence"),
    )

    id = Column(String(36), primary_key=True, default=_uuid)
    interview_id = Column(String(36), ForeignKey("product_interviews.id", ondelete="CASCADE"), nullable=False)
    sequence = Column(Integer, nullable=False)
    direction = Column(String(16), nullable=False)
    event_type = Column(String(80), nullable=False)
    speaker = Column(String(24), nullable=True)
    text = Column(Text, nullable=True)
    payload = Column(JSON, nullable=False, default=dict)
    client_event_id = Column(String(128), nullable=True)
    provider_event_id = Column(String(255), nullable=True)
    occurred_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)


class ProductInterviewReport(Base):
    __tablename__ = "product_interview_reports"
    __table_args__ = (
        UniqueConstraint("interview_id", "rubric_version", "attempt_number", name="uq_product_interview_report_attempt"),
        Index("ix_product_interview_reports_status_created", "status", "created_at"),
        Index("ix_product_interview_reports_processing_lease", "status", "processing_lease_expires_at"),
    )

    id = Column(String(36), primary_key=True, default=_uuid)
    interview_id = Column(String(36), ForeignKey("product_interviews.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    parent_report_id = Column(String(36), ForeignKey("product_interview_reports.id", ondelete="SET NULL"), nullable=True)
    attempt_number = Column(Integer, nullable=False, default=1)
    status = Column(String(24), nullable=False, default="processing")
    rubric_version = Column(String(40), nullable=False)
    prompt_version = Column(String(40), nullable=False)
    model = Column(String(160), nullable=False)
    model_configuration_id = Column(String(36), nullable=True)
    transcript_version = Column(Integer, nullable=False)
    scores = Column(JSON, nullable=True)
    strengths = Column(JSON, nullable=True)
    gaps = Column(JSON, nullable=True)
    actions = Column(JSON, nullable=True)
    disclaimer = Column(Text, nullable=True)
    provider_run_id = Column(String(255), nullable=True)
    usage_json = Column(JSON, nullable=True)
    estimated_cost_minor = Column(Integer, nullable=True)
    error = Column(JSON, nullable=True)
    processing_lease_id = Column(String(255), nullable=True)
    processing_lease_expires_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow)


class InterviewFeedback(Base):
    __tablename__ = "interview_feedback"
    __table_args__ = (Index("ix_interview_feedback_report_created", "report_id", "created_at"),)

    id = Column(String(36), primary_key=True, default=_uuid)
    interview_id = Column(String(36), ForeignKey("product_interviews.id", ondelete="CASCADE"), nullable=False)
    report_id = Column(String(36), ForeignKey("product_interview_reports.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    category = Column(String(80), nullable=False)
    message = Column(Text, nullable=False)
    event_ids = Column(JSON, nullable=False, default=list)
    status = Column(String(24), nullable=False, default="open")
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
