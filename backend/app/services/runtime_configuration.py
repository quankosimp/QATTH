from __future__ import annotations

import hashlib
from typing import Any

from sqlalchemy import select
from structlog.contextvars import get_contextvars

from app.core.db import SessionLocal
from app.core.errors import AppError
from app.models.product_admin_ops import ModelConfiguration


def runtime_model_configuration(purpose: str, provider: str, model: str) -> dict[str, Any]:
    with SessionLocal() as db:
        deployed = list(db.scalars(
            select(ModelConfiguration)
            .where(
                ModelConfiguration.purpose == purpose,
                ModelConfiguration.status.in_(["active", "canary"]),
            )
            .order_by(ModelConfiguration.activated_at.desc())
        ))
        active = next((item for item in deployed if item.status == "active"), None)
        canary = next((item for item in deployed if item.status == "canary"), None)
        if active is None:
            return {"id": None, "purpose": purpose, "version": "environment", "provider": provider, "model": model, "configuration": {}}
        configured = active
        if canary is not None:
            subject = str(get_contextvars().get("request_id") or "background")
            if _rollout_bucket(purpose, canary.id, subject) < canary.rollout_percentage:
                configured = canary
        if configured.provider != provider:
            raise AppError(503, "MODEL_CONFIGURATION_PROVIDER_MISMATCH", "Active model configuration does not match the implemented provider")
        return {
            "id": configured.id,
            "purpose": configured.purpose,
            "version": configured.version,
            "provider": configured.provider,
            "model": configured.model,
            "configuration": configured.configuration or {},
            "output_schema_version": configured.output_schema_version,
            "rollout_status": configured.status,
            "rollout_percentage": configured.rollout_percentage,
        }


def _rollout_bucket(purpose: str, configuration_id: str, subject: str) -> int:
    digest = hashlib.sha256(f"{purpose}:{configuration_id}:{subject}".encode()).digest()
    return int.from_bytes(digest[:8], "big") % 100
