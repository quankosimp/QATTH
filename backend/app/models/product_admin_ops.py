from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint

from backend.app.models.db import Base


def _uuid() -> str:
    return str(uuid4())


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ModelConfiguration(Base):
    __tablename__ = "product_model_configurations"
    __table_args__ = (
        UniqueConstraint("purpose", "version", name="uq_product_model_configuration_version"),
        UniqueConstraint("created_by_user_id", "idempotency_key", name="uq_product_model_configuration_idempotency"),
        Index("ix_product_model_configurations_purpose_status", "purpose", "status"),
    )

    id = Column(String(36), primary_key=True, default=_uuid)
    purpose = Column(String(120), nullable=False)
    version = Column(String(80), nullable=False)
    status = Column(String(24), nullable=False, default="draft")
    provider = Column(String(40), nullable=False)
    model = Column(String(160), nullable=False)
    configuration = Column(JSON, nullable=False, default=dict)
    output_schema_version = Column(String(80), nullable=True)
    idempotency_key = Column(String(255), nullable=False)
    request_hash = Column(String(64), nullable=False)
    created_by_user_id = Column(String(36), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    activated_by_user_id = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    activation_reason = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
    activated_at = Column(DateTime(timezone=True), nullable=True)
    retired_at = Column(DateTime(timezone=True), nullable=True)


class OperationalJob(Base):
    __tablename__ = "product_operational_jobs"
    __table_args__ = (
        Index("ix_product_operational_jobs_status_created", "status", "created_at"),
        Index("ix_product_operational_jobs_resource", "resource_type", "resource_id"),
        Index("ix_product_operational_jobs_request", "request_id"),
    )

    id = Column(String(36), primary_key=True)
    task_name = Column(String(160), nullable=False)
    queue = Column(String(80), nullable=False, default="celery")
    status = Column(String(24), nullable=False, default="queued")
    attempt = Column(Integer, nullable=False, default=0)
    max_attempts = Column(Integer, nullable=False, default=3)
    resource_type = Column(String(80), nullable=True)
    resource_id = Column(String(80), nullable=True)
    args_payload = Column(JSON, nullable=False, default=list)
    request_id = Column(String(128), nullable=True)
    parent_job_id = Column(String(36), ForeignKey("product_operational_jobs.id", ondelete="SET NULL"), nullable=True)
    error_code = Column(String(120), nullable=True)
    error_message = Column(Text, nullable=True)
    result_summary = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
    started_at = Column(DateTime(timezone=True), nullable=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow)


class PrivilegedCommand(Base):
    __tablename__ = "product_privileged_commands"
    __table_args__ = (UniqueConstraint("actor_user_id", "command_type", "idempotency_key", name="uq_product_privileged_command_idempotency"),)

    id = Column(String(36), primary_key=True, default=_uuid)
    actor_user_id = Column(String(36), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    command_type = Column(String(160), nullable=False)
    idempotency_key = Column(String(255), nullable=False)
    request_hash = Column(String(64), nullable=False)
    status = Column(String(24), nullable=False, default="processing")
    resource_type = Column(String(80), nullable=True)
    resource_id = Column(String(80), nullable=True)
    response_snapshot = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
    completed_at = Column(DateTime(timezone=True), nullable=True)


class PrivilegedAuditEvent(Base):
    __tablename__ = "product_privileged_audit_events"
    __table_args__ = (
        Index("ix_product_privileged_audit_actor_created", "actor_user_id", "created_at"),
        Index("ix_product_privileged_audit_resource", "resource_type", "resource_id"),
    )

    id = Column(String(36), primary_key=True, default=_uuid)
    sequence = Column(Integer, nullable=False, unique=True)
    actor_user_id = Column(String(36), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    action = Column(String(160), nullable=False)
    resource_type = Column(String(80), nullable=True)
    resource_id = Column(String(80), nullable=True)
    reason = Column(Text, nullable=True)
    request_id = Column(String(128), nullable=True)
    source_ip_hash = Column(String(64), nullable=True)
    metadata_json = Column(JSON, nullable=False, default=dict)
    previous_hash = Column(String(64), nullable=True)
    event_hash = Column(String(64), nullable=False, unique=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)


class AuditChainHead(Base):
    __tablename__ = "product_audit_chain_heads"

    id = Column(String(80), primary_key=True)
    sequence = Column(Integer, nullable=False, default=0)
    last_hash = Column(String(64), nullable=True)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow)
