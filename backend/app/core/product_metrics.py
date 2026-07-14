from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Any, Callable

from prometheus_client import REGISTRY, CollectorRegistry
from prometheus_client.core import GaugeMetricFamily
from sqlalchemy import func, select

from app.core.db import SessionLocal, engine
from app.models.foundation import OutboxEvent
from app.models.product_admin_ops import OperationalJob, OperationalJobDispatch
from app.models.product_interview import ProductInterview
from app.models.product_jobs import JobSearchDispatch, ProductJob
from app.models.product_privacy import PrivacyArtifact, PrivacyDispatch
from app.models.product_recommendations import RecommendationDispatch


def _age_seconds(now: datetime, value: datetime | None) -> float:
    if value is None:
        return 0.0
    if value.tzinfo is None:
        now = now.replace(tzinfo=None)
    return max(0.0, (now - value).total_seconds())


def _runtime_snapshot() -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        queue_rows = list(
            db.execute(
                select(OperationalJob.queue, func.count(), func.min(OperationalJob.created_at))
                .where(OperationalJob.status == "queued")
                .group_by(OperationalJob.queue)
            )
        )
        queues = [(str(queue), int(depth), _age_seconds(now, oldest)) for queue, depth, oldest in queue_rows]
        if not queues:
            queues = [("celery", 0, 0.0)]

        dispatches = []
        dispatch_specs = (
            ("ai", OutboxEvent, OutboxEvent.published_at.is_(None), OutboxEvent.occurred_at),
            ("job_search", JobSearchDispatch, JobSearchDispatch.status == "pending", JobSearchDispatch.created_at),
            ("recommendation", RecommendationDispatch, RecommendationDispatch.status == "pending", RecommendationDispatch.created_at),
            ("privacy", PrivacyDispatch, PrivacyDispatch.status == "pending", PrivacyDispatch.created_at),
            ("admin_retry", OperationalJobDispatch, OperationalJobDispatch.status == "pending", OperationalJobDispatch.created_at),
        )
        for name, model, pending, created_at in dispatch_specs:
            depth, oldest = db.execute(select(func.count()).select_from(model).where(pending).add_columns(func.min(created_at))).one()
            dispatches.append((name, int(depth), _age_seconds(now, oldest)))

        interview_counts = {"live": 0, "interrupted": 0}
        for status, count in db.execute(
            select(ProductInterview.status, func.count())
            .where(ProductInterview.status.in_(interview_counts))
            .group_by(ProductInterview.status)
        ):
            interview_counts[str(status)] = int(count)

        job_counts = {status: 0 for status in ("active", "stale", "expired", "invalid", "unavailable")}
        for status, count in db.execute(select(ProductJob.status, func.count()).group_by(ProductJob.status)):
            job_counts[str(status)] = int(count)
        oldest_active = db.scalar(select(func.min(ProductJob.last_seen_at)).where(ProductJob.status == "active"))
        expired_artifacts, oldest_expiry = db.execute(
            select(func.count(), func.min(PrivacyArtifact.expires_at)).where(
                PrivacyArtifact.deleted_at.is_(None),
                PrivacyArtifact.expires_at <= now,
            )
        ).one()

    return {
        "queues": queues,
        "dispatches": dispatches,
        "interviews": interview_counts,
        "jobs": job_counts,
        "oldest_active_job_age": _age_seconds(now, oldest_active),
        "privacy_retention": (int(expired_artifacts), _age_seconds(now, oldest_expiry)),
    }


def _pool_value(name: str) -> float:
    value = getattr(engine.pool, name, None)
    if not callable(value):
        return 0.0
    try:
        return max(0.0, float(value()))
    except Exception:
        return 0.0


class ProductRuntimeCollector:
    def __init__(self, snapshot_loader: Callable[[], dict[str, Any]] | None = None) -> None:
        self.snapshot_loader = snapshot_loader or _runtime_snapshot

    def collect(self):
        try:
            snapshot = self.snapshot_loader()
            scrape_success = 1.0
        except Exception:
            snapshot = {
                "queues": [("celery", 0, 0.0)],
                "dispatches": [],
                "interviews": {"live": 0, "interrupted": 0},
                "jobs": {},
                "oldest_active_job_age": 0.0,
                "privacy_retention": (0, 0.0),
            }
            scrape_success = 0.0

        success = GaugeMetricFamily("qatth_runtime_metrics_scrape_success", "Whether the runtime DB metrics snapshot succeeded.")
        success.add_metric([], scrape_success)
        yield success

        pool = GaugeMetricFamily("qatth_db_pool_connections", "SQLAlchemy connection pool state.", labels=["state"])
        for state, value in (
            ("size", _pool_value("size")),
            ("checked_out", _pool_value("checkedout")),
            ("checked_in", _pool_value("checkedin")),
            ("overflow", _pool_value("overflow")),
        ):
            pool.add_metric([state], value)
        yield pool

        queue_depth = GaugeMetricFamily("qatth_queue_projected_depth", "Queued operational jobs by queue.", labels=["queue"])
        queue_age = GaugeMetricFamily("qatth_queue_oldest_age_seconds", "Age of the oldest queued operational job.", labels=["queue"])
        for queue, depth, age in snapshot["queues"]:
            queue_depth.add_metric([queue], depth)
            queue_age.add_metric([queue], age)
        yield queue_depth
        yield queue_age

        dispatch_depth = GaugeMetricFamily("qatth_dispatch_pending", "Unpublished transactional dispatches.", labels=["dispatch"])
        dispatch_age = GaugeMetricFamily("qatth_dispatch_oldest_age_seconds", "Age of the oldest unpublished dispatch.", labels=["dispatch"])
        for dispatch, depth, age in snapshot["dispatches"]:
            dispatch_depth.add_metric([dispatch], depth)
            dispatch_age.add_metric([dispatch], age)
        yield dispatch_depth
        yield dispatch_age

        interviews = GaugeMetricFamily("qatth_interview_active", "Active interview sessions by state.", labels=["status"])
        for status, count in snapshot["interviews"].items():
            interviews.add_metric([status], count)
        yield interviews

        jobs = GaugeMetricFamily("qatth_job_catalog", "Job catalog postings by freshness state.", labels=["status"])
        for status, count in snapshot["jobs"].items():
            jobs.add_metric([status], count)
        yield jobs

        job_age = GaugeMetricFamily("qatth_job_oldest_active_age_seconds", "Age since the least recently seen active posting.")
        job_age.add_metric([], snapshot["oldest_active_job_age"])
        yield job_age

        expired_count, expired_age = snapshot.get("privacy_retention", (0, 0.0))
        privacy_count = GaugeMetricFamily("qatth_privacy_expired_artifacts", "Expired privacy artifacts awaiting deletion.")
        privacy_count.add_metric([], expired_count)
        yield privacy_count
        privacy_age = GaugeMetricFamily("qatth_privacy_expired_artifact_oldest_age_seconds", "Age past expiry of the oldest privacy artifact awaiting deletion.")
        privacy_age.add_metric([], expired_age)
        yield privacy_age


_registration_lock = threading.Lock()
_registered_registries: set[int] = set()


def register_product_metrics(registry: CollectorRegistry | None = None) -> None:
    target = registry or REGISTRY
    registry_id = id(target)
    with _registration_lock:
        if registry_id in _registered_registries:
            return
        target.register(ProductRuntimeCollector())
        _registered_registries.add(registry_id)
