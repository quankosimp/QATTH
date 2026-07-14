from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field


class BillingOfferView(BaseModel):
    id: str
    code: str
    display_name: str
    offer_type: Literal["subscription", "topup"]
    amount_minor: int
    currency: str
    billing_interval: str | None
    credit_grant: int
    catalog_version: str


class FeatureCreditPriceView(BaseModel):
    feature_key: str
    credit_cost: int
    maximum_duration_minutes: int | None
    catalog_version: str


class BillingCatalogView(BaseModel):
    catalog_version: str
    currency: str
    effective_from: datetime
    subscription_offers: list[BillingOfferView]
    topup_offers: list[BillingOfferView]
    feature_prices: list[FeatureCreditPriceView]


class SignupTrialPolicyView(BaseModel):
    policy_key: str
    enabled: bool
    trigger: str
    credit_grant: int
    valid_days: int
    grants_per_user: int
    policy_version: str
    effective_from: datetime


class SubscriptionView(BaseModel):
    id: str | None
    offer: BillingOfferView | None
    status: str
    current_period_start: datetime | None
    current_period_end: datetime | None
    cancel_at_period_end: bool
    current_period_credit_grant: int


class CreditBucketView(BaseModel):
    id: str
    bucket_type: str
    source_reference: str | None
    granted: int
    available: int
    reserved: int
    expires_at: datetime | None
    created_at: datetime


class CreditLedgerEntryView(BaseModel):
    id: str
    bucket_id: str | None
    amount: int
    entry_type: str
    balance_after: int
    description: str
    reference_type: str | None
    reference_id: str | None
    occurred_at: datetime


class CreditAccountView(BaseModel):
    status: str
    available: int
    reserved: int
    trial_available: int
    subscription_available: int
    topup_available: int
    adjustment_available: int
    trial_expires_at: datetime | None
    buckets: list[CreditBucketView]
    entries: list[CreditLedgerEntryView]
    next_cursor: str | None


class CreateCheckoutRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    offer_id: str
    success_url: AnyHttpUrl
    cancel_url: AnyHttpUrl


class RedirectSessionView(BaseModel):
    id: str
    offer_id: str
    url: str
    expires_at: datetime


class BillingOfferDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(pattern=r"^[A-Z][A-Z0-9_]{2,63}$")
    display_name: str = Field(min_length=1, max_length=200)
    offer_type: Literal["subscription", "topup"]
    amount_minor: int = Field(gt=0)
    currency: Literal["VND"] = "VND"
    billing_interval: Literal["month"] | None = None
    credit_grant: int = Field(gt=0)


class FeatureCreditPriceDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    feature_key: str = Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")
    credit_cost: int = Field(ge=0)
    maximum_duration_minutes: int | None = Field(default=None, ge=1)


class CreateBillingCatalogVersionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version_key: str = Field(min_length=3, max_length=100)
    market: Literal["VN"] = "VN"
    currency: Literal["VND"] = "VND"
    offers: list[BillingOfferDraft] = Field(min_length=1)
    feature_prices: list[FeatureCreditPriceDraft] = Field(min_length=1)


class BillingCatalogVersionView(BaseModel):
    id: str
    version_key: str
    market: str
    currency: str
    status: str
    effective_from: datetime | None
    effective_to: datetime | None
    created_at: datetime
    published_at: datetime | None


class ActivateBillingCatalogRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    effective_from: datetime
    reason: str = Field(min_length=3, max_length=500)


class UpdateFeatureCreditPriceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    catalog_version_id: str
    credit_cost: int = Field(ge=0)
    maximum_duration_minutes: int | None = Field(default=None, ge=1)
    reason: str = Field(min_length=3, max_length=500)


class UpdateSignupTrialPolicyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool
    credit_grant: int = Field(gt=0)
    valid_days: int = Field(gt=0)
    reason: str = Field(min_length=3, max_length=500)
    effective_from: datetime | None = None


class CreditAdjustmentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: str
    amount: int
    reason: str = Field(min_length=3, max_length=500)
    reference: str | None = Field(default=None, max_length=255)


class CreditAdjustmentDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=3, max_length=500)


class CreditAdjustmentView(BaseModel):
    id: str
    target_user_id: str
    amount: int
    reason: str
    reference: str | None
    status: Literal["pending", "executed", "rejected"]
    dual_control_required: bool
    policy_threshold: int
    requested_by_user_id: str
    approved_by_user_id: str | None
    decision_reason: str | None
    ledger_entry: CreditLedgerEntryView | None
    created_at: datetime
    decided_at: datetime | None
    executed_at: datetime | None
