from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import DateTime, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


def utc_now() -> datetime:
    return datetime.now(UTC)


class IdempotencyRecord(Base):
    __tablename__ = "idempotency_records"
    __table_args__ = (
        UniqueConstraint(
            "scope",
            "operation",
            "idempotency_key",
            name="uq_idempotency_scope_operation_key",
        ),
        Index("ix_idempotency_expires_at", "expires_at"),
    )

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid4()),
    )
    scope: Mapped[str] = mapped_column(String(120), nullable=False)
    operation: Mapped[str] = mapped_column(String(120), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="processing")
    resource_type: Mapped[str | None] = mapped_column(String(80), nullable=True)
    resource_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    response_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    response_body: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )


class OutboxEvent(Base):
    __tablename__ = "outbox_events"
    __table_args__ = (
        Index("ix_outbox_unpublished", "published_at", "occurred_at"),
        Index("ix_outbox_aggregate", "aggregate_type", "aggregate_id"),
    )

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid4()),
    )
    aggregate_type: Mapped[str] = mapped_column(String(80), nullable=False)
    aggregate_id: Mapped[str] = mapped_column(String(80), nullable=False)
    event_type: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    deduplication_key: Mapped[str | None] = mapped_column(String(255), nullable=True, unique=True)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    correlation_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
