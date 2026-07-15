from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_billing_contract_exposes_product_routes() -> None:
    source = (ROOT / "backend/app/api/v1/billing.py").read_text()
    for path in ("/billing/catalog", "/billing/feature-pricing", "/billing/signup-trial-policy", "/billing/subscription", "/billing/credits", "/billing/checkout-sessions", "/billing/portal-sessions", "/webhooks/payments/{provider}", "/admin/billing/catalog-versions", "/admin/credit-adjustments", "/admin/credit-adjustments/{adjustment_id}/approve", "/admin/credit-adjustments/{adjustment_id}/reject"):
        assert path in source


def test_credit_ledger_is_immutable_and_bucketed() -> None:
    migration = (ROOT / "migrations/versions/20260714_0012_product_billing.py").read_text()
    assert "credit ledger entries are immutable" in migration
    assert "product_credit_reservation_allocations" in migration
    assert '"trial", 1' in (ROOT / "backend/app/services/product_billing.py").read_text()
    assert '"subscription", 2' in (ROOT / "backend/app/services/product_billing.py").read_text()
    assert '"topup", 3' in (ROOT / "backend/app/services/product_billing.py").read_text()


def test_approved_product_pricing_is_seeded() -> None:
    migration = (ROOT / "migrations/versions/20260714_0012_product_billing.py").read_text()
    for value in ("49000", "99000", "199000", "70000", "100000", "200000", "300000"):
        assert value in migration
    assert '("202", "cv_analysis", 10, None)' in migration
    assert '("204", "interview", 25, 30)' in migration
    assert '"credit_grant": 50' in migration
    assert '"valid_days": 7' in migration


def test_high_value_adjustments_require_dual_control() -> None:
    model = (ROOT / "backend/app/models/product_billing.py").read_text()
    service = (ROOT / "backend/app/services/product_billing.py").read_text()
    assert "CreditAdjustmentApproval" in model
    assert "DUAL_CONTROL_SELF_APPROVAL_FORBIDDEN" in service
    assert "credit_adjustment_dual_control_threshold" in service
