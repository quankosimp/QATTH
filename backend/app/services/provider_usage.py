from __future__ import annotations

from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session
from structlog.contextvars import get_contextvars

from app.core.errors import AppError
from app.core.provider_resilience import get_provider_executor
from app.models.provider_ops import ProviderUsageEvent


class ProviderUsageService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def success(
        self,
        *,
        user_id: str | None,
        provider: str,
        purpose: str,
        resource_type: str,
        resource_id: str,
        metadata: dict[str, Any],
    ) -> ProviderUsageEvent:
        provider_run_id = metadata.get("provider_run_id")
        if provider_run_id:
            existing = self.db.scalar(select(ProviderUsageEvent).where(
                ProviderUsageEvent.provider == provider,
                ProviderUsageEvent.provider_run_id == provider_run_id,
            ))
            if existing is not None:
                return existing
        event = ProviderUsageEvent(
            user_id=user_id,
            provider=provider,
            purpose=purpose,
            model=metadata.get("model"),
            model_configuration_id=metadata.get("model_configuration_id"),
            correlation_id=str(metadata.get("correlation_id") or get_contextvars().get("request_id") or uuid4()),
            resource_type=resource_type,
            resource_id=resource_id,
            provider_run_id=provider_run_id,
            status="succeeded",
            attempts=int(metadata.get("attempts") or 1),
            latency_ms=metadata.get("latency_ms"),
            usage_json=metadata.get("usage") or {},
            estimated_cost_minor=metadata.get("estimated_cost_minor"),
        )
        self.db.add(event)
        self.db.flush()
        get_provider_executor().record_cost(provider, event.estimated_cost_minor)
        return event

    def failure(
        self,
        *,
        user_id: str | None,
        provider: str,
        purpose: str,
        resource_type: str,
        resource_id: str,
        error: Exception,
    ) -> ProviderUsageEvent:
        details = error.details if isinstance(error, AppError) else {}
        execution = (details or {}).get("provider_execution", {})
        event = ProviderUsageEvent(
            user_id=user_id,
            provider=provider,
            purpose=purpose,
            correlation_id=str(execution.get("correlation_id") or get_contextvars().get("request_id") or uuid4()),
            resource_type=resource_type,
            resource_id=resource_id,
            status="failed",
            attempts=int(execution.get("attempts") or 1),
            latency_ms=execution.get("latency_ms"),
            usage_json={},
            error_code=(error.code if isinstance(error, AppError) else type(error).__name__.upper())[:120],
        )
        self.db.add(event)
        self.db.flush()
        return event
