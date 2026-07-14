from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from app.core.config import get_settings
from app.core.errors import AppError


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

    def create_checkout(self, session_id: str, offer: dict[str, Any], success_url: str, cancel_url: str) -> ProviderRedirect:
        raise AppError(503, "PAYMENT_PROVIDER_NOT_CONFIGURED", "Payment provider is not configured")

    def create_portal(self, user_id: str, return_url: str) -> ProviderRedirect:
        raise AppError(503, "PAYMENT_PROVIDER_NOT_CONFIGURED", "Payment provider is not configured")

    def verify_webhook(self, raw_body: bytes, signature: str | None, payload: dict[str, Any]) -> NormalizedPaymentEvent:
        raise AppError(503, "PAYMENT_PROVIDER_NOT_CONFIGURED", "Payment provider is not configured")


class MockPaymentAdapter(PaymentAdapter):
    provider = "mock"

    def __init__(self) -> None:
        self.settings = get_settings()

    def create_checkout(self, session_id: str, offer: dict[str, Any], success_url: str, cancel_url: str) -> ProviderRedirect:
        parts = urlsplit(success_url)
        query = dict(parse_qsl(parts.query, keep_blank_values=True))
        query["checkout_session_id"] = session_id
        url = urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))
        return ProviderRedirect(provider_session_id=session_id, url=url, expires_at=datetime.now(timezone.utc) + timedelta(minutes=30))

    def create_portal(self, user_id: str, return_url: str) -> ProviderRedirect:
        return ProviderRedirect(provider_session_id="portal-" + user_id, url=return_url, expires_at=datetime.now(timezone.utc) + timedelta(minutes=10))

    def verify_webhook(self, raw_body: bytes, signature: str | None, payload: dict[str, Any]) -> NormalizedPaymentEvent:
        secret = str(self.settings.payment_webhook_secret or "")
        if not secret:
            raise AppError(503, "PAYMENT_WEBHOOK_NOT_CONFIGURED", "Payment webhook secret is not configured")
        expected = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
        if not signature or not hmac.compare_digest(expected, signature):
            raise AppError(401, "INVALID_WEBHOOK_SIGNATURE", "Payment webhook signature is invalid")
        event_id = str(payload.get("event_id") or "")
        event_type = str(payload.get("event_type") or "")
        data = payload.get("data")
        if not event_id or not event_type or not isinstance(data, dict):
            raise AppError(422, "INVALID_PAYMENT_EVENT", "Payment event is missing required fields")
        return NormalizedPaymentEvent(event_id=event_id, event_type=event_type, payload=data)


def payment_adapter(provider: str | None = None) -> PaymentAdapter:
    settings = get_settings()
    selected = str(provider or settings.payment_provider or "").lower()
    if selected == "mock" and str(settings.app_env).lower() in {"local", "development", "test"}:
        return MockPaymentAdapter()
    return PaymentAdapter()
