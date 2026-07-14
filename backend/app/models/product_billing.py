from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint

from backend.app.models.db import Base


def _uuid() -> str:
    return str(uuid4())


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class BillingCatalogVersion(Base):
    __tablename__ = "product_billing_catalog_versions"
    __table_args__ = (
        UniqueConstraint("version_key", name="uq_product_billing_catalog_version_key"),
        Index("ix_product_billing_catalog_active", "market", "currency", "status", "effective_from"),
    )

    id = Column(String(36), primary_key=True, default=_uuid)
    version_key = Column(String(100), nullable=False)
    market = Column(String(8), nullable=False, default="VN")
    currency = Column(String(3), nullable=False, default="VND")
    status = Column(String(24), nullable=False, default="draft")
    effective_from = Column(DateTime(timezone=True), nullable=True)
    effective_to = Column(DateTime(timezone=True), nullable=True)
    created_by_user_id = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    activation_reason = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
    published_at = Column(DateTime(timezone=True), nullable=True)


class BillingOffer(Base):
    __tablename__ = "product_billing_offers"
    __table_args__ = (
        UniqueConstraint("catalog_version_id", "code", name="uq_product_billing_offer_code"),
        Index("ix_product_billing_offers_catalog_type", "catalog_version_id", "offer_type"),
    )

    id = Column(String(36), primary_key=True, default=_uuid)
    catalog_version_id = Column(String(36), ForeignKey("product_billing_catalog_versions.id", ondelete="CASCADE"), nullable=False)
    code = Column(String(64), nullable=False)
    display_name = Column(String(200), nullable=False)
    offer_type = Column(String(24), nullable=False)
    amount_minor = Column(Integer, nullable=False)
    currency = Column(String(3), nullable=False, default="VND")
    billing_interval = Column(String(24), nullable=True)
    credit_grant = Column(Integer, nullable=False)
    active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)


class FeatureCreditPrice(Base):
    __tablename__ = "product_feature_credit_prices"
    __table_args__ = (UniqueConstraint("catalog_version_id", "feature_key", name="uq_product_feature_credit_price"),)

    id = Column(String(36), primary_key=True, default=_uuid)
    catalog_version_id = Column(String(36), ForeignKey("product_billing_catalog_versions.id", ondelete="CASCADE"), nullable=False)
    feature_key = Column(String(64), nullable=False)
    credit_cost = Column(Integer, nullable=False)
    maximum_duration_minutes = Column(Integer, nullable=True)
    change_reason = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)


class SignupTrialPolicy(Base):
    __tablename__ = "product_signup_trial_policies"
    __table_args__ = (UniqueConstraint("policy_version", name="uq_product_signup_trial_policy_version"),)

    id = Column(String(36), primary_key=True, default=_uuid)
    policy_key = Column(String(80), nullable=False, default="SIGNUP_VERIFIED_EMAIL")
    enabled = Column(Boolean, nullable=False, default=True)
    trigger = Column(String(40), nullable=False, default="verified_email")
    credit_grant = Column(Integer, nullable=False)
    valid_days = Column(Integer, nullable=False)
    grants_per_user = Column(Integer, nullable=False, default=1)
    policy_version = Column(String(80), nullable=False)
    effective_from = Column(DateTime(timezone=True), nullable=False)
    reason = Column(Text, nullable=True)
    created_by_user_id = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)


class BillingSubscription(Base):
    __tablename__ = "product_billing_subscriptions"
    __table_args__ = (
        UniqueConstraint("provider", "provider_subscription_id", name="uq_product_billing_provider_subscription"),
        Index("ix_product_billing_subscriptions_user_status", "user_id", "status"),
    )

    id = Column(String(36), primary_key=True, default=_uuid)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    offer_id = Column(String(36), ForeignKey("product_billing_offers.id", ondelete="RESTRICT"), nullable=False)
    provider = Column(String(40), nullable=False)
    provider_customer_id = Column(String(255), nullable=True)
    provider_subscription_id = Column(String(255), nullable=True)
    status = Column(String(24), nullable=False)
    current_period_reference = Column(String(255), nullable=True)
    current_period_start = Column(DateTime(timezone=True), nullable=True)
    current_period_end = Column(DateTime(timezone=True), nullable=True)
    cancel_at_period_end = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow)


class CreditAccount(Base):
    __tablename__ = "product_credit_accounts"

    id = Column(String(36), primary_key=True, default=_uuid)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True)
    status = Column(String(24), nullable=False, default="active")
    debt = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow)


class CreditBucket(Base):
    __tablename__ = "product_credit_buckets"
    __table_args__ = (
        UniqueConstraint("account_id", "bucket_type", "source_reference", name="uq_product_credit_bucket_source"),
        Index("ix_product_credit_buckets_account_expiry", "account_id", "expires_at"),
    )

    id = Column(String(36), primary_key=True, default=_uuid)
    account_id = Column(String(36), ForeignKey("product_credit_accounts.id", ondelete="CASCADE"), nullable=False)
    bucket_type = Column(String(24), nullable=False)
    source_reference = Column(String(255), nullable=True)
    granted = Column(Integer, nullable=False)
    available = Column(Integer, nullable=False)
    reserved = Column(Integer, nullable=False, default=0)
    expires_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)


