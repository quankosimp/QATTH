from __future__ import annotations

from typing import Any

from sqlalchemy import select

from app.core.db import SessionLocal
from app.core.errors import AppError
from app.models.product_admin_ops import ModelConfiguration


def runtime_model_configuration(purpose: str, provider: str, model: str) -> dict[str, Any]:
    with SessionLocal() as db:
        configured = db.scalar(
            select(ModelConfiguration)
            .where(ModelConfiguration.purpose == purpose, ModelConfiguration.status == "active")
            .order_by(ModelConfiguration.activated_at.desc())
        )
        if configured is None:
            return {"id": None, "purpose": purpose, "version": "environment", "provider": provider, "model": model, "configuration": {}}
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
        }
