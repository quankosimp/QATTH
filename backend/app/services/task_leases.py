from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.foundation import OutboxEvent
from app.models.product_cv import CvAnalysis, CvScan
from app.models.product_interview import ProductInterviewReport
from app.services.task_dispatch import ProductTaskDispatchService


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ProductTaskLeaseService:
    lease_duration = timedelta(minutes=15)

    @classmethod
    def claim(cls, resource: Any, lease_id: str, active_status: str, now: datetime | None = None) -> bool:
        now = now or _utcnow()
        if (
            resource.processing_lease_id
            and resource.processing_lease_id != lease_id
            and resource.processing_lease_expires_at
            and resource.processing_lease_expires_at > now
        ):
            return False
        resource.processing_lease_id = lease_id
        resource.processing_lease_expires_at = now + cls.lease_duration
        resource.status = active_status
        return True

    @staticmethod
    def owns(resource: Any, lease_id: str) -> bool:
        return resource.processing_lease_id == lease_id

    @staticmethod
    def clear(resource: Any) -> None:
        resource.processing_lease_id = None
        resource.processing_lease_expires_at = None

    def __init__(self, db: Session) -> None:
        self.db = db

    def recover_stalled(self, limit: int = 100) -> dict[str, int]:
        now = _utcnow()
        stale_before = now - self.lease_duration
        dispatch = ProductTaskDispatchService(self.db)
        recovered = 0
        backfilled = 0
        specifications = (
            (CvScan, "queued", "extracting", "product.cv.extract", "cv_scan"),
            (CvAnalysis, "queued", "processing", "product.cv.analyze", "cv_analysis"),
            (ProductInterviewReport, "processing", "processing", "product.interview.evaluate", "interview_report"),
        )
        for model, waiting_status, active_status, topic, resource_type in specifications:
            if recovered + backfilled >= limit:
                break
            candidates = list(
                self.db.scalars(
                    select(model)
                    .where(model.status.in_({waiting_status, active_status}))
                    .order_by(model.updated_at)
                    .limit(limit - recovered - backfilled)
                    .with_for_update(skip_locked=True)
                )
            )
            for resource in candidates:
                event = self.db.scalar(
                    select(OutboxEvent).where(OutboxEvent.deduplication_key == topic + ":" + resource.id)
                )
                if event is None:
                    dispatch.enqueue(topic, resource_type, resource.id)
                    backfilled += 1
                    continue
                lease_expired = (
                    resource.status == active_status
                    and (
                        resource.processing_lease_expires_at is not None
                        and resource.processing_lease_expires_at <= now
                        or resource.processing_lease_id is None
                        and resource.updated_at <= stale_before
                    )
                )
                if not lease_expired:
                    continue
                resource.status = waiting_status
                self.clear(resource)
                event.published_at = None
                event.available_at = now
                event.last_error = "PROCESSING_LEASE_EXPIRED"
                recovered += 1
        self.db.commit()
        published = dispatch.publish_pending(limit)
        return {"recovered": recovered, "backfilled": backfilled, "published": published}
