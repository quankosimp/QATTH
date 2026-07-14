from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint

from app.models.db import Base


def _uuid() -> str:
    return str(uuid4())


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ProductFileAsset(Base):
    __tablename__ = "product_file_assets"
    __table_args__ = (
        Index("ix_product_file_assets_user_created", "user_id", "created_at"),
        Index("ix_product_file_assets_lifecycle", "upload_status", "security_status", "expires_at"),
    )

    id = Column(String(36), primary_key=True, default=_uuid)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    purpose = Column(String(40), nullable=False)
    original_filename = Column(String(255), nullable=False)
    content_type = Column(String(120), nullable=False)
    declared_size_bytes = Column(Integer, nullable=False)
    actual_size_bytes = Column(Integer, nullable=True)
    declared_sha256 = Column(String(64), nullable=False)
    verified_sha256 = Column(String(64), nullable=True)
    bucket = Column(String(255), nullable=False)
    object_key = Column(String(1024), nullable=False, unique=True)
    storage_backend = Column(String(32), nullable=False)
    upload_status = Column(String(24), nullable=False, default="pending")
    security_status = Column(String(24), nullable=False, default="pending")
    provider_etag = Column(String(255), nullable=True)
    rejection_reason = Column(Text, nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    uploaded_at = Column(DateTime(timezone=True), nullable=True)
    deleted_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow)


class ProductCV(Base):
    __tablename__ = "product_cvs"
    __table_args__ = (Index("ix_product_cvs_user_status_created", "user_id", "status", "created_at"),)

    id = Column(String(36), primary_key=True, default=_uuid)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    title = Column(String(255), nullable=False)
    status = Column(String(24), nullable=False, default="active")
    active_version_id = Column(String(36), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow)


class CvScan(Base):
    __tablename__ = "product_cv_scans"
    __table_args__ = (
        UniqueConstraint("file_id", "schema_version", "attempt_number", name="uq_product_cv_scan_file_schema_attempt"),
        Index("ix_product_cv_scans_user_status", "user_id", "status"),
    )

    id = Column(String(36), primary_key=True, default=_uuid)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    file_id = Column(String(36), ForeignKey("product_file_assets.id", ondelete="RESTRICT"), nullable=False)
    cv_id = Column(String(36), ForeignKey("product_cvs.id", ondelete="SET NULL"), nullable=True)
    parent_scan_id = Column(String(36), ForeignKey("product_cv_scans.id", ondelete="SET NULL"), nullable=True)
    attempt_number = Column(Integer, nullable=False, default=1)
    status = Column(String(32), nullable=False, default="queued")
    schema_version = Column(String(32), nullable=False)
    locale_hint = Column(String(16), nullable=True)
    provider = Column(String(40), nullable=True)
    provider_run_id = Column(String(255), nullable=True)
    error = Column(JSON, nullable=True)
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow)


class CvDraft(Base):
    __tablename__ = "product_cv_drafts"

    id = Column(String(36), primary_key=True, default=_uuid)
    scan_id = Column(String(36), ForeignKey("product_cv_scans.id", ondelete="CASCADE"), nullable=False, unique=True)
    revision = Column(Integer, nullable=False, default=1)
    schema_version = Column(String(32), nullable=False)
    content = Column(JSON, nullable=False)
    field_confidence = Column(JSON, nullable=False, default=dict)
    warnings = Column(JSON, nullable=False, default=list)
    checksum = Column(String(64), nullable=False)
    confirmed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow)


class ProductCvVersion(Base):
    __tablename__ = "product_cv_versions"
    __table_args__ = (
        UniqueConstraint("cv_id", "version", name="uq_product_cv_version"),
        Index("ix_product_cv_versions_user_created", "user_id", "created_at"),
    )

    id = Column(String(36), primary_key=True, default=_uuid)
    cv_id = Column(String(36), ForeignKey("product_cvs.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    source_scan_id = Column(String(36), ForeignKey("product_cv_scans.id", ondelete="SET NULL"), nullable=True)
    source_file_id = Column(String(36), ForeignKey("product_file_assets.id", ondelete="RESTRICT"), nullable=False)
    version = Column(Integer, nullable=False)
    schema_version = Column(String(32), nullable=False)
    content = Column(JSON, nullable=False)
    checksum = Column(String(64), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)


class CvAnalysis(Base):
    __tablename__ = "product_cv_analyses"
    __table_args__ = (Index("ix_product_cv_analyses_user_status", "user_id", "status"),)

    id = Column(String(36), primary_key=True, default=_uuid)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    cv_version_id = Column(String(36), ForeignKey("product_cv_versions.id", ondelete="CASCADE"), nullable=False)
    parent_analysis_id = Column(String(36), ForeignKey("product_cv_analyses.id", ondelete="SET NULL"), nullable=True)
    attempt_number = Column(Integer, nullable=False, default=1)
    status = Column(String(24), nullable=False, default="queued")
    scores = Column(JSON, nullable=True)
    findings = Column(JSON, nullable=True)
    provider = Column(String(40), nullable=True)
    provider_run_id = Column(String(255), nullable=True)
    model_name = Column(String(255), nullable=True)
    model_configuration_id = Column(String(36), nullable=True)
    prompt_version = Column(String(80), nullable=True)
    usage_json = Column(JSON, nullable=True)
    disclaimer = Column(Text, nullable=True)
    error = Column(JSON, nullable=True)
    credit_reservation_id = Column(String(36), nullable=True)
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow)
