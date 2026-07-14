from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx

from app.core.config import get_settings
from app.core.errors import AppError


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class ProviderRedirect:
    provider_session_id: str
    url: str
    expires_at: datetime


@dataclass(frozen=True)
class NormalizedPaymentEvent:
    event_id: str
    event_type: str
    payload: dict[str, Any]


class PaymentAdapter:
    provider = "disabled"

    def create_checkout(
        self,
        checkout_id: str,
        offer_snapshot: dict[str, Any],
        success_url: str,
        cancel_url: str,
    ) -> ProviderRedirect:
        raise AppError(503, "PAYMENT_PROVIDER_NOT_CONFIGURED", "Payment provider is not configured")

    def create_portal(self, provider_customer_id: str, return_url: str) -> ProviderRedirect:
        raise AppError(503, "PAYMENT_PROVIDER_NOT_CONFIGURED", "Payment provider is not configured")

    def verify_webhook(
        self,
        raw_body: bytes,
        signature: str | None,
        payload: dict[str, Any],
    ) -> NormalizedPaymentEvent:
        raise AppError(503, "PAYMENT_PROVIDER_NOT_CONFIGURED", "Payment provider is not configured")

    def reconcile_checkout(self, provider_session_id: str) -> list[NormalizedPaymentEvent]:
        raise AppError(503, "PAYMENT_PROVIDER_NOT_CONFIGURED", "Payment provider is not configured")

    def reconcile_subscription(self, provider_subscription_id: str) -> list[NormalizedPaymentEvent]:
        raise AppError(503, "PAYMENT_PROVIDER_NOT_CONFIGURED", "Payment provider is not configured")


class MockPaymentAdapter(PaymentAdapter):
    provider = "mock"

    def __init__(self, secret: str) -> None:
        self.secret = secret

    def create_checkout(
        self,
        checkout_id: str,
        offer_snapshot: dict[str, Any],
        success_url: str,
        cancel_url: str,
    ) -> ProviderRedirect:
        del offer_snapshot, cancel_url
        parts = urlsplit(success_url)
        query = parse_qsl(parts.query, keep_blank_values=True)
        query.append(("checkout_session_id", checkout_id))
        redirect_url = urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))
        return ProviderRedirect(checkout_id, redirect_url, _utcnow() + timedelta(minutes=30))

    def create_portal(self, provider_customer_id: str, return_url: str) -> ProviderRedirect:
        return ProviderRedirect(provider_customer_id, return_url, _utcnow() + timedelta(minutes=15))

    def verify_webhook(
        self,
        raw_body: bytes,
        signature: str | None,
        payload: dict[str, Any],
    ) -> NormalizedPaymentEvent:
        if not signature:
            raise AppError(401, "PAYMENT_SIGNATURE_REQUIRED", "Payment signature is required")
        expected = hmac.new(self.secret.encode(), raw_body, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, signature):
            raise AppError(401, "PAYMENT_SIGNATURE_INVALID", "Payment signature is invalid")
        event_id = str(payload.get("event_id") or "")
        event_type = str(payload.get("event_type") or "")
        data = payload.get("data")
        if not event_id or not event_type or not isinstance(data, dict):
            raise AppError(422, "PAYMENT_EVENT_INVALID", "Payment event is malformed")
        return NormalizedPaymentEvent(event_id, event_type, data)

    def reconcile_checkout(self, provider_session_id: str) -> list[NormalizedPaymentEvent]:
        del provider_session_id
        return []

    def reconcile_subscription(self, provider_subscription_id: str) -> list[NormalizedPaymentEvent]:
        del provider_subscription_id
        return []


