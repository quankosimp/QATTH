from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_interview_reserves_credit_at_realtime_boundary() -> None:
    source = (ROOT / "backend/app/services/product_interview.py").read_text()
    create_body = source.split("def create(", 1)[1].split("def list(", 1)[0]
    token_body = source.split("def create_realtime_token(", 1)[1].split("def consume_realtime_token(", 1)[0]
    consume_body = source.split("def consume_realtime_token(", 1)[1].split("def mark_interrupted(", 1)[0]
    assert "ProductBillingService" not in create_body
    assert '"interview_token"' in token_body
    assert "with_for_update" in token_body
    assert "realtime_token_expired" in token_body
    assert "reservation.expires_at" in consume_body


def test_interview_captures_only_after_successful_provider_output_delivery() -> None:
    service = (ROOT / "backend/app/services/product_interview.py").read_text()
    gateway = (ROOT / "backend/app/services/gemini_interview_gateway.py").read_text()
    model = (ROOT / "backend/app/models/product_interview.py").read_text()
    migration = (ROOT / "migrations/versions/20260715_0021_interview_billing_boundary.py").read_text()
    for field in ("billable_started_at", "billable_event_id"):
        assert field in service
        assert field in model
        assert field in migration
    assert "await websocket.send_json" in gateway
    assert "mark_billable_started(interview_id, event.id)" in gateway
    assert 'release(interview.credit_reservation_id, "interview_not_billable")' in service


def test_reservation_reconciliation_uses_domain_outcomes() -> None:
    source = (ROOT / "backend/app/services/product_billing.py").read_text()
    body = source.split("def _reservation_reconciliation_action", 1)[1].split("def create_checkout", 1)[0]
    for evidence in (
        "CV_ANALYSIS_TIMEOUT",
        'analysis.status == "completed"',
        "interview.billable_started_at is not None",
        'interview.status = "timed_out"',
    ):
        assert evidence in body
    assert "with_for_update(skip_locked=True)" in source
    assert 'action == "capture"' in source
    assert 'action == "release"' in source
