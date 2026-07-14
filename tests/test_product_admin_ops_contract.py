from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_admin_ops_contract_exposes_required_routes() -> None:
    source = (ROOT / "backend/app/api/v1/admin_ops.py").read_text()
    for path in ("/admin/model-configurations", "/admin/job-sources", "/ops/background-jobs", "/ops/background-jobs/{job_id}/retry"):
        assert path in source
    assert "require_product_scopes" in source


def test_privileged_audit_is_immutable_and_chained() -> None:
    service = (ROOT / "backend/app/services/product_admin_ops.py").read_text()
    migration = (ROOT / "migrations/versions/20260714_0014_product_admin_ops.py").read_text()
    assert "previous_hash" in service
    assert "event_hash" in service
    assert "privileged audit events are immutable" in migration


def test_celery_jobs_are_observable_and_scheduled() -> None:
    source = (ROOT / "backend/app/core/celery_app.py").read_text()
    assert "before_task_publish" in source
    assert "task_prerun" in source
    assert "task_failure" in source
    assert "beat_schedule" in source
