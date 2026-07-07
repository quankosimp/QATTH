import hashlib
import json
from datetime import UTC, datetime
from time import perf_counter
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.models.db import ModelRun
from app.schemas.ai import ModelRunList, ModelRunRead


class ModelRunTimer:
    def __init__(self, *, service: "ModelRunService", run: ModelRun) -> None:
        self.service = service
        self.run = run
        self.started = perf_counter()

    def complete(self, *, output_json: dict[str, Any] | None = None) -> None:
        elapsed = int((perf_counter() - self.started) * 1000)
        self.service.complete(run=self.run, latency_ms=elapsed, output_json=output_json)

    def fail(self, *, error: str) -> None:
        elapsed = int((perf_counter() - self.started) * 1000)
        self.service.fail(run=self.run, latency_ms=elapsed, error=error)


class ModelRunService:
    def __init__(self, *, db: Session) -> None:
        self.db = db

    def start(
        self,
        *,
        user_id: str | None,
        run_type: str,
        provider: str,
        model: str,
        input_payload: dict[str, Any],
        output_schema: str | None,
        prompt_version_id: str | None = None,
    ) -> ModelRunTimer:
        run = ModelRun(
            user_id=user_id,
            run_type=run_type,
            provider=provider,
            model=model,
            status="running",
            prompt_version_id=prompt_version_id,
            input_hash=self._hash_payload(input_payload),
            output_schema=output_schema,
        )
        self.db.add(run)
        self.db.commit()
        self.db.refresh(run)
        return ModelRunTimer(service=self, run=run)

    def complete(self, *, run: ModelRun, latency_ms: int, output_json: dict[str, Any] | None) -> None:
        run.status = "completed"
        run.latency_ms = latency_ms
        run.output_json = output_json
        run.completed_at = datetime.now(UTC)
        self.db.commit()

    def fail(self, *, run: ModelRun, latency_ms: int, error: str) -> None:
        run.status = "failed"
        run.latency_ms = latency_ms
        run.error_message = error
        run.completed_at = datetime.now(UTC)
        self.db.commit()

    def list(self, *, status: str | None = None, run_type: str | None = None) -> ModelRunList:
        statement = select(ModelRun).order_by(ModelRun.created_at.desc())
        if status:
            statement = statement.where(ModelRun.status == status)
        if run_type:
            statement = statement.where(ModelRun.run_type == run_type)
        runs = list(self.db.scalars(statement).all())
        return ModelRunList(items=[self._to_read(run) for run in runs], total=len(runs))

    def mark_retry_requested(self, *, run_id: str) -> ModelRunRead:
        run = self.db.get(ModelRun, run_id)
        if not run:
            raise AppError(status_code=404, code="MODEL_RUN_NOT_FOUND", message="Model run not found.")
        run.status = "retry_requested"
        self.db.commit()
        self.db.refresh(run)
        return self._to_read(run)

    def _to_read(self, run: ModelRun) -> ModelRunRead:
        return ModelRunRead(
            run_id=run.id,
            user_id=run.user_id,
            run_type=run.run_type,
            provider=run.provider,
            model=run.model,
            status=run.status,
            prompt_version_id=run.prompt_version_id,
            input_hash=run.input_hash,
            output_schema=run.output_schema,
            latency_ms=run.latency_ms,
            output_json=run.output_json,
            error_message=run.error_message,
            created_at=run.created_at,
            completed_at=run.completed_at,
        )

    def _hash_payload(self, payload: dict[str, Any]) -> str:
        encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()
