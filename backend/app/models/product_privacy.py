from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint

from app.models.db import Base


def _uuid() -> str:
    return str(uuid4())


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class PrivacyRequest(Base):
    __tablename__ = "product_privacy_requests"
    __table_args__ = (
        UniqueConstraint("user_id", "request_type", "idempotency_key", name="uq_product_privacy_request_idempotency"),
        Index("ix_product_privacy_requests_user_status", "user_id", "status"),
    )

    id = Column(String(36), primary_key=True, default=_uuid)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    request_type = Column(String(24), nullable=False)
    status = Column(String(32), nullable=False, default="queued")
    idempotency_key = Column(String(255), nullable=False)
    request_hash = Column(String(64), nullable=False)
    reason = Column(Text, nullable=True)
    checkpoints = Column(JSON, nullable=False, default=dict)
    retention_exceptions = Column(JSON, nullable=False, default=list)
    error = Column(JSON, nullable=True)
    attempts = Column(Integer, nullable=False, default=0)
    lease_expires_at = Column(DateTime(timezone=True), nullable=True)
    requested_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow)


class PrivacyArtifact(Base):
    __tablename__ = "product_privacy_artifacts"
    __table_args__ = (Index("ix_product_privacy_artifacts_expiry", "expires_at", "deleted_at"),)

    id = Column(String(36), primary_key=True, default=_uuid)
    request_id = Column(String(36), ForeignKey("product_privacy_requests.id", ondelete="CASCADE"), nullable=False, unique=True)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    object_key = Column(String(1024), nullable=False, unique=True)
    content_type = Column(String(120), nullable=False)
    size_bytes = Column(Integer, nullable=False)
    sha256 = Column(String(64), nullable=False)
    encryption_version = Column(String(40), nullable=False)
    download_token_hash = Column(String(64), nullable=True)
    download_token_expires_at = Column(DateTime(timezone=True), nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    deleted_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)


class PrivacyDispatch(Base):
    __tablename__ = "product_privacy_dispatches"
    __table_args__ = (Index("ix_product_privacy_dispatches_pending", "status", "available_at"),)

    id = Column(String(36), primary_key=True, default=_uuid)
    request_id = Column(String(36), ForeignKey("product_privacy_requests.id", ondelete="CASCADE"), nullable=False, unique=True)
    topic = Column(String(120), nullable=False, default="product.privacy.execute")
    payload = Column(JSON, nullable=False)
    status = Column(String(24), nullable=False, default="pending")
    attempts = Column(Integer, nullable=False, default=0)
    available_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
    last_error = Column(Text, nullable=True)
    published_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)


class PrivacyEvent(Base):
    __tablename__ = "product_privacy_events"
    __table_args__ = (
        UniqueConstraint("request_id", "sequence", name="uq_product_privacy_event_sequence"),
        Index("ix_product_privacy_events_request_sequence", "request_id", "sequence"),
    )

    id = Column(String(36), primary_key=True, default=_uuid)
    request_id = Column(String(36), ForeignKey("product_privacy_requests.id", ondelete="CASCADE"), nullable=False)
    sequence = Column(Integer, nullable=False)
    event_type = Column(String(80), nullable=False)
    payload = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)


class DeletionTombstone(Base):
    __tablename__ = "product_deletion_tombstones"

    id = Column(String(36), primary_key=True, default=_uuid)
    request_id = Column(String(36), ForeignKey("product_privacy_requests.id", ondelete="RESTRICT"), nullable=False, unique=True)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, unique=True)
    pseudonymous_subject = Column(String(64), nullable=False, unique=True)
    retention_exceptions = Column(JSON, nullable=False)
    deletion_manifest = Column(JSON, nullable=False)
    completed_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
