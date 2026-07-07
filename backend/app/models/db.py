from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import Boolean, JSON, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


def utc_now() -> datetime:
    return datetime.now(UTC)


class CVRecord(Base):
    __tablename__ = "cv_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    original_file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(120), nullable=False)
    file_path: Mapped[str] = mapped_column(Text, nullable=False)
    scan_status: Mapped[str] = mapped_column(String(40), nullable=False, default="pending")
    parsed_profile: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    raw_model_response: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    warnings: Mapped[list | None] = mapped_column(JSON, nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class CVVersion(Base):
    __tablename__ = "cv_versions"
    __table_args__ = (UniqueConstraint("cv_id", "version_number", name="uq_cv_version_number"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    cv_id: Mapped[str] = mapped_column(ForeignKey("cv_records.id"), nullable=False, index=True)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    source: Mapped[str] = mapped_column(String(80), nullable=False)
    profile_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    edit_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    full_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    role: Mapped[str] = mapped_column(String(40), nullable=False, default="student")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class AuthToken(Base):
    __tablename__ = "auth_tokens"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class PasswordResetToken(Base):
    __tablename__ = "password_reset_tokens"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    actor_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    resource_type: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    resource_id: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class UserJobPreference(Base):
    __tablename__ = "user_job_preferences"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), unique=True, nullable=False, index=True)
    target_roles: Mapped[list | None] = mapped_column(JSON, nullable=True)
    locations: Mapped[list | None] = mapped_column(JSON, nullable=True)
    working_models: Mapped[list | None] = mapped_column(JSON, nullable=True)
    salary_expectation: Mapped[str | None] = mapped_column(String(120), nullable=True)
    preferred_skills: Mapped[list | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class JobInteraction(Base):
    __tablename__ = "job_interactions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("job_postings.id"), nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class ConsentRecord(Base):
    __tablename__ = "consent_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    consent_type: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    accepted: Mapped[bool] = mapped_column(Boolean, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class BackgroundTask(Base):
    __tablename__ = "background_tasks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    celery_task_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    task_type: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(40), nullable=False, index=True, default="queued")
    resource_type: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    resource_id: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    result_payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error_payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class FileAsset(Base):
    __tablename__ = "file_assets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    owner_type: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    owner_id: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    original_file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(120), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    storage_backend: Mapped[str] = mapped_column(String(40), nullable=False)
    storage_key: Mapped[str] = mapped_column(Text, nullable=False)
    local_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class PromptTemplate(Base):
    __tablename__ = "prompt_templates"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    key: Mapped[str] = mapped_column(String(120), unique=True, nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class PromptVersion(Base):
    __tablename__ = "prompt_versions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    template_id: Mapped[str] = mapped_column(ForeignKey("prompt_templates.id"), nullable=False, index=True)
    version: Mapped[str] = mapped_column(String(80), nullable=False)
    model: Mapped[str] = mapped_column(String(160), nullable=False)
    prompt_text: Mapped[str] = mapped_column(Text, nullable=False)
    schema_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class ModelRun(Base):
    __tablename__ = "model_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    run_type: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(80), nullable=False, default="gemini")
    model: Mapped[str] = mapped_column(String(160), nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="running", index=True)
    prompt_version_id: Mapped[str | None] = mapped_column(
        ForeignKey("prompt_versions.id"), nullable=True, index=True
    )
    input_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    output_schema: Mapped[str | None] = mapped_column(String(160), nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class InterviewSession(Base):
    __tablename__ = "interview_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    cv_id: Mapped[str] = mapped_column(ForeignKey("cv_records.id"), nullable=False, index=True)
    target_role: Mapped[str] = mapped_column(String(160), nullable=False)
    language: Mapped[str] = mapped_column(String(20), nullable=False, default="vi")
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="created")
    opening_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class InterviewTurn(Base):
    __tablename__ = "interview_turns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    interview_id: Mapped[str] = mapped_column(
        ForeignKey("interview_sessions.id"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String(40), nullable=False)
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    text: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class CrawlRun(Base):
    __tablename__ = "crawl_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    source: Mapped[str] = mapped_column(String(80), nullable=False)
    query: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="pending")
    jobs_found: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class JobPosting(Base):
    __tablename__ = "job_postings"
    __table_args__ = (UniqueConstraint("source", "external_id", name="uq_job_source_external"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    source: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    company: Mapped[str] = mapped_column(String(255), nullable=False)
    location: Mapped[str | None] = mapped_column(String(255), nullable=True)
    working_model: Mapped[str | None] = mapped_column(String(80), nullable=True)
    level: Mapped[str | None] = mapped_column(String(80), nullable=True)
    salary_range: Mapped[str | None] = mapped_column(String(120), nullable=True)
    skills: Mapped[list | None] = mapped_column(JSON, nullable=True)
    jd_text: Mapped[str] = mapped_column(Text, nullable=False)
    posted_at: Mapped[str | None] = mapped_column(String(120), nullable=True)
    embedding: Mapped[list | None] = mapped_column(JSON, nullable=True)
    raw_payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    crawled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class MatchRun(Base):
    __tablename__ = "match_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    cv_id: Mapped[str] = mapped_column(ForeignKey("cv_records.id"), nullable=False, index=True)
    interview_id: Mapped[str | None] = mapped_column(
        ForeignKey("interview_sessions.id"), nullable=True, index=True
    )
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="completed")
    results: Mapped[list] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
