import hashlib
import hmac
import json
from datetime import datetime, timezone

import httpx
import pytest

from app.core.errors import AppError
from app.services.payment_adapter import PaddlePaymentAdapter, redact_payment_payload


NOW = datetime(2026, 7, 15, 12, 0, tzinfo=timezone.utc)


def _adapter(handler: httpx.MockTransport) -> PaddlePaymentAdapter:
    return PaddlePaymentAdapter(
        api_key="pdl_test_key",
        webhook_secret="pdl_webhook_secret",
        price_ids={"TOPUP_STARTER": "pri_01test"},
        api_base_url="https://sandbox-api.paddle.com",
        client=httpx.Client(transport=handler, base_url="https://sandbox-api.paddle.com"),
        now=lambda: NOW,
    )


def _signed_event(adapter: PaddlePaymentAdapter, event: dict, timestamp: int | None = None):
    raw = json.dumps(event, separators=(",", ":")).encode()
    ts = timestamp or int(NOW.timestamp())
    digest = hmac.new(b"pdl_webhook_secret", str(ts).encode() + b":" + raw, hashlib.sha256).hexdigest()
    return adapter.verify_webhook(raw, f"ts={ts};h1={digest}", event)


def test_paddle_checkout_uses_server_side_offer_mapping() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Paddle-Version"] == "1"
        body = json.loads(request.content)
        assert body["items"] == [{"price_id": "pri_01test", "quantity": 1}]
        assert body["custom_data"] == {"qatth_checkout_id": "checkout-1", "qatth_offer_id": "offer-1"}
        return httpx.Response(
            201,
            json={"data": {"id": "txn_01test", "checkout": {"url": "https://pay.example/txn_01test"}}},
        )

    adapter = _adapter(httpx.MockTransport(handler))
    redirect = adapter.create_checkout(
        "checkout-1",
        {"id": "offer-1", "code": "TOPUP_STARTER"},
        "https://app.example/success",
        "https://app.example/cancel",
    )
    assert redirect.provider_session_id == "txn_01test"


def test_paddle_webhook_verifies_replay_window_and_normalizes_transaction() -> None:
    adapter = _adapter(httpx.MockTransport(lambda request: httpx.Response(500)))
    event = {
        "event_id": "evt_01test",
        "event_type": "transaction.completed",
        "data": {
            "id": "txn_01test",
            "origin": "api",
            "customer_id": "ctm_01test",
            "subscription_id": None,
            "currency_code": "VND",
            "custom_data": {"qatth_offer_id": "offer-1"},
            "details": {"totals": {"grand_total": "70000", "currency_code": "VND"}},
            "billing_period": None,
        },
    }
    normalized = _signed_event(adapter, event)
    assert normalized.event_type == "checkout.completed"
    assert normalized.payload["period_reference"] == "txn_01test"
    assert normalized.payload["amount_minor"] == "70000"

    with pytest.raises(AppError):
        _signed_event(adapter, event, int(NOW.timestamp()) - 6)


def test_paddle_webhook_normalizes_renewal_and_approved_refund() -> None:
    adapter = _adapter(httpx.MockTransport(lambda request: httpx.Response(500)))
    renewal = {
        "event_id": "evt_renewal",
        "event_type": "transaction.completed",
        "data": {
            "id": "txn_renewal",
            "origin": "subscription_recurring",
            "customer_id": "ctm_01test",
            "subscription_id": "sub_01test",
            "currency_code": "VND",
            "details": {"totals": {"grand_total": "99000"}},
            "billing_period": {"starts_at": "2026-07-01T00:00:00Z", "ends_at": "2026-08-01T00:00:00Z"},
        },
    }
    refund = {
        "event_id": "evt_refund",
        "event_type": "adjustment.updated",
        "data": {
            "action": "refund",
            "status": "approved",
            "transaction_id": "txn_renewal",
            "currency_code": "VND",
            "totals": {"total": "49500"},
        },
    }
    assert _signed_event(adapter, renewal).event_type == "subscription.renewed"
    normalized_refund = _signed_event(adapter, refund)
    assert normalized_refund.event_type == "payment.refunded"
    assert normalized_refund.payload["period_reference"] == "txn_renewal"


def test_payment_payload_redaction_preserves_audit_fields() -> None:
    payload = {"event_id": "evt_1", "data": {"email": "student@example.com", "amount": "70000"}}
    assert redact_payment_payload(payload) == {
        "event_id": "evt_1",
        "data": {"email": "[REDACTED]", "amount": "70000"},
    }


def test_paddle_reconciliation_uses_provider_state_without_webhook_payload() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/subscriptions/sub_01test":
            return httpx.Response(
                200,
                json={"data": {"id": "sub_01test", "status": "canceled", "updated_at": "2026-07-15T12:00:00Z"}},
            )
        if request.url.path == "/transactions":
            assert request.url.params["origin"] == "subscription_recurring"
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "id": "txn_renewal",
                            "status": "completed",
                            "origin": "subscription_recurring",
                            "subscription_id": "sub_01test",
                            "customer_id": "ctm_01test",
                            "currency_code": "VND",
                            "updated_at": "2026-07-15T11:00:00Z",
                            "details": {"totals": {"grand_total": "99000"}},
                            "billing_period": {
                                "starts_at": "2026-07-01T00:00:00Z",
                                "ends_at": "2026-08-01T00:00:00Z",
                            },
                        }
                    ]
                },
            )
        return httpx.Response(404)

    events = _adapter(httpx.MockTransport(handler)).reconcile_subscription("sub_01test")
    assert [event.event_type for event in events] == ["subscription.cancelled", "subscription.renewed"]
    assert events[1].payload["period_reference"] == "txn_renewal"
