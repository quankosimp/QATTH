from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Header, Query, Request, status
from sqlalchemy.orm import Session

from backend.app.core.db import get_db
from backend.app.core.errors import AppError
from backend.app.core.identity_security import ProductCurrentUser, get_product_user, require_product_scopes
from backend.app.schemas.common import APIResponse, make_response
from backend.app.schemas.product_billing import (
    ActivateBillingCatalogRequest,
    BillingCatalogVersionView,
    BillingCatalogView,
    CreateBillingCatalogVersionRequest,
    CreateCheckoutRequest,
    CreditAccountView,
    CreditAdjustmentRequest,
    CreditLedgerEntryView,
    FeatureCreditPriceView,
    RedirectSessionView,
    SignupTrialPolicyView,
    SubscriptionView,
    UpdateFeatureCreditPriceRequest,
    UpdateSignupTrialPolicyRequest,
)
from backend.app.services.product_billing import ProductBillingService

router = APIRouter(tags=["Billing"])
billing_read = require_product_scopes("admin:billing:read")
billing_write = require_product_scopes("admin:billing:write")


@router.get("/billing/catalog", response_model=APIResponse[BillingCatalogView])
def get_billing_catalog(request: Request, db: Session = Depends(get_db)):
    return make_response(ProductBillingService(db).catalog_view(), request=request)


@router.get("/billing/feature-pricing", response_model=APIResponse[list[FeatureCreditPriceView]])
def get_feature_pricing(request: Request, db: Session = Depends(get_db)):
    return make_response(ProductBillingService(db).feature_prices(), request=request)


@router.get("/billing/signup-trial-policy", response_model=APIResponse[SignupTrialPolicyView])
def get_signup_trial_policy(request: Request, db: Session = Depends(get_db)):
    return make_response(ProductBillingService(db).trial_policy_view(), request=request)


@router.get("/billing/subscription", response_model=APIResponse[SubscriptionView])
def get_current_subscription(request: Request, current: ProductCurrentUser = Depends(get_product_user), db: Session = Depends(get_db)):
    return make_response(ProductBillingService(db).current_subscription(current), request=request)


@router.get("/billing/credits", response_model=APIResponse[CreditAccountView])
def get_credit_account(request: Request, cursor: str | None = None, limit: int = Query(default=20, ge=1, le=100), current: ProductCurrentUser = Depends(get_product_user), db: Session = Depends(get_db)):
    return make_response(ProductBillingService(db).credit_account(current, cursor, limit), request=request)


@router.post("/billing/checkout-sessions", response_model=APIResponse[RedirectSessionView], status_code=status.HTTP_201_CREATED)
def create_checkout_session(payload: CreateCheckoutRequest, request: Request, idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=8, max_length=128), current: ProductCurrentUser = Depends(get_product_user), db: Session = Depends(get_db)):
    return make_response(ProductBillingService(db).create_checkout(current, payload, idempotency_key), request=request)


@router.post("/billing/portal-sessions", response_model=APIResponse[RedirectSessionView], status_code=status.HTTP_201_CREATED)
def create_portal_session(request: Request, idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=8, max_length=128), current: ProductCurrentUser = Depends(get_product_user), db: Session = Depends(get_db)):
    return make_response(ProductBillingService(db).create_portal(current, idempotency_key), request=request)


@router.post("/webhooks/payments/{provider}", status_code=status.HTTP_202_ACCEPTED)
async def receive_payment_webhook(provider: str, request: Request, signature: str | None = Header(default=None, alias="X-Payment-Signature"), db: Session = Depends(get_db)):
    raw_body = await request.body()
    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError as exc:
        raise AppError(422, "INVALID_WEBHOOK_PAYLOAD", "Payment webhook body must be valid JSON") from exc
    inbox = ProductBillingService(db).process_webhook(provider, raw_body, signature, payload)
    return make_response({"event_id": inbox.provider_event_id, "status": inbox.status}, request=request)


@router.get("/admin/billing/catalog-versions", response_model=APIResponse[list[BillingCatalogVersionView]])
def list_catalog_versions(request: Request, current: ProductCurrentUser = Depends(billing_read), db: Session = Depends(get_db)):
    return make_response(ProductBillingService(db).list_catalog_versions(), request=request)


@router.post("/admin/billing/catalog-versions", response_model=APIResponse[BillingCatalogVersionView], status_code=status.HTTP_201_CREATED)
def create_catalog_version(payload: CreateBillingCatalogVersionRequest, request: Request, idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=8, max_length=128), current: ProductCurrentUser = Depends(billing_write), db: Session = Depends(get_db)):
    service = ProductBillingService(db)
    return make_response(service.catalog_version_view(service.create_catalog_version(current, payload, idempotency_key)), request=request)


@router.post("/admin/billing/catalog-versions/{catalog_version_id}/activate", response_model=APIResponse[BillingCatalogVersionView])
def activate_catalog_version(catalog_version_id: str, payload: ActivateBillingCatalogRequest, request: Request, idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=8, max_length=128), current: ProductCurrentUser = Depends(billing_write), db: Session = Depends(get_db)):
    service = ProductBillingService(db)
    return make_response(service.catalog_version_view(service.activate_catalog(current, catalog_version_id, payload, idempotency_key)), request=request)


@router.put("/admin/billing/feature-pricing/{feature_key}", response_model=APIResponse[FeatureCreditPriceView])
def set_feature_credit_price(feature_key: str, payload: UpdateFeatureCreditPriceRequest, request: Request, idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=8, max_length=128), current: ProductCurrentUser = Depends(billing_write), db: Session = Depends(get_db)):
    service = ProductBillingService(db)
    price = service.update_feature_price(current, payload.catalog_version_id, feature_key, payload, idempotency_key)
    catalog = db.get(__import__("backend.app.models.product_billing", fromlist=["BillingCatalogVersion"]).BillingCatalogVersion, payload.catalog_version_id)
    return make_response(service.price_view(price, catalog), request=request)


@router.put("/admin/billing/signup-trial-policy", response_model=APIResponse[SignupTrialPolicyView])
def update_signup_trial_policy(payload: UpdateSignupTrialPolicyRequest, request: Request, idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=8, max_length=128), current: ProductCurrentUser = Depends(billing_write), db: Session = Depends(get_db)):
    service = ProductBillingService(db)
    policy = service.publish_trial_policy(current, payload, idempotency_key)
    return make_response(SignupTrialPolicyView(policy_key=policy.policy_key, enabled=policy.enabled, trigger=policy.trigger, credit_grant=policy.credit_grant, valid_days=policy.valid_days, grants_per_user=policy.grants_per_user, policy_version=policy.policy_version, effective_from=policy.effective_from), request=request)


@router.post("/admin/credit-adjustments", response_model=APIResponse[CreditLedgerEntryView], status_code=status.HTTP_201_CREATED)
def create_credit_adjustment(payload: CreditAdjustmentRequest, request: Request, idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=8, max_length=128), current: ProductCurrentUser = Depends(billing_write), db: Session = Depends(get_db)):
    entry = ProductBillingService(db).adjust_credits(current, payload, idempotency_key)
    return make_response(CreditLedgerEntryView.model_validate({column: getattr(entry, column) for column in ("id", "bucket_id", "amount", "entry_type", "balance_after", "description", "reference_type", "reference_id", "occurred_at")}), request=request)
