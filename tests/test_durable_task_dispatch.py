from pathlib import Path

from app.services.task_dispatch import ProductTaskDispatchService


ROOT = Path(__file__).resolve().parents[1]


def test_product_ai_tasks_use_transactional_dispatch_boundary() -> None:
    cv = (ROOT / "backend/app/services/product_cv.py").read_text()
    interview = (ROOT / "backend/app/services/product_interview.py").read_text()
    schedule = (ROOT / "backend/app/core/celery_app.py").read_text()
    tasks = (ROOT / "backend/app/workers/tasks.py").read_text()

    assert ".delay(" not in cv
    assert ".delay(" not in interview
    for topic in ProductTaskDispatchService.topics:
        assert topic in cv or topic in interview
    assert "product.tasks.publish_dispatches" in schedule
    assert "product.tasks.publish_dispatches" in tasks


def test_dispatch_outbox_has_deduplication_and_retry_fields() -> None:
    model = (ROOT / "backend/app/models/foundation.py").read_text()
    migration = (ROOT / "migrations/versions/20260715_0027_durable_task_dispatch.py").read_text()
    for field in ("deduplication_key", "available_at"):
        assert field in model
        assert field in migration
