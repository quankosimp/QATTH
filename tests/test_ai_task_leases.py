from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from app.services.task_leases import ProductTaskLeaseService


ROOT = Path(__file__).resolve().parents[1]


def test_task_lease_blocks_duplicate_and_allows_expired_takeover() -> None:
    now = datetime.now(timezone.utc)
    resource = SimpleNamespace(
        status="queued",
        processing_lease_id=None,
        processing_lease_expires_at=None,
    )

    assert ProductTaskLeaseService.claim(resource, "task-1", "processing", now)
    assert not ProductTaskLeaseService.claim(resource, "task-2", "processing", now)
    resource.processing_lease_expires_at = now - timedelta(seconds=1)
    assert ProductTaskLeaseService.claim(resource, "task-2", "processing", now)
    assert ProductTaskLeaseService.owns(resource, "task-2")
    ProductTaskLeaseService.clear(resource)
    assert resource.processing_lease_id is None


def test_ai_workers_are_bound_and_stalled_recovery_is_scheduled() -> None:
    tasks = (ROOT / "backend/app/workers/tasks.py").read_text()
    schedule = (ROOT / "backend/app/core/celery_app.py").read_text()
    migration = (ROOT / "migrations/versions/20260715_0028_ai_task_processing_leases.py").read_text()

    assert tasks.count("bind=True") >= 3
    assert "product.tasks.recover_stalled" in tasks
    assert "product.tasks.recover_stalled" in schedule
    assert "processing_lease_expires_at" in migration
