from __future__ import annotations

import base64
import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlsplit

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import AppError
from app.core.identity_security import ProductCurrentUser
from app.models.db import User
from app.models.product_billing import (
    BillingCatalogVersion,
    BillingCheckoutSession,
    BillingCommand,
    BillingOffer,
    BillingSubscription,
    CreditAccount,
    CreditAdjustmentApproval,
    CreditBucket,
    CreditLedgerEntry,
    CreditReservation,
    CreditReservationAllocation,
    FeatureCreditPrice,
    PaymentEventInbox,
    SignupTrialGrant,
    SignupTrialPolicy,
)
from app.schemas.product_billing import (
    ActivateBillingCatalogRequest,
    BillingCatalogVersionView,
    BillingCatalogView,
    BillingOfferView,
    CreateBillingCatalogVersionRequest,
    CreateCheckoutRequest,
    CreditAccountView,
    CreditAdjustmentRequest,
    CreditAdjustmentDecisionRequest,
    CreditAdjustmentView,
    CreditBucketView,
    CreditLedgerEntryView,
    FeatureCreditPriceView,
    RedirectSessionView,
    SignupTrialPolicyView,
    SubscriptionView,
    UpdateFeatureCreditPriceRequest,
    UpdateSignupTrialPolicyRequest,
)
from app.services.payment_adapter import NormalizedPaymentEvent, payment_adapter, redact_payment_payload


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ProductBillingService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def active_catalog(self) -> BillingCatalogVersion:
        now = _utcnow()
        catalog = self.db.scalar(
            select(BillingCatalogVersion)
            .where(
                BillingCatalogVersion.market == "VN",
                BillingCatalogVersion.currency == "VND",
                BillingCatalogVersion.status == "active",
                BillingCatalogVersion.effective_from <= now,
                (BillingCatalogVersion.effective_to.is_(None)) | (BillingCatalogVersion.effective_to > now),
            )
            .order_by(BillingCatalogVersion.effective_from.desc())
        )
        if catalog is None:
            raise AppError(503, "BILLING_CATALOG_UNAVAILABLE", "Billing catalog is unavailable")
        return catalog

    def catalog_view(self) -> BillingCatalogView:
        catalog = self.active_catalog()
        offers = list(self.db.scalars(select(BillingOffer).where(BillingOffer.catalog_version_id == catalog.id, BillingOffer.active.is_(True)).order_by(BillingOffer.amount_minor)))
        prices = list(self.db.scalars(select(FeatureCreditPrice).where(FeatureCreditPrice.catalog_version_id == catalog.id).order_by(FeatureCreditPrice.feature_key)))
        offer_views = [self.offer_view(item, catalog) for item in offers]
        return BillingCatalogView(
            catalog_version=catalog.version_key,
            currency=catalog.currency,
            effective_from=catalog.effective_from,
            subscription_offers=[item for item in offer_views if item.offer_type == "subscription"],
            topup_offers=[item for item in offer_views if item.offer_type == "topup"],
            feature_prices=[self.price_view(item, catalog) for item in prices],
        )

    @staticmethod
    def offer_view(offer: BillingOffer, catalog: BillingCatalogVersion) -> BillingOfferView:
        return BillingOfferView(
            id=offer.id,
            code=offer.code,
            display_name=offer.display_name,
            offer_type=offer.offer_type,
            amount_minor=offer.amount_minor,
            currency=offer.currency,
            billing_interval=offer.billing_interval,
            credit_grant=offer.credit_grant,
            catalog_version=catalog.version_key,
        )

    @staticmethod
    def price_view(price: FeatureCreditPrice, catalog: BillingCatalogVersion) -> FeatureCreditPriceView:
        return FeatureCreditPriceView(
            feature_key=price.feature_key,
            credit_cost=price.credit_cost,
            maximum_duration_minutes=price.maximum_duration_minutes,
            catalog_version=catalog.version_key,
        )

    def feature_prices(self) -> list[FeatureCreditPriceView]:
        catalog = self.active_catalog()
        return [self.price_view(item, catalog) for item in self.db.scalars(select(FeatureCreditPrice).where(FeatureCreditPrice.catalog_version_id == catalog.id).order_by(FeatureCreditPrice.feature_key))]

    def active_trial_policy(self) -> SignupTrialPolicy:
        policy = self.db.scalar(
            select(SignupTrialPolicy)
            .where(SignupTrialPolicy.effective_from <= _utcnow())
            .order_by(SignupTrialPolicy.effective_from.desc(), SignupTrialPolicy.created_at.desc())
        )
        if policy is None:
            raise AppError(503, "TRIAL_POLICY_UNAVAILABLE", "Signup trial policy is unavailable")
        return policy

    def trial_policy_view(self) -> SignupTrialPolicyView:
        policy = self.active_trial_policy()
        return SignupTrialPolicyView(
            policy_key=policy.policy_key,
            enabled=policy.enabled,
            trigger=policy.trigger,
            credit_grant=policy.credit_grant,
            valid_days=policy.valid_days,
            grants_per_user=policy.grants_per_user,
            policy_version=policy.policy_version,
            effective_from=policy.effective_from,
        )

    def ensure_signup_trial(self, current: ProductCurrentUser) -> None:
        if not current.email_verified:
            return
        policy = self.active_trial_policy()
        if not policy.enabled:
            return
        existing = self.db.scalar(select(SignupTrialGrant).where(SignupTrialGrant.user_id == current.id, SignupTrialGrant.policy_key == policy.policy_key))
        if existing is not None:
            return
        account = self._account(current.id, lock=True)
        existing = self.db.scalar(select(SignupTrialGrant).where(SignupTrialGrant.user_id == current.id, SignupTrialGrant.policy_key == policy.policy_key))
        if existing is not None:
            return
        bucket = self._grant_bucket(
            account,
            "trial",
            "trial:" + policy.id + ":" + current.id,
            policy.credit_grant,
            _utcnow() + timedelta(days=policy.valid_days),
            "Signup trial credit",
            "signup_trial",
            policy.id,
            "trial:" + policy.id + ":" + current.id,
        )
        self.db.add(SignupTrialGrant(user_id=current.id, policy_id=policy.id, policy_key=policy.policy_key, bucket_id=bucket.id))
        self.db.flush()

    def current_subscription(self, current: ProductCurrentUser) -> SubscriptionView:
        subscription = self.db.scalar(
            select(BillingSubscription)
            .where(BillingSubscription.user_id == current.id)
            .order_by(BillingSubscription.created_at.desc())
        )
        if subscription is None:
            return SubscriptionView(id=None, offer=None, status="none", current_period_start=None, current_period_end=None, cancel_at_period_end=False, current_period_credit_grant=0)
        offer = self.db.get(BillingOffer, subscription.offer_id)
        catalog = self.db.get(BillingCatalogVersion, offer.catalog_version_id) if offer else None
        return SubscriptionView(
            id=subscription.id,
            offer=self.offer_view(offer, catalog) if offer and catalog else None,
            status=subscription.status,
            current_period_start=subscription.current_period_start,
            current_period_end=subscription.current_period_end,
            cancel_at_period_end=subscription.cancel_at_period_end,
            current_period_credit_grant=offer.credit_grant if offer and subscription.status in {"trialing", "active"} else 0,
        )

    def credit_account(self, current: ProductCurrentUser, cursor: str | None, limit: int) -> CreditAccountView:
        self.ensure_signup_trial(current)
        account = self._account(current.id, lock=True)
        self._expire_buckets(account)
        self.db.commit()
        buckets = list(self.db.scalars(select(CreditBucket).where(CreditBucket.account_id == account.id).order_by(CreditBucket.created_at, CreditBucket.id)))
        ledger_query = select(CreditLedgerEntry).where(CreditLedgerEntry.account_id == account.id)
        if cursor:
            try:
                decoded = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)).decode()
                timestamp, item_id = decoded.rsplit("|", 1)
                occurred_at = datetime.fromisoformat(timestamp)
            except (ValueError, UnicodeDecodeError) as exc:
                raise AppError(422, "INVALID_CURSOR", "Cursor is invalid") from exc
            ledger_query = ledger_query.where((CreditLedgerEntry.occurred_at < occurred_at) | ((CreditLedgerEntry.occurred_at == occurred_at) & (CreditLedgerEntry.id < item_id)))
        entries = list(self.db.scalars(ledger_query.order_by(CreditLedgerEntry.occurred_at.desc(), CreditLedgerEntry.id.desc()).limit(limit + 1)))
        has_more = len(entries) > limit
        entries = entries[:limit]
        available_by_type = {key: sum(item.available for item in buckets if item.bucket_type == key) for key in ("trial", "subscription", "topup", "adjustment")}
        trial_expiries = [item.expires_at for item in buckets if item.bucket_type == "trial" and item.available > 0 and item.expires_at]
        next_cursor = None
        if has_more and entries:
            next_cursor = base64.urlsafe_b64encode((entries[-1].occurred_at.isoformat() + "|" + entries[-1].id).encode()).decode().rstrip("=")
        return CreditAccountView(
            status=account.status,
            available=sum(item.available for item in buckets),
            reserved=sum(item.reserved for item in buckets),
            trial_available=available_by_type["trial"],
            subscription_available=available_by_type["subscription"],
            topup_available=available_by_type["topup"],
            adjustment_available=available_by_type["adjustment"] - account.debt,
            trial_expires_at=min(trial_expiries) if trial_expiries else None,
            buckets=[CreditBucketView.model_validate({column: getattr(item, column) for column in ("id", "bucket_type", "source_reference", "granted", "available", "reserved", "expires_at", "created_at")}) for item in buckets],
            entries=[CreditLedgerEntryView.model_validate({column: getattr(item, column) for column in ("id", "bucket_id", "amount", "entry_type", "balance_after", "description", "reference_type", "reference_id", "occurred_at")}) for item in entries],
            next_cursor=next_cursor,
        )

    def reserve(
        self,
        current: ProductCurrentUser,
        feature_key: str,
        reference_type: str,
        reference_id: str,
        duration_minutes: int | None = None,
    ) -> CreditReservation | None:
        self.ensure_signup_trial(current)
        catalog = self.active_catalog()
        price = self.db.scalar(select(FeatureCreditPrice).where(FeatureCreditPrice.catalog_version_id == catalog.id, FeatureCreditPrice.feature_key == feature_key))
        if price is None:
            raise AppError(503, "FEATURE_PRICING_UNAVAILABLE", "Feature pricing is unavailable")
        if price.maximum_duration_minutes and duration_minutes and duration_minutes > price.maximum_duration_minutes:
            raise AppError(422, "FEATURE_LIMIT_EXCEEDED", "Requested duration exceeds the feature limit", details={"maximum_duration_minutes": price.maximum_duration_minutes})
        if price.credit_cost == 0:
            return None
        existing = self.db.scalar(select(CreditReservation).where(CreditReservation.reference_type == reference_type, CreditReservation.reference_id == reference_id))
        if existing is not None:
            return existing
        account = self._account(current.id, lock=True)
        if account.status != "active":
            raise AppError(409, "CREDIT_ACCOUNT_RESTRICTED", "Credit account cannot be charged", details={"status": account.status})
        self._expire_buckets(account)
        order = case(
            (CreditBucket.bucket_type == "trial", 1),
            (CreditBucket.bucket_type == "subscription", 2),
            (CreditBucket.bucket_type == "topup", 3),
            else_=4,
        )
        buckets = list(self.db.scalars(select(CreditBucket).where(CreditBucket.account_id == account.id, CreditBucket.available > 0).order_by(order, CreditBucket.expires_at.asc().nullslast(), CreditBucket.created_at).with_for_update()))
        if sum(item.available for item in buckets) < price.credit_cost:
            raise AppError(402, "INSUFFICIENT_CREDITS", "Insufficient credits", details={"required": price.credit_cost, "available": sum(item.available for item in buckets)})
        reservation = CreditReservation(
            account_id=account.id,
            user_id=current.id,
            feature_key=feature_key,
            amount=price.credit_cost,
            catalog_version_id=catalog.id,
            pricing_snapshot={"feature_key": feature_key, "credit_cost": price.credit_cost, "catalog_version": catalog.version_key, "maximum_duration_minutes": price.maximum_duration_minutes},
            reference_type=reference_type,
            reference_id=reference_id,
            expires_at=_utcnow() + timedelta(hours=2),
        )
        self.db.add(reservation)
        self.db.flush()
        remaining = price.credit_cost
        for bucket in buckets:
            amount = min(bucket.available, remaining)
            if not amount:
                continue
            bucket.available -= amount
            bucket.reserved += amount
            self.db.add(CreditReservationAllocation(reservation_id=reservation.id, bucket_id=bucket.id, amount=amount))
            remaining -= amount
            if remaining == 0:
                break
        self.db.flush()
        return reservation

    def capture(self, reservation_id: str | None) -> None:
        if not reservation_id:
            return
        reservation = self.db.scalar(select(CreditReservation).where(CreditReservation.id == reservation_id).with_for_update())
        if reservation is None or reservation.status == "captured":
            return
        if reservation.status != "reserved":
            raise AppError(409, "CREDIT_RESERVATION_NOT_CAPTURABLE", "Credit reservation cannot be captured")
        allocations = list(self.db.scalars(select(CreditReservationAllocation).where(CreditReservationAllocation.reservation_id == reservation.id)))
        for allocation in allocations:
            bucket = self.db.scalar(select(CreditBucket).where(CreditBucket.id == allocation.bucket_id).with_for_update())
            if bucket is None or bucket.reserved < allocation.amount:
                raise AppError(409, "CREDIT_RESERVATION_CORRUPT", "Credit reservation allocation is inconsistent")
            bucket.reserved -= allocation.amount
        reservation.status = "captured"
        reservation.captured_at = _utcnow()
        self.db.flush()
        account = self.db.get(CreditAccount, reservation.account_id)
        self._ledger(
            account,
            -reservation.amount,
            "CHARGE",
            "Credit charge for " + reservation.feature_key,
            reservation.reference_type,
            reservation.reference_id,
            "capture:" + reservation.id,
            metadata={"reservation_id": reservation.id, "pricing": reservation.pricing_snapshot},
        )

    def release(self, reservation_id: str | None, reason: str) -> None:
        if not reservation_id:
            return
        reservation = self.db.scalar(select(CreditReservation).where(CreditReservation.id == reservation_id).with_for_update())
        if reservation is None or reservation.status == "released":
            return
        if reservation.status != "reserved":
            return
        allocations = list(self.db.scalars(select(CreditReservationAllocation).where(CreditReservationAllocation.reservation_id == reservation.id)))
        for allocation in allocations:
            bucket = self.db.scalar(select(CreditBucket).where(CreditBucket.id == allocation.bucket_id).with_for_update())
            if bucket is not None:
                bucket.reserved -= allocation.amount
                bucket.available += allocation.amount
        reservation.status = "released"
        reservation.released_at = _utcnow()
        self.db.flush()

    def refund(self, reservation_id: str, reason: str, actor_user_id: str | None = None) -> CreditLedgerEntry:
        reservation = self.db.scalar(select(CreditReservation).where(CreditReservation.id == reservation_id).with_for_update())
        if reservation is None:
            raise AppError(404, "CREDIT_RESERVATION_NOT_FOUND", "Credit reservation was not found")
        account = self.db.scalar(select(CreditAccount).where(CreditAccount.id == reservation.account_id).with_for_update())
        existing = self.db.scalar(select(CreditLedgerEntry).where(CreditLedgerEntry.account_id == account.id, CreditLedgerEntry.idempotency_key == "refund:" + reservation.id))
        if existing is not None:
            return existing
        if reservation.status != "captured":
            raise AppError(409, "CREDIT_RESERVATION_NOT_REFUNDABLE", "Only a captured credit reservation can be refunded")
        allocations = list(self.db.scalars(select(CreditReservationAllocation).where(CreditReservationAllocation.reservation_id == reservation.id)))
        adjustment_amount = 0
        now = _utcnow()
        for allocation in allocations:
            bucket = self.db.scalar(select(CreditBucket).where(CreditBucket.id == allocation.bucket_id).with_for_update())
            if bucket is not None and (bucket.expires_at is None or bucket.expires_at > now):
                bucket.available += allocation.amount
            else:
                adjustment_amount += allocation.amount
        if adjustment_amount:
            fallback = CreditBucket(account_id=account.id, bucket_type="adjustment", source_reference="feature-refund:" + reservation.id, granted=adjustment_amount, available=adjustment_amount, reserved=0)
            self.db.add(fallback)
        reservation.status = "refunded"
        reservation.refunded_at = now
        self.db.flush()
        return self._ledger(account, reservation.amount, "REFUND", "Feature credit refund", reservation.reference_type, reservation.reference_id, "refund:" + reservation.id, actor_user_id=actor_user_id, reason=reason, metadata={"reservation_id": reservation.id})

    def reconcile_expired_reservations(self, limit: int = 100) -> int:
        reservations = list(self.db.scalars(select(CreditReservation).where(CreditReservation.status == "reserved", CreditReservation.expires_at <= _utcnow()).order_by(CreditReservation.expires_at).limit(limit)))
        for reservation in reservations:
            self.release(reservation.id, "reservation_timeout")
        self.db.commit()
        return len(reservations)

    def create_checkout(self, current: ProductCurrentUser, payload: CreateCheckoutRequest, idempotency_key: str | None) -> RedirectSessionView:
        request_hash = hashlib.sha256(payload.model_dump_json().encode()).hexdigest()
        if idempotency_key:
            existing = self.db.scalar(select(BillingCheckoutSession).where(BillingCheckoutSession.user_id == current.id, BillingCheckoutSession.idempotency_key == idempotency_key))
            if existing is not None:
                if existing.request_hash != request_hash:
                    raise AppError(409, "IDEMPOTENCY_KEY_REUSED", "Idempotency-Key was already used with a different request")
                return RedirectSessionView(id=existing.id, offer_id=existing.offer_id, url=existing.redirect_url, expires_at=existing.expires_at)
        offer = self.db.get(BillingOffer, payload.offer_id)
        catalog = self.active_catalog()
        if offer is None or offer.catalog_version_id != catalog.id or not offer.active:
            raise AppError(404, "BILLING_OFFER_NOT_FOUND", "Billing offer was not found")
        success_url = str(payload.success_url)
        cancel_url = str(payload.cancel_url)
        self._validate_redirect(success_url)
        self._validate_redirect(cancel_url)
        adapter = payment_adapter()
        checkout = BillingCheckoutSession(
            user_id=current.id,
            offer_id=offer.id,
            catalog_version_id=catalog.id,
            provider=adapter.provider,
            offer_snapshot=self.offer_view(offer, catalog).model_dump(mode="json"),
            success_url=success_url,
            cancel_url=cancel_url,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            expires_at=_utcnow() + timedelta(minutes=30),
        )
        self.db.add(checkout)
        self.db.flush()
        redirect = adapter.create_checkout(checkout.id, checkout.offer_snapshot, success_url, cancel_url)
        checkout.provider_session_id = redirect.provider_session_id
        checkout.redirect_url = redirect.url
        checkout.expires_at = redirect.expires_at
        self.db.commit()
        return RedirectSessionView(id=checkout.id, offer_id=offer.id, url=redirect.url, expires_at=redirect.expires_at)

    def create_portal(self, current: ProductCurrentUser, idempotency_key: str) -> RedirectSessionView:
        command, replay = self._command(current.id, "create_portal_session", idempotency_key, {"user_id": current.id})
        if replay:
            return RedirectSessionView.model_validate(command.response_snapshot)
        subscription = self.db.scalar(select(BillingSubscription).where(BillingSubscription.user_id == current.id).order_by(BillingSubscription.created_at.desc()))
        if subscription is None:
            raise AppError(409, "SUBSCRIPTION_NOT_FOUND", "No subscription is available for the billing portal")
        configured_urls = list(get_settings().payment_success_url_allowlist)
        if not configured_urls:
            raise AppError(503, "PAYMENT_REDIRECT_NOT_CONFIGURED", "Payment redirect allowlist is not configured")
        return_url = str(configured_urls[0])
        self._validate_redirect(return_url)
        if not subscription.provider_customer_id:
            raise AppError(409, "PAYMENT_CUSTOMER_NOT_FOUND", "Subscription has no provider customer")
        redirect = payment_adapter(subscription.provider).create_portal(subscription.provider_customer_id, return_url)
        response = RedirectSessionView(id=redirect.provider_session_id, offer_id=subscription.offer_id, url=redirect.url, expires_at=redirect.expires_at)
        self._complete_command(command, "portal_session", None, response.model_dump(mode="json"))
        self.db.commit()
        return response

    def process_webhook(self, provider: str, raw_body: bytes, signature: str | None, payload: dict[str, Any]) -> PaymentEventInbox:
        provider = provider.lower()
        event = payment_adapter(provider).verify_webhook(raw_body, signature, payload)
        body_hash = hashlib.sha256(raw_body).hexdigest()
        existing = self.db.scalar(select(PaymentEventInbox).where(PaymentEventInbox.provider == provider, PaymentEventInbox.provider_event_id == event.event_id))
        if existing is not None:
            if existing.raw_body_hash != body_hash:
                raise AppError(409, "PAYMENT_EVENT_CONFLICT", "Payment event ID was reused with a different payload")
            if existing.status in {"processed", "processing"}:
                return existing
            inbox = existing
            inbox.status = "received"
            inbox.error = None
        else:
            inbox = PaymentEventInbox(
                provider=provider,
                provider_event_id=event.event_id,
                event_type=event.event_type,
                raw_body_hash=body_hash,
                raw_payload=redact_payment_payload(payload),
                normalized_payload=event.payload,
                raw_payload_expires_at=_utcnow() + timedelta(days=90),
            )
            self.db.add(inbox)
        self.db.commit()
        inbox.status = "processing"
        inbox.processing_started_at = _utcnow()
        self.db.commit()
        try:
            self._apply_payment_event(provider, event)
            inbox.status = "processed"
            inbox.processed_at = _utcnow()
            self.db.commit()
        except Exception as exc:
            self.db.rollback()
            inbox = self.db.scalar(select(PaymentEventInbox).where(PaymentEventInbox.provider == provider, PaymentEventInbox.provider_event_id == event.event_id))
            if inbox is not None:
                inbox.status = "failed"
                inbox.error = {"code": "PAYMENT_EVENT_FAILED", "message": str(exc)[:1000]}
                self.db.commit()
            raise
        return inbox

    def _apply_payment_event(self, provider: str, event: NormalizedPaymentEvent) -> None:
        if event.event_type in {"checkout.completed", "subscription.renewed"}:
            self._payment_succeeded(provider, event.payload, event.event_id, event.event_type)
        elif event.event_type in {"payment.refunded", "payment.chargeback"}:
            self._payment_reversed(provider, event.payload, event.event_id, event.event_type)
        elif event.event_type == "subscription.cancelled":
            subscription = self.db.scalar(
                select(BillingSubscription).where(
                    BillingSubscription.provider == provider,
                    BillingSubscription.provider_subscription_id == str(event.payload.get("subscription_id")),
                )
            )
            if subscription:
                subscription.cancel_at_period_end = False
                subscription.status = "cancelled"

    def _process_reconciled_event(self, provider: str, event: NormalizedPaymentEvent) -> bool:
        existing = self.db.scalar(
            select(PaymentEventInbox).where(
                PaymentEventInbox.provider == provider,
                PaymentEventInbox.provider_event_id == event.event_id,
            )
        )
        if existing is not None and existing.status == "processed":
            return False
        now = _utcnow()
        inbox = existing or PaymentEventInbox(
            provider=provider,
            provider_event_id=event.event_id,
            event_type=event.event_type,
            raw_body_hash=hashlib.sha256(event.event_id.encode()).hexdigest(),
            raw_payload={},
            normalized_payload=event.payload,
            raw_payload_expires_at=now,
            raw_payload_purged_at=now,
        )
        if existing is None:
            self.db.add(inbox)
        inbox.status = "processing"
        inbox.processing_started_at = now
        inbox.error = None
        self.db.commit()
        try:
            self._apply_payment_event(provider, event)
            inbox.status = "processed"
            inbox.processed_at = _utcnow()
            self.db.commit()
        except Exception as exc:
            self.db.rollback()
            inbox = self.db.scalar(
                select(PaymentEventInbox).where(
                    PaymentEventInbox.provider == provider,
                    PaymentEventInbox.provider_event_id == event.event_id,
                )
            )
            if inbox is not None:
                inbox.status = "failed"
                inbox.error = {"code": "PAYMENT_RECONCILIATION_FAILED", "message": str(exc)[:1000]}
                self.db.commit()
            raise
        return True

    def reconcile_payment_provider(self, limit: int = 100) -> dict[str, int]:
        stats = {"events_processed": 0, "events_failed": 0, "checkouts_checked": 0, "subscriptions_checked": 0}
        stale_processing_before = _utcnow() - timedelta(minutes=5)
        retry_ids = list(
            self.db.scalars(
                select(PaymentEventInbox.id)
                .where(
                    (PaymentEventInbox.status == "failed")
                    | (
                        (PaymentEventInbox.status == "processing")
                        & (PaymentEventInbox.processing_started_at < stale_processing_before)
                    )
                )
                .order_by(PaymentEventInbox.received_at)
                .limit(limit)
            )
        )
        for inbox_id in retry_ids:
            inbox = self.db.get(PaymentEventInbox, inbox_id)
            if inbox is None:
                continue
            event = NormalizedPaymentEvent(inbox.provider_event_id, inbox.event_type, inbox.normalized_payload)
            try:
                if self._process_reconciled_event(inbox.provider, event):
                    stats["events_processed"] += 1
            except Exception:
                stats["events_failed"] += 1

        remaining = max(0, limit - stats["events_processed"])
        checkout_ids = list(
            self.db.scalars(
                select(BillingCheckoutSession.id)
                .where(
                    BillingCheckoutSession.status == "pending",
                    BillingCheckoutSession.provider_session_id.is_not(None),
                )
                .order_by(BillingCheckoutSession.created_at)
                .limit(remaining)
            )
        )
        for checkout_id in checkout_ids:
            checkout = self.db.get(BillingCheckoutSession, checkout_id)
            if checkout is None or not checkout.provider_session_id:
                continue
            stats["checkouts_checked"] += 1
            try:
                events = payment_adapter(checkout.provider).reconcile_checkout(checkout.provider_session_id)
                for event in events:
                    if self._process_reconciled_event(checkout.provider, event):
                        stats["events_processed"] += 1
            except Exception:
                stats["events_failed"] += 1

        subscription_ids = list(
            self.db.scalars(
                select(BillingSubscription.id)
                .where(
                    BillingSubscription.status.in_({"active", "past_due"}),
                    BillingSubscription.provider_subscription_id.is_not(None),
                )
                .order_by(BillingSubscription.created_at)
                .limit(max(0, limit - stats["events_processed"]))
            )
        )
        for subscription_id in subscription_ids:
            subscription = self.db.get(BillingSubscription, subscription_id)
            if subscription is None or not subscription.provider_subscription_id:
                continue
            stats["subscriptions_checked"] += 1
            try:
                events = payment_adapter(subscription.provider).reconcile_subscription(
                    subscription.provider_subscription_id
                )
                for event in events:
                    if self._process_reconciled_event(subscription.provider, event):
                        stats["events_processed"] += 1
            except Exception:
                stats["events_failed"] += 1
        return stats

    def cleanup_expired_payment_payloads(self, limit: int = 500) -> int:
        now = _utcnow()
        records = list(
            self.db.scalars(
                select(PaymentEventInbox)
                .where(
                    PaymentEventInbox.raw_payload_purged_at.is_(None),
                    PaymentEventInbox.raw_payload_expires_at <= now,
                )
                .order_by(PaymentEventInbox.raw_payload_expires_at)
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
        )
        for record in records:
            record.raw_payload = {}
            record.raw_payload_purged_at = now
        self.db.commit()
        return len(records)

    def _payment_succeeded(self, provider: str, payload: dict[str, Any], event_id: str, event_type: str) -> None:
        checkout = None
        subscription = None
        if event_type == "checkout.completed":
            checkout = self.db.scalar(select(BillingCheckoutSession).where(BillingCheckoutSession.provider == provider, BillingCheckoutSession.provider_session_id == str(payload.get("checkout_session_id"))))
            if checkout is None:
                raise AppError(422, "CHECKOUT_SESSION_NOT_FOUND", "Payment event references an unknown checkout session")
            offer = self.db.get(BillingOffer, checkout.offer_id)
            user_id = checkout.user_id
        else:
            provider_subscription_id = str(payload.get("subscription_id") or "")
            if not provider_subscription_id:
                raise AppError(422, "SUBSCRIPTION_ID_REQUIRED", "Subscription renewal requires a subscription ID")
            subscription = self.db.scalar(select(BillingSubscription).where(BillingSubscription.provider == provider, BillingSubscription.provider_subscription_id == provider_subscription_id).with_for_update())
            if subscription is None:
                raise AppError(422, "SUBSCRIPTION_NOT_FOUND", "Payment event references an unknown subscription")
            offer = self.db.get(BillingOffer, subscription.offer_id)
            user_id = subscription.user_id
        if offer is None:
            raise AppError(422, "BILLING_OFFER_NOT_FOUND", "Payment event references an unknown offer")
        try:
            amount_minor = int(payload.get("amount_minor"))
        except (TypeError, ValueError) as exc:
            raise AppError(422, "PAYMENT_AMOUNT_REQUIRED", "Payment event requires a valid amount") from exc
        currency = str(payload.get("currency") or "").upper()
        if amount_minor != offer.amount_minor or currency != offer.currency:
            raise AppError(409, "PAYMENT_AMOUNT_MISMATCH", "Payment amount or currency does not match the checkout offer")
        if payload.get("offer_id") and str(payload["offer_id"]) != offer.id:
            raise AppError(409, "PAYMENT_OFFER_MISMATCH", "Payment offer does not match the checkout offer")
        account = self._account(user_id, lock=True)
        period_reference = str(payload.get("period_reference") or event_id)
        if offer.offer_type == "subscription" and event_type == "subscription.renewed" and not payload.get("period_reference"):
            raise AppError(422, "BILLING_PERIOD_REQUIRED", "Subscription renewal requires a stable billing period reference")
        expires_at = None
        bucket_type = "topup"
        if offer.offer_type == "subscription":
            bucket_type = "subscription"
            period_start = self._parse_time(payload.get("period_start")) or _utcnow()
            period_end = self._parse_time(payload.get("period_end")) or period_start + timedelta(days=30)
            expires_at = period_end
            subscription_id = str(payload.get("subscription_id") or checkout.id)
            if subscription is None:
                subscription = self.db.scalar(select(BillingSubscription).where(BillingSubscription.provider == provider, BillingSubscription.provider_subscription_id == subscription_id))
            if subscription is None:
                subscription = BillingSubscription(user_id=user_id, offer_id=offer.id, provider=provider, provider_subscription_id=subscription_id, status="active")
                self.db.add(subscription)
            subscription.status = "active"
            if payload.get("provider_customer_id"):
                subscription.provider_customer_id = str(payload["provider_customer_id"])
            subscription.current_period_reference = period_reference
            subscription.current_period_start = period_start
            subscription.current_period_end = period_end
        self._grant_bucket(account, bucket_type, "payment:" + period_reference, offer.credit_grant, expires_at, offer.display_name + " credits", "payment", event_id, "payment:" + event_id)
        if checkout is not None:
            checkout.status = "completed"
            checkout.completed_at = _utcnow()

    def _payment_reversed(self, provider: str, payload: dict[str, Any], event_id: str, event_type: str) -> None:
        source_reference = "payment:" + str(payload.get("period_reference") or payload.get("original_event_id") or "")
        bucket = self.db.scalar(select(CreditBucket).where(CreditBucket.source_reference == source_reference).with_for_update())
        if bucket is None:
            raise AppError(422, "PAYMENT_GRANT_NOT_FOUND", "Reversed payment grant was not found")
        original_event = self.db.scalar(
            select(PaymentEventInbox).where(
                PaymentEventInbox.provider == provider,
                PaymentEventInbox.event_type.in_({"checkout.completed", "subscription.renewed"}),
                PaymentEventInbox.normalized_payload["period_reference"].as_string()
                == str(payload.get("period_reference") or ""),
            )
        )
        original_amount = int((original_event.normalized_payload if original_event else {}).get("amount_minor") or 0)
        reversed_amount = int(payload.get("amount_minor") or original_amount)
        if original_amount <= 0 or reversed_amount <= 0 or reversed_amount > original_amount:
            raise AppError(422, "PAYMENT_REVERSAL_AMOUNT_INVALID", "Payment reversal amount is invalid")
        credits_to_reverse = min(bucket.granted, (bucket.granted * reversed_amount + original_amount - 1) // original_amount)
        account = self.db.scalar(select(CreditAccount).where(CreditAccount.id == bucket.account_id).with_for_update())
        reservation_ids = set(self.db.scalars(select(CreditReservation.id).join(CreditReservationAllocation, CreditReservationAllocation.reservation_id == CreditReservation.id).where(CreditReservationAllocation.bucket_id == bucket.id, CreditReservation.status == "reserved")))
        for reservation_id in reservation_ids:
            self.release(reservation_id, "payment_reversed")
        self.db.flush()
        unspent = min(bucket.available, credits_to_reverse)
        bucket.available -= unspent
        amount_due = max(0, credits_to_reverse - unspent)
        if amount_due:
            account.status = "review"
            account.debt += amount_due
        self.db.flush()
        if unspent:
            self._ledger(account, -unspent, "REVERSAL", "Payment " + event_type, "payment_event", event_id, "reversal:" + event_id, bucket_id=bucket.id, metadata={"debt_created": amount_due})

    def list_catalog_versions(self) -> list[BillingCatalogVersionView]:
        return [self.catalog_version_view(item) for item in self.db.scalars(select(BillingCatalogVersion).order_by(BillingCatalogVersion.created_at.desc()))]

    def create_catalog_version(self, current: ProductCurrentUser, payload: CreateBillingCatalogVersionRequest, idempotency_key: str) -> BillingCatalogVersion:
        command, replay = self._command(current.id, "create_billing_catalog", idempotency_key, payload.model_dump(mode="json"))
        if replay:
            return self.db.get(BillingCatalogVersion, command.resource_id)
        if len({item.code for item in payload.offers}) != len(payload.offers) or len({item.feature_key for item in payload.feature_prices}) != len(payload.feature_prices):
            raise AppError(422, "DUPLICATE_CATALOG_ITEM", "Catalog offer codes and feature keys must be unique")
        catalog = BillingCatalogVersion(version_key=payload.version_key, market=payload.market, currency=payload.currency, created_by_user_id=current.id)
        self.db.add(catalog)
        self.db.flush()
        for item in payload.offers:
            if item.offer_type == "subscription" and item.billing_interval != "month":
                raise AppError(422, "INVALID_BILLING_INTERVAL", "Subscription offers require a monthly interval")
            self.db.add(BillingOffer(catalog_version_id=catalog.id, **item.model_dump()))
        for item in payload.feature_prices:
            self.db.add(FeatureCreditPrice(catalog_version_id=catalog.id, **item.model_dump()))
        self._complete_command(command, "billing_catalog", catalog.id, {"id": catalog.id})
        self.db.commit()
        self.db.refresh(catalog)
        return catalog

    def activate_catalog(self, current: ProductCurrentUser, catalog_id: str, payload: ActivateBillingCatalogRequest, idempotency_key: str) -> BillingCatalogVersion:
        command, replay = self._command(current.id, "activate_billing_catalog:" + catalog_id, idempotency_key, payload.model_dump(mode="json"))
        if replay:
            return self.db.get(BillingCatalogVersion, command.resource_id)
        catalog = self.db.scalar(select(BillingCatalogVersion).where(BillingCatalogVersion.id == catalog_id).with_for_update())
        if catalog is None:
            raise AppError(404, "BILLING_CATALOG_NOT_FOUND", "Billing catalog was not found")
        if catalog.status != "draft":
            raise AppError(409, "BILLING_CATALOG_IMMUTABLE", "Only a draft catalog can be activated")
        active = list(self.db.scalars(select(BillingCatalogVersion).where(BillingCatalogVersion.market == catalog.market, BillingCatalogVersion.currency == catalog.currency, BillingCatalogVersion.status == "active").with_for_update()))
        for item in active:
            item.effective_to = payload.effective_from
            if payload.effective_from <= _utcnow():
                item.status = "retired"
        catalog.status = "active"
        catalog.effective_from = payload.effective_from
        catalog.published_at = _utcnow()
        catalog.activation_reason = payload.reason
        catalog.created_by_user_id = catalog.created_by_user_id or current.id
        self._complete_command(command, "billing_catalog", catalog.id, {"id": catalog.id})
        self.db.commit()
        self.db.refresh(catalog)
        return catalog

    def update_feature_price(self, current: ProductCurrentUser, catalog_id: str, feature_key: str, payload: UpdateFeatureCreditPriceRequest, idempotency_key: str) -> FeatureCreditPrice:
        command, replay = self._command(current.id, "set_feature_price:" + catalog_id + ":" + feature_key, idempotency_key, payload.model_dump(mode="json"))
        if replay:
            return self.db.get(FeatureCreditPrice, command.resource_id)
        if payload.catalog_version_id != catalog_id:
            raise AppError(422, "CATALOG_VERSION_MISMATCH", "Catalog version does not match the route")
        catalog = self.db.get(BillingCatalogVersion, catalog_id)
        if catalog is None:
            raise AppError(404, "BILLING_CATALOG_NOT_FOUND", "Billing catalog was not found")
        if catalog.status != "draft":
            raise AppError(409, "BILLING_CATALOG_IMMUTABLE", "Published catalog pricing cannot be changed")
        price = self.db.scalar(select(FeatureCreditPrice).where(FeatureCreditPrice.catalog_version_id == catalog.id, FeatureCreditPrice.feature_key == feature_key))
        if price is None:
            price = FeatureCreditPrice(catalog_version_id=catalog.id, feature_key=feature_key)
            self.db.add(price)
        price.credit_cost = payload.credit_cost
        price.maximum_duration_minutes = payload.maximum_duration_minutes
        price.change_reason = payload.reason
        self.db.flush()
        self._complete_command(command, "feature_credit_price", price.id, {"id": price.id})
        self.db.commit()
        self.db.refresh(price)
        return price

    def publish_trial_policy(self, current: ProductCurrentUser, payload: UpdateSignupTrialPolicyRequest, idempotency_key: str) -> SignupTrialPolicy:
        command, replay = self._command(current.id, "publish_signup_trial_policy", idempotency_key, payload.model_dump(mode="json"))
        if replay:
            return self.db.get(SignupTrialPolicy, command.resource_id)
        effective = payload.effective_from or _utcnow()
        version = "trial-" + effective.strftime("%Y%m%d%H%M%S%f")
        policy = SignupTrialPolicy(enabled=payload.enabled, credit_grant=payload.credit_grant, valid_days=payload.valid_days, policy_version=version, effective_from=effective, reason=payload.reason, created_by_user_id=current.id)
        self.db.add(policy)
        self.db.flush()
        self._complete_command(command, "signup_trial_policy", policy.id, {"id": policy.id})
        self.db.commit()
        self.db.refresh(policy)
        return policy

    def request_credit_adjustment(
        self,
        current: ProductCurrentUser,
        payload: CreditAdjustmentRequest,
        idempotency_key: str,
    ) -> CreditAdjustmentView:
        if payload.amount == 0:
            raise AppError(422, "ZERO_CREDIT_ADJUSTMENT", "Credit adjustment cannot be zero")
        user = self.db.get(User, payload.user_id)
        if user is None:
            raise AppError(404, "USER_NOT_FOUND", "User was not found")
        command, replay = self._command(
            current.id,
            "request_credit_adjustment",
            idempotency_key,
            payload.model_dump(mode="json"),
        )
        if replay:
            return self.adjustment_view(self.db.get(CreditAdjustmentApproval, command.resource_id))
        settings = get_settings()
        threshold = settings.credit_adjustment_dual_control_threshold
        requires_approval = settings.credit_adjustment_dual_control_enabled and abs(payload.amount) >= threshold
        request_hash = hashlib.sha256(payload.model_dump_json().encode("utf-8")).hexdigest()
        adjustment = CreditAdjustmentApproval(
            requested_by_user_id=current.id,
            target_user_id=user.id,
            amount=payload.amount,
            reason=payload.reason,
            reference=payload.reference,
            status="pending" if requires_approval else "executed",
            dual_control_required=requires_approval,
            policy_threshold=threshold,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
        )
        self.db.add(adjustment)
        self.db.flush()
        if not requires_approval:
            entry = self._apply_credit_adjustment(current.id, payload, "adjustment:" + adjustment.id)
            adjustment.ledger_entry_id = entry.id
            adjustment.executed_at = _utcnow()
        self._complete_command(command, "credit_adjustment", adjustment.id, {"id": adjustment.id})
        self.db.commit()
        self.db.refresh(adjustment)
        return self.adjustment_view(adjustment)

    def get_credit_adjustment(self, adjustment_id: str) -> CreditAdjustmentView:
        adjustment = self.db.get(CreditAdjustmentApproval, adjustment_id)
        if adjustment is None:
            raise AppError(404, "CREDIT_ADJUSTMENT_NOT_FOUND", "Credit adjustment was not found")
        return self.adjustment_view(adjustment)

    def approve_credit_adjustment(
        self,
        current: ProductCurrentUser,
        adjustment_id: str,
        payload: CreditAdjustmentDecisionRequest,
        idempotency_key: str,
    ) -> CreditAdjustmentView:
        command, replay = self._command(
            current.id,
            "approve_credit_adjustment:" + adjustment_id,
            idempotency_key,
            payload.model_dump(mode="json"),
        )
        if replay:
            return self.adjustment_view(self.db.get(CreditAdjustmentApproval, command.resource_id))
        adjustment = self.db.scalar(
            select(CreditAdjustmentApproval)
            .where(CreditAdjustmentApproval.id == adjustment_id)
            .with_for_update()
        )
        if adjustment is None:
            raise AppError(404, "CREDIT_ADJUSTMENT_NOT_FOUND", "Credit adjustment was not found")
        if adjustment.status != "pending":
            raise AppError(409, "CREDIT_ADJUSTMENT_ALREADY_DECIDED", "Credit adjustment is no longer pending")
        if adjustment.requested_by_user_id == current.id:
            raise AppError(409, "DUAL_CONTROL_SELF_APPROVAL_FORBIDDEN", "Requester cannot approve their own adjustment")
        decision_time = _utcnow()
        request_payload = CreditAdjustmentRequest(
            user_id=adjustment.target_user_id,
            amount=adjustment.amount,
            reason=adjustment.reason,
            reference=adjustment.reference,
        )
        entry = self._apply_credit_adjustment(current.id, request_payload, "adjustment:" + adjustment.id)
        adjustment.approved_by_user_id = current.id
        adjustment.decision_reason = payload.reason
        adjustment.status = "executed"
        adjustment.ledger_entry_id = entry.id
        adjustment.decided_at = decision_time
        adjustment.executed_at = decision_time
        self._complete_command(command, "credit_adjustment", adjustment.id, {"id": adjustment.id})
        self.db.commit()
        self.db.refresh(adjustment)
        return self.adjustment_view(adjustment)

    def reject_credit_adjustment(
        self,
        current: ProductCurrentUser,
        adjustment_id: str,
        payload: CreditAdjustmentDecisionRequest,
        idempotency_key: str,
    ) -> CreditAdjustmentView:
        command, replay = self._command(
            current.id,
            "reject_credit_adjustment:" + adjustment_id,
            idempotency_key,
            payload.model_dump(mode="json"),
        )
        if replay:
            return self.adjustment_view(self.db.get(CreditAdjustmentApproval, command.resource_id))
        adjustment = self.db.scalar(
            select(CreditAdjustmentApproval)
            .where(CreditAdjustmentApproval.id == adjustment_id)
            .with_for_update()
        )
        if adjustment is None:
            raise AppError(404, "CREDIT_ADJUSTMENT_NOT_FOUND", "Credit adjustment was not found")
        if adjustment.status != "pending":
            raise AppError(409, "CREDIT_ADJUSTMENT_ALREADY_DECIDED", "Credit adjustment is no longer pending")
        if adjustment.requested_by_user_id == current.id:
            raise AppError(409, "DUAL_CONTROL_SELF_DECISION_FORBIDDEN", "Requester cannot decide their own adjustment")
        adjustment.approved_by_user_id = current.id
        adjustment.decision_reason = payload.reason
        adjustment.status = "rejected"
        adjustment.decided_at = _utcnow()
        self._complete_command(command, "credit_adjustment", adjustment.id, {"id": adjustment.id})
        self.db.commit()
        self.db.refresh(adjustment)
        return self.adjustment_view(adjustment)

    def _apply_credit_adjustment(
        self,
        actor_user_id: str,
        payload: CreditAdjustmentRequest,
        ledger_idempotency_key: str,
    ) -> CreditLedgerEntry:
        account = self._account(payload.user_id, lock=True)
        existing = self.db.scalar(
            select(CreditLedgerEntry).where(
                CreditLedgerEntry.account_id == account.id,
                CreditLedgerEntry.idempotency_key == ledger_idempotency_key,
            )
        )
        if existing is not None:
            return existing
        bucket = None
        if payload.amount > 0:
            bucket = CreditBucket(account_id=account.id, bucket_type="adjustment", source_reference=ledger_idempotency_key, granted=payload.amount, available=payload.amount, reserved=0)
            self.db.add(bucket)
            self.db.flush()
        else:
            needed = -payload.amount
            buckets = list(self.db.scalars(select(CreditBucket).where(CreditBucket.account_id == account.id, CreditBucket.available > 0).order_by(CreditBucket.created_at).with_for_update()))
            if sum(item.available for item in buckets) < needed:
                raise AppError(409, "ADJUSTMENT_EXCEEDS_BALANCE", "Negative adjustment exceeds available credits")
            for item in buckets:
                amount = min(item.available, needed)
                item.available -= amount
                needed -= amount
                if needed == 0:
                    break
            self.db.flush()
        return self._ledger(account, payload.amount, "ADJUSTMENT", "Administrative credit adjustment", "admin_adjustment", payload.reference, ledger_idempotency_key, bucket_id=bucket.id if bucket else None, actor_user_id=actor_user_id, reason=payload.reason)

    def adjustment_view(self, adjustment: CreditAdjustmentApproval | None) -> CreditAdjustmentView:
        if adjustment is None:
            raise AppError(404, "CREDIT_ADJUSTMENT_NOT_FOUND", "Credit adjustment was not found")
        entry = self.db.get(CreditLedgerEntry, adjustment.ledger_entry_id) if adjustment.ledger_entry_id else None
        ledger_view = None
        if entry is not None:
            ledger_view = CreditLedgerEntryView.model_validate({column: getattr(entry, column) for column in ("id", "bucket_id", "amount", "entry_type", "balance_after", "description", "reference_type", "reference_id", "occurred_at")})
        return CreditAdjustmentView(
            id=adjustment.id,
            target_user_id=adjustment.target_user_id,
            amount=adjustment.amount,
            reason=adjustment.reason,
            reference=adjustment.reference,
            status=adjustment.status,
            dual_control_required=adjustment.dual_control_required,
            policy_threshold=adjustment.policy_threshold,
            requested_by_user_id=adjustment.requested_by_user_id,
            approved_by_user_id=adjustment.approved_by_user_id,
            decision_reason=adjustment.decision_reason,
            ledger_entry=ledger_view,
            created_at=adjustment.created_at,
            decided_at=adjustment.decided_at,
            executed_at=adjustment.executed_at,
        )

    @staticmethod
    def catalog_version_view(catalog: BillingCatalogVersion) -> BillingCatalogVersionView:
        return BillingCatalogVersionView(id=catalog.id, version_key=catalog.version_key, market=catalog.market, currency=catalog.currency, status=catalog.status, effective_from=catalog.effective_from, effective_to=catalog.effective_to, created_at=catalog.created_at, published_at=catalog.published_at)

    def _command(self, actor_user_id: str, command_type: str, idempotency_key: str, payload: dict[str, Any]) -> tuple[BillingCommand, bool]:
        request_hash = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()
        self.db.scalar(select(User.id).where(User.id == actor_user_id).with_for_update())
        existing = self.db.scalar(select(BillingCommand).where(BillingCommand.actor_user_id == actor_user_id, BillingCommand.command_type == command_type, BillingCommand.idempotency_key == idempotency_key))
        if existing is not None:
            if existing.request_hash != request_hash:
                raise AppError(409, "IDEMPOTENCY_KEY_REUSED", "Idempotency-Key was already used with a different request")
            if existing.status != "completed":
                raise AppError(409, "IDEMPOTENT_COMMAND_IN_PROGRESS", "The idempotent command is still processing", retryable=True)
            return existing, True
        command = BillingCommand(actor_user_id=actor_user_id, command_type=command_type, idempotency_key=idempotency_key, request_hash=request_hash)
        self.db.add(command)
        self.db.flush()
        return command, False

    @staticmethod
    def _complete_command(command: BillingCommand, resource_type: str, resource_id: str | None, response_snapshot: dict[str, Any]) -> None:
        command.status = "completed"
        command.resource_type = resource_type
        command.resource_id = resource_id
        command.response_snapshot = response_snapshot
        command.completed_at = _utcnow()

    def _account(self, user_id: str, lock: bool = False) -> CreditAccount:
        query = select(CreditAccount).where(CreditAccount.user_id == user_id)
        if lock:
            query = query.with_for_update()
        account = self.db.scalar(query)
        if account is None and lock:
            user_exists = self.db.scalar(select(User.id).where(User.id == user_id).with_for_update())
            if user_exists is None:
                raise AppError(404, "USER_NOT_FOUND", "User was not found")
            account = self.db.scalar(select(CreditAccount).where(CreditAccount.user_id == user_id).with_for_update())
        if account is None:
            account = CreditAccount(user_id=user_id)
            self.db.add(account)
            self.db.flush()
        return account

    def _grant_bucket(self, account: CreditAccount, bucket_type: str, source_reference: str, amount: int, expires_at: datetime | None, description: str, reference_type: str, reference_id: str, idempotency_key: str) -> CreditBucket:
        existing = self.db.scalar(select(CreditBucket).where(CreditBucket.account_id == account.id, CreditBucket.bucket_type == bucket_type, CreditBucket.source_reference == source_reference))
        if existing is not None:
            return existing
        bucket = CreditBucket(account_id=account.id, bucket_type=bucket_type, source_reference=source_reference, granted=amount, available=amount, reserved=0, expires_at=expires_at)
        self.db.add(bucket)
        self.db.flush()
        self._ledger(account, amount, "GRANT", description, reference_type, reference_id, idempotency_key, bucket_id=bucket.id)
        return bucket

    def _ledger(self, account: CreditAccount, amount: int, entry_type: str, description: str, reference_type: str | None, reference_id: str | None, idempotency_key: str | None, bucket_id: str | None = None, actor_user_id: str | None = None, reason: str | None = None, metadata: dict[str, Any] | None = None) -> CreditLedgerEntry:
        if amount == 0:
            raise AppError(409, "ZERO_LEDGER_ENTRY", "Credit ledger entries cannot be zero")
        if idempotency_key:
            existing = self.db.scalar(select(CreditLedgerEntry).where(CreditLedgerEntry.account_id == account.id, CreditLedgerEntry.idempotency_key == idempotency_key))
            if existing is not None:
                return existing
        self.db.flush()
        balance = self.db.scalar(select(func.coalesce(func.sum(CreditBucket.available + CreditBucket.reserved), 0)).where(CreditBucket.account_id == account.id)) or 0
        entry = CreditLedgerEntry(account_id=account.id, bucket_id=bucket_id, amount=amount, entry_type=entry_type, balance_after=int(balance), description=description, reference_type=reference_type, reference_id=reference_id, idempotency_key=idempotency_key, actor_user_id=actor_user_id, reason=reason, metadata_json=metadata or {})
        self.db.add(entry)
        self.db.flush()
        return entry

    def _expire_buckets(self, account: CreditAccount) -> None:
        expired = list(self.db.scalars(select(CreditBucket).where(CreditBucket.account_id == account.id, CreditBucket.expires_at <= _utcnow(), CreditBucket.available > 0).with_for_update()))
        for bucket in expired:
            amount = bucket.available
            bucket.available = 0
            self.db.flush()
            self._ledger(account, -amount, "EXPIRE", "Credit bucket expired", "credit_bucket", bucket.id, "expire:" + bucket.id, bucket_id=bucket.id)

    def _validate_redirect(self, value: str) -> None:
        parsed = urlsplit(value)
        origin = parsed.scheme + "://" + parsed.netloc
        settings = get_settings()
        allowed = set()
        for item in settings.payment_success_url_allowlist:
            allowed_parts = urlsplit(str(item))
            if allowed_parts.scheme and allowed_parts.netloc:
                allowed.add((allowed_parts.scheme + "://" + allowed_parts.netloc).rstrip("/"))
        local_http = str(settings.app_env).lower() in {"local", "development", "test"} and parsed.scheme == "http"
        if (parsed.scheme != "https" and not local_http) or not parsed.netloc or origin.rstrip("/") not in allowed:
            raise AppError(422, "PAYMENT_REDIRECT_NOT_ALLOWED", "Payment redirect origin is not allowed")

    @staticmethod
    def _parse_time(value: Any) -> datetime | None:
        if not value:
            return None
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError as exc:
            raise AppError(422, "INVALID_PAYMENT_TIMESTAMP", "Payment event contains an invalid timestamp") from exc