class CreditLedgerEntry(Base):
    __tablename__ = "product_credit_ledger_entries"
    __table_args__ = (
        UniqueConstraint("account_id", "idempotency_key", name="uq_product_credit_ledger_idempotency"),
        Index("ix_product_credit_ledger_account_occurred", "account_id", "occurred_at"),
        Index("ix_product_credit_ledger_reference", "reference_type", "reference_id"),
    )

    id = Column(String(36), primary_key=True, default=_uuid)
    account_id = Column(String(36), ForeignKey("product_credit_accounts.id", ondelete="RESTRICT"), nullable=False)
    bucket_id = Column(String(36), ForeignKey("product_credit_buckets.id", ondelete="RESTRICT"), nullable=True)
    amount = Column(Integer, nullable=False)
    entry_type = Column(String(24), nullable=False)
    balance_after = Column(Integer, nullable=False)
    description = Column(String(500), nullable=False)
    reference_type = Column(String(80), nullable=True)
    reference_id = Column(String(255), nullable=True)
    idempotency_key = Column(String(255), nullable=True)
    actor_user_id = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    reason = Column(Text, nullable=True)
    metadata_json = Column(JSON, nullable=False, default=dict)
    occurred_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)


class CreditReservation(Base):
    __tablename__ = "product_credit_reservations"
    __table_args__ = (
        UniqueConstraint("reference_type", "reference_id", name="uq_product_credit_reservation_reference"),
        Index("ix_product_credit_reservations_status_expiry", "status", "expires_at"),
    )

    id = Column(String(36), primary_key=True, default=_uuid)
    account_id = Column(String(36), ForeignKey("product_credit_accounts.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    feature_key = Column(String(64), nullable=False)
    amount = Column(Integer, nullable=False)
    status = Column(String(24), nullable=False, default="reserved")
    catalog_version_id = Column(String(36), ForeignKey("product_billing_catalog_versions.id", ondelete="RESTRICT"), nullable=False)
    pricing_snapshot = Column(JSON, nullable=False)
    reference_type = Column(String(80), nullable=False)
    reference_id = Column(String(36), nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    captured_at = Column(DateTime(timezone=True), nullable=True)
    released_at = Column(DateTime(timezone=True), nullable=True)
    refunded_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)


class CreditReservationAllocation(Base):
    __tablename__ = "product_credit_reservation_allocations"
    __table_args__ = (UniqueConstraint("reservation_id", "bucket_id", name="uq_product_credit_reservation_bucket"),)

    id = Column(String(36), primary_key=True, default=_uuid)
    reservation_id = Column(String(36), ForeignKey("product_credit_reservations.id", ondelete="CASCADE"), nullable=False)
    bucket_id = Column(String(36), ForeignKey("product_credit_buckets.id", ondelete="RESTRICT"), nullable=False)
    amount = Column(Integer, nullable=False)


class SignupTrialGrant(Base):
    __tablename__ = "product_signup_trial_grants"
    __table_args__ = (UniqueConstraint("user_id", "policy_key", name="uq_product_signup_trial_grant"),)

    id = Column(String(36), primary_key=True, default=_uuid)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    policy_id = Column(String(36), ForeignKey("product_signup_trial_policies.id", ondelete="RESTRICT"), nullable=False)
    policy_key = Column(String(80), nullable=False)
    bucket_id = Column(String(36), ForeignKey("product_credit_buckets.id", ondelete="RESTRICT"), nullable=False)
    granted_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)


class BillingCheckoutSession(Base):
    __tablename__ = "product_billing_checkout_sessions"
    __table_args__ = (
        UniqueConstraint("user_id", "idempotency_key", name="uq_product_billing_checkout_idempotency"),
        UniqueConstraint("provider", "provider_session_id", name="uq_product_billing_provider_session"),
    )

    id = Column(String(36), primary_key=True, default=_uuid)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    offer_id = Column(String(36), ForeignKey("product_billing_offers.id", ondelete="RESTRICT"), nullable=False)
    catalog_version_id = Column(String(36), ForeignKey("product_billing_catalog_versions.id", ondelete="RESTRICT"), nullable=False)
    provider = Column(String(40), nullable=False)
    provider_session_id = Column(String(255), nullable=True)
    status = Column(String(24), nullable=False, default="created")
    offer_snapshot = Column(JSON, nullable=False)
    success_url = Column(Text, nullable=False)
    cancel_url = Column(Text, nullable=False)
    redirect_url = Column(Text, nullable=True)
    idempotency_key = Column(String(255), nullable=True)
    request_hash = Column(String(64), nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)


class PaymentEventInbox(Base):
    __tablename__ = "product_payment_event_inbox"
    __table_args__ = (
        UniqueConstraint("provider", "provider_event_id", name="uq_product_payment_event"),
        Index("ix_product_payment_event_status_received", "status", "received_at"),
    )

    id = Column(String(36), primary_key=True, default=_uuid)
    provider = Column(String(40), nullable=False)
    provider_event_id = Column(String(255), nullable=False)
    event_type = Column(String(120), nullable=False)
    status = Column(String(24), nullable=False, default="received")
    raw_body_hash = Column(String(64), nullable=False)
    raw_payload = Column(JSON, nullable=False)
    normalized_payload = Column(JSON, nullable=False)
    raw_payload_expires_at = Column(DateTime(timezone=True), nullable=False)
    error = Column(JSON, nullable=True)
    received_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
    processed_at = Column(DateTime(timezone=True), nullable=True)


class BillingCommand(Base):
    __tablename__ = "product_billing_commands"
    __table_args__ = (
        UniqueConstraint("actor_user_id", "command_type", "idempotency_key", name="uq_product_billing_command_idempotency"),
        Index("ix_product_billing_commands_actor_created", "actor_user_id", "created_at"),
    )

    id = Column(String(36), primary_key=True, default=_uuid)
    actor_user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    command_type = Column(String(120), nullable=False)
    idempotency_key = Column(String(255), nullable=False)
    request_hash = Column(String(64), nullable=False)
    status = Column(String(24), nullable=False, default="processing")
    resource_type = Column(String(80), nullable=True)
    resource_id = Column(String(36), nullable=True)
    response_snapshot = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
    completed_at = Column(DateTime(timezone=True), nullable=True)
