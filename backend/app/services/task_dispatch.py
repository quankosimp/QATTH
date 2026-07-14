from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session
from structlog.contextvars import get_contextvars

from app.models.foundation import OutboxEvent


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ProductTaskDispatchService:
    topics = frozenset({"product.cv.extract", "product.cv.analyze", "product.interview.evaluate"})

    def __init__(self, db: Session) -> None:
        self.db = db

    def enqueue(self, topic: str, resource_type: str, resource_id: str) -> OutboxEvent:
        if topic not in self.topics:
            raise ValueError("Unsupported product task dispatch topic")
        key = topic + ":" + resource_id
        existing = self.db.scalar(select(OutboxEvent).where(OutboxEvent.deduplication_key == key))
        if existing is not None:
            return existing
        context = get_contextvars()
        event = OutboxEvent(
            aggregate_type=resource_type,
            aggregate_id=resource_id,
            event_type=topic,
            deduplication_key=key,
            payload={"resource_id": resource_id},
            correlation_id=str(context.get("request_id") or uuid4()),
            available_at=_utcnow(),
        )
        self.db.add(event)
        self.db.flush()
        return event

    def publish_resource(self, topic: str, resource_id: str) -> bool:
        event = self.db.scalar(
            select(OutboxEvent).where(OutboxEvent.deduplication_key == topic + ":" + resource_id)
        )
        return self.publish(event.id) if event is not None else False

    def publish(self, event_id: str) -> bool:
        event = self.db.scalar(select(OutboxEvent).where(OutboxEvent.id == event_id).with_for_update())
        if event is None or event.published_at is not None:
            return True
        if event.event_type not in self.topics or event.available_at > _utcnow():
            return False
        event.attempts += 1
        try:
            task = self._task(event.event_type)
            result = task.apply_async(
                args=[event.aggregate_id],
                headers={"request_id": event.correlation_id, "outbox_event_id": event.id},
            )
        except Exception as exc:
            event.last_error = type(exc).__name__
            event.available_at = _utcnow() + timedelta(seconds=min(300, 2 ** min(event.attempts, 8)))
            self.db.commit()
            return False
        event.payload = {**(event.payload or {}), "celery_task_id": result.id}
        event.published_at = _utcnow()
        event.last_error = None
        self.db.commit()
        return True

    def publish_pending(self, limit: int = 100) -> int:
        event_ids = list(
            self.db.scalars(
                select(OutboxEvent.id)
                .where(
                    OutboxEvent.event_type.in_(self.topics),
                    OutboxEvent.published_at.is_(None),
                    OutboxEvent.available_at <= _utcnow(),
                )
                .order_by(OutboxEvent.available_at, OutboxEvent.occurred_at)
                .limit(limit)
            )
        )
        return sum(1 for event_id in event_ids if self.publish(event_id))

    @staticmethod
    def _task(topic: str):
        from app.workers.tasks import analyze_product_cv_task, evaluate_product_interview_task, extract_product_cv_task

        return {
            "product.cv.extract": extract_product_cv_task,
            "product.cv.analyze": analyze_product_cv_task,
            "product.interview.evaluate": evaluate_product_interview_task,
        }[topic]
