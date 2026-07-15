import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import AppError
from app.models.foundation import IdempotencyRecord, OutboxEvent


@dataclass(frozen=True)
class IdempotencyResult:
    record: IdempotencyRecord
    replayed: bool


class IdempotencyService:
    def __init__(self, db: Session) -> None:
        self.db = db

    @staticmethod
    def request_hash(payload: Any) -> str:
        serialized = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    def begin(
        self,
        *,
        scope: str,
        operation: str,
        key: str,
        request_hash: str,
    ) -> IdempotencyResult:
        if not 8 <= len(key) <= 128:
            raise AppError(
                status_code=400,
                code="INVALID_IDEMPOTENCY_KEY",
                message="Idempotency-Key must contain between 8 and 128 characters.",
            )

        existing = self.db.execute(
            select(IdempotencyRecord).where(
                IdempotencyRecord.scope == scope,
                IdempotencyRecord.operation == operation,
                IdempotencyRecord.idempotency_key == key,
            )
        ).scalar_one_or_none()
        if existing:
            if existing.request_hash != request_hash:
                raise AppError(
                    status_code=409,
                    code="IDEMPOTENCY_CONFLICT",
                    message="The idempotency key was already used with another request.",
                )
            return IdempotencyResult(record=existing, replayed=True)

        settings = get_settings()
        record = IdempotencyRecord(
            scope=scope,
            operation=operation,
            idempotency_key=key,
            request_hash=request_hash,
            status="processing",
            expires_at=datetime.now(UTC)
            + timedelta(seconds=settings.idempotency_ttl_seconds),
        )
        self.db.add(record)
        self.db.flush()
        return IdempotencyResult(record=record, replayed=False)

    def complete(
        self,
        record: IdempotencyRecord,
        *,
        resource_type: str,
        resource_id: str,
        response_status: int,
        response_body: dict[str, Any] | None = None,
    ) -> None:
        record.status = "completed"
        record.resource_type = resource_type
        record.resource_id = resource_id
        record.response_status = response_status
        record.response_body = response_body
        record.completed_at = datetime.now(UTC)


def enqueue_outbox(
    db: Session,
    *,
    aggregate_type: str,
    aggregate_id: str,
    event_type: str,
    payload: dict[str, Any],
    correlation_id: str,
) -> OutboxEvent:
    event = OutboxEvent(
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        event_type=event_type,
        payload=payload,
        correlation_id=correlation_id,
    )
    db.add(event)
    db.flush()
    return event
