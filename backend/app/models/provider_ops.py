from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, JSON, String, UniqueConstraint

from app.models.db import Base


def _uuid() -> str:
    return str(uuid4())


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ProviderUsageEvent(Base):
    __tablename__ = "product_provider_usage_events"
    __table_args__ = (
        UniqueConstraint("provider", "provider_run_id", name="uq_product_provider_usage_run"),
        Index("ix_product_provider_usage_correlation", "correlation_id"),
        Index("ix_product_provider_usage_provider_time", "provider", "purpose", "occurred_at"),
        Index("ix_product_provider_usage_user_time", "user_id", "occurred_at"),
    )

    id = Column(String(36), primary_key=True, default=_uuid)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    provider = Column(String(40), nullable=False)
    purpose = Column(String(80), nullable=False)
    model = Column(String(160), nullable=True)
    model_configuration_id = Column(String(36), nullable=True)
    correlation_id = Column(String(128), nullable=False)
    resource_type = Column(String(80), nullable=False)
    resource_id = Column(String(80), nullable=False)
    provider_run_id = Column(String(255), nullable=True)
    status = Column(String(24), nullable=False)
    attempts = Column(Integer, nullable=False, default=1)
    latency_ms = Column(Integer, nullable=True)
    usage_json = Column(JSON, nullable=False, default=dict)
    estimated_cost_minor = Column(Integer, nullable=True)
    error_code = Column(String(120), nullable=True)
    occurred_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
