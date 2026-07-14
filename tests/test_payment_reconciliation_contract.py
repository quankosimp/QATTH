from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_payment_reconciliation_and_retention_are_scheduled() -> None:
    schedule = (ROOT / "backend/app/core/celery_app.py").read_text()
    tasks = (ROOT / "backend/app/workers/tasks.py").read_text()
    service = (ROOT / "backend/app/services/product_billing.py").read_text()
    for task_name in ("product.billing.reconcile_payments", "product.billing.cleanup_payment_payloads"):
        assert task_name in schedule
        assert task_name in tasks
    assert "reconcile_payment_provider" in service
    assert "cleanup_expired_payment_payloads" in service


def test_payment_inbox_tracks_processing_lease_and_payload_purge() -> None:
    model = (ROOT / "backend/app/models/product_billing.py").read_text()
    migration = (ROOT / "migrations/versions/20260715_0020_payment_reconciliation.py").read_text()
    for field in ("processing_started_at", "raw_payload_purged_at"):
        assert field in model
        assert field in migration


def test_checkout_does_not_transfer_client_redirect_urls_to_provider_metadata() -> None:
    adapter = (ROOT / "backend/app/services/payment_adapter.py").read_text()
    custom_data = adapter.split('"custom_data": {', 1)[1].split("}", 1)[0]
    assert "qatth_checkout_id" in custom_data
    assert "qatth_offer_id" in custom_data
    assert "success_url" not in custom_data
    assert "cancel_url" not in custom_data