class PaddlePaymentAdapter(PaymentAdapter):
    provider = "paddle"
    _ALLOWED_BASE_URLS = {"https://api.paddle.com", "https://sandbox-api.paddle.com"}

    def __init__(
        self,
        api_key: str,
        webhook_secret: str,
        price_ids: dict[str, str],
        api_base_url: str = "https://api.paddle.com",
        webhook_tolerance_seconds: int = 5,
        timeout_seconds: float = 10.0,
        client: httpx.Client | None = None,
        now: Callable[[], datetime] = _utcnow,
    ) -> None:
        normalized_base_url = api_base_url.rstrip("/")
        if normalized_base_url not in self._ALLOWED_BASE_URLS:
            raise AppError(503, "PAYMENT_PROVIDER_URL_INVALID", "Paddle API URL is not allowed")
        if not api_key or not webhook_secret:
            raise AppError(503, "PAYMENT_PROVIDER_NOT_CONFIGURED", "Paddle credentials are not configured")
        self.webhook_secret = webhook_secret
        self.price_ids = dict(price_ids)
        self.webhook_tolerance_seconds = max(1, webhook_tolerance_seconds)
        self.now = now
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Paddle-Version": "1",
        }
        self.client = client or httpx.Client(base_url=normalized_base_url, timeout=timeout_seconds)
        self.client.headers.update(headers)

    def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        try:
            response = self.client.post(path, json=body)
        except httpx.HTTPError as exc:
            raise AppError(503, "PAYMENT_PROVIDER_UNAVAILABLE", "Payment provider is unavailable") from exc
        if response.status_code >= 400:
            request_id = response.headers.get("request-id") or response.headers.get("x-request-id")
            details = {"provider": self.provider}
            if request_id:
                details["provider_request_id"] = request_id
            raise AppError(
                502,
                "PAYMENT_PROVIDER_REJECTED",
                "Payment provider rejected the request",
                details=details,
            )
        try:
            result = response.json()
        except ValueError as exc:
            raise AppError(502, "PAYMENT_PROVIDER_RESPONSE_INVALID", "Payment provider returned invalid JSON") from exc
        data = result.get("data") if isinstance(result, dict) else None
        if not isinstance(data, dict):
            raise AppError(502, "PAYMENT_PROVIDER_RESPONSE_INVALID", "Payment provider response is malformed")
        return data

    def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any] | list[dict[str, Any]]:
        try:
            response = self.client.get(path, params=params)
        except httpx.HTTPError as exc:
            raise AppError(503, "PAYMENT_PROVIDER_UNAVAILABLE", "Payment provider is unavailable") from exc
        if response.status_code >= 400:
            request_id = response.headers.get("request-id") or response.headers.get("x-request-id")
            details = {"provider": self.provider}
            if request_id:
                details["provider_request_id"] = request_id
            raise AppError(
                502,
                "PAYMENT_PROVIDER_REJECTED",
                "Payment provider rejected the reconciliation request",
                details=details,
            )
        try:
            result = response.json()
        except ValueError as exc:
            raise AppError(502, "PAYMENT_PROVIDER_RESPONSE_INVALID", "Payment provider returned invalid JSON") from exc
        data = result.get("data") if isinstance(result, dict) else None
        if isinstance(data, dict):
            return data
        if isinstance(data, list) and all(isinstance(item, dict) for item in data):
            return data
        raise AppError(502, "PAYMENT_PROVIDER_RESPONSE_INVALID", "Payment provider response is malformed")

    def create_checkout(
        self,
        checkout_id: str,
        offer_snapshot: dict[str, Any],
        success_url: str,
        cancel_url: str,
    ) -> ProviderRedirect:
        offer_code = str(offer_snapshot.get("code") or "")
        provider_price_id = self.price_ids.get(offer_code)
        if not provider_price_id:
            raise AppError(503, "PAYMENT_PRICE_NOT_CONFIGURED", "Provider price mapping is not configured for this offer")
        data = self._post(
            "/transactions",
            {
                "items": [{"price_id": provider_price_id, "quantity": 1}],
                "custom_data": {
                    "qatth_checkout_id": checkout_id,
                    "qatth_offer_id": str(offer_snapshot.get("id") or ""),
                },
            },
        )
        transaction_id = str(data.get("id") or "")
        checkout = data.get("checkout")
        checkout_url = checkout.get("url") if isinstance(checkout, dict) else None
        if not transaction_id or not isinstance(checkout_url, str) or not checkout_url.startswith("https://"):
            raise AppError(502, "PAYMENT_PROVIDER_RESPONSE_INVALID", "Paddle did not return a checkout URL")
        return ProviderRedirect(transaction_id, checkout_url, self.now() + timedelta(minutes=30))

    def create_portal(self, provider_customer_id: str, return_url: str) -> ProviderRedirect:
        del return_url
        if not provider_customer_id.startswith("ctm_"):
            raise AppError(409, "PAYMENT_CUSTOMER_NOT_FOUND", "Subscription has no valid provider customer")
        data = self._post(f"/customers/{provider_customer_id}/portal-sessions", {})
        urls = data.get("urls")
        general = urls.get("general") if isinstance(urls, dict) else None
        overview = general.get("overview") if isinstance(general, dict) else None
        session_id = str(data.get("id") or "")
        if not session_id or not isinstance(overview, str) or not overview.startswith("https://"):
            raise AppError(502, "PAYMENT_PROVIDER_RESPONSE_INVALID", "Paddle did not return a portal URL")
        return ProviderRedirect(session_id, overview, self.now() + timedelta(minutes=15))

    def verify_webhook(
        self,
        raw_body: bytes,
        signature: str | None,
        payload: dict[str, Any],
    ) -> NormalizedPaymentEvent:
        timestamp, signatures = self._parse_signature(signature)
        if abs(int(self.now().timestamp()) - timestamp) > self.webhook_tolerance_seconds:
            raise AppError(401, "PAYMENT_SIGNATURE_EXPIRED", "Payment signature is outside the replay window")
        signed_payload = str(timestamp).encode() + b":" + raw_body
        expected = hmac.new(self.webhook_secret.encode(), signed_payload, hashlib.sha256).hexdigest()
        if not any(hmac.compare_digest(expected, candidate) for candidate in signatures):
            raise AppError(401, "PAYMENT_SIGNATURE_INVALID", "Payment signature is invalid")
        return self._normalize_event(payload)

    @staticmethod
    def _parse_signature(signature: str | None) -> tuple[int, list[str]]:
        if not signature:
            raise AppError(401, "PAYMENT_SIGNATURE_REQUIRED", "Paddle-Signature is required")
        values: dict[str, list[str]] = {}
        for part in signature.split(";"):
            key, separator, value = part.strip().partition("=")
            if separator and key and value:
                values.setdefault(key, []).append(value)
        try:
            timestamp = int(values["ts"][0])
        except (KeyError, IndexError, ValueError) as exc:
            raise AppError(401, "PAYMENT_SIGNATURE_INVALID", "Paddle-Signature is malformed") from exc
        signatures = values.get("h1", [])
        if timestamp <= 0 or not signatures:
            raise AppError(401, "PAYMENT_SIGNATURE_INVALID", "Paddle-Signature is malformed")
        return timestamp, signatures

    @staticmethod
    def _normalize_event(payload: dict[str, Any]) -> NormalizedPaymentEvent:
        event_id = str(payload.get("event_id") or "")
        provider_event_type = str(payload.get("event_type") or "")
        data = payload.get("data")
        if not event_id or not provider_event_type or not isinstance(data, dict):
            raise AppError(422, "PAYMENT_EVENT_INVALID", "Paddle event is malformed")

        normalized_type = "ignored"
        normalized: dict[str, Any] = {"provider_event_type": provider_event_type}
        if provider_event_type == "transaction.completed":
            transaction_id = str(data.get("id") or "")
            details = data.get("details") if isinstance(data.get("details"), dict) else {}
            totals = details.get("totals") if isinstance(details.get("totals"), dict) else {}
            custom_data = data.get("custom_data") if isinstance(data.get("custom_data"), dict) else {}
            billing_period = data.get("billing_period") if isinstance(data.get("billing_period"), dict) else {}
            normalized_type = "subscription.renewed" if data.get("origin") == "subscription_recurring" else "checkout.completed"
            normalized.update(
                {
                    "checkout_session_id": transaction_id,
                    "transaction_id": transaction_id,
                    "subscription_id": data.get("subscription_id"),
                    "provider_customer_id": data.get("customer_id"),
                    "offer_id": custom_data.get("qatth_offer_id"),
                    "amount_minor": totals.get("grand_total"),
                    "currency": data.get("currency_code") or totals.get("currency_code"),
                    "period_reference": transaction_id,
                    "period_start": billing_period.get("starts_at"),
                    "period_end": billing_period.get("ends_at"),
                }
            )
        elif provider_event_type in {"adjustment.created", "adjustment.updated"}:
            action = str(data.get("action") or "")
            status = str(data.get("status") or "")
            if status == "approved" and action in {"refund", "chargeback"}:
                totals = data.get("totals") if isinstance(data.get("totals"), dict) else {}
                normalized_type = "payment.refunded" if action == "refund" else "payment.chargeback"
                normalized.update(
                    {
                        "transaction_id": data.get("transaction_id"),
                        "period_reference": data.get("transaction_id"),
                        "amount_minor": totals.get("total"),
                        "currency": data.get("currency_code"),
                    }
                )
        elif provider_event_type == "subscription.canceled":
            normalized_type = "subscription.cancelled"
            normalized["subscription_id"] = data.get("id")

        return NormalizedPaymentEvent(event_id, normalized_type, normalized)

    @staticmethod
    def _reconciliation_payload(event_type: str, data: dict[str, Any]) -> dict[str, Any]:
        entity_id = str(data.get("id") or "unknown")
        version = str(data.get("updated_at") or data.get("status") or "unknown")
        digest = hashlib.sha256(f"{event_type}:{entity_id}:{version}".encode()).hexdigest()[:32]
        return {
            "event_id": f"reconcile_{digest}",
            "event_type": event_type,
            "occurred_at": data.get("updated_at"),
            "data": data,
        }

    def reconcile_checkout(self, provider_session_id: str) -> list[NormalizedPaymentEvent]:
        data = self._get(f"/transactions/{provider_session_id}")
        if not isinstance(data, dict) or data.get("status") != "completed":
            return []
        return [self._normalize_event(self._reconciliation_payload("transaction.completed", data))]

    def reconcile_subscription(self, provider_subscription_id: str) -> list[NormalizedPaymentEvent]:
        subscription = self._get(f"/subscriptions/{provider_subscription_id}")
        if not isinstance(subscription, dict):
            raise AppError(502, "PAYMENT_PROVIDER_RESPONSE_INVALID", "Paddle subscription response is malformed")
        events: list[NormalizedPaymentEvent] = []
        if subscription.get("status") == "canceled":
            events.append(self._normalize_event(self._reconciliation_payload("subscription.canceled", subscription)))
        transactions = self._get(
            "/transactions",
            params={
                "subscription_id": provider_subscription_id,
                "status": "completed",
                "origin": "subscription_recurring",
                "order_by": "updated_at[ASC]",
                "per_page": 30,
            },
        )
        if not isinstance(transactions, list):
            raise AppError(502, "PAYMENT_PROVIDER_RESPONSE_INVALID", "Paddle transactions response is malformed")
        for transaction in transactions:
            events.append(self._normalize_event(self._reconciliation_payload("transaction.completed", transaction)))
        return events


_REDACTED_PAYMENT_KEYS = {
    "address",
    "billing_details",
    "card",
    "customer_email",
    "email",
    "first_name",
    "last_name",
    "name",
    "payment_method",
    "phone",
}


def redact_payment_payload(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): "[REDACTED]" if str(key).lower() in _REDACTED_PAYMENT_KEYS else redact_payment_payload(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_payment_payload(item) for item in value]
    return value


def payment_adapter(provider: str | None = None) -> PaymentAdapter:
    settings = get_settings()
    selected = (provider or settings.payment_provider or "").strip().lower()
    if selected == "paddle":
        return PaddlePaymentAdapter(
            api_key=settings.payment_api_key or "",
            webhook_secret=settings.payment_webhook_secret or "",
            price_ids=settings.payment_paddle_price_ids,
            api_base_url=settings.payment_paddle_api_base_url,
            webhook_tolerance_seconds=settings.payment_webhook_tolerance_seconds,
            timeout_seconds=settings.payment_http_timeout_seconds,
        )
    if selected == "mock" and settings.environment.lower() in {"local", "development", "test"}:
        return MockPaymentAdapter(settings.payment_webhook_secret or "local-payment-secret")
    return PaymentAdapter()
