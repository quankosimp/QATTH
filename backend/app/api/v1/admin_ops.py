from __future__ import annotations

from datetime import datetime
from fastapi import APIRouter, Depends, Header, Query, Request, status
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.identity_security import ProductCurrentUser, require_product_scopes
from app.schemas.common import APIResponse, make_response
from app.schemas.product_admin_ops import (
    ActivateModelConfigurationRequest,
    AccountStatusView,
    AdminResourceSummary,
    AdminUserSummary,
    BackgroundJobPage,
    BackgroundJobView,
    CreateModelEvaluationReportRequest,
    CreateModelConfigurationRequest,
    JobSourceAdminView,
    ModelConfigurationView,
    ModelEvaluationReportView,
    ModerationCaseView,
    OpsDiagnosticsView,
    ProviderUsageSummaryView,
    ResolveModerationCaseRequest,
    RetryBackgroundJobRequest,
    UpdateJobSourceRequest,
    UpdateAccountStatusRequest,
)
from app.services.product_admin_ops import ProductAdminOpsService

router = APIRouter(tags=["Admin", "Operations"])

model_read = require_product_scopes("admin:model:read")
model_write = require_product_scopes("admin:model:write")
jobs_read = require_product_scopes("admin:jobs:read")
jobs_write = require_product_scopes("admin:jobs:write")
users_read = require_product_scopes("admin:users:read")
users_write = require_product_scopes("admin:users:write")
resources_read = require_product_scopes("admin:resources:read")
ops_read = require_product_scopes("ops:jobs:read")
ops_write = require_product_scopes("ops:jobs:write")


def _context(request: Request) -> dict:
    return {"request_id": getattr(request.state, "request_id", None), "ip": request.client.host if request.client else None}


@router.get("/admin/model-configurations", response_model=APIResponse[list[ModelConfigurationView]])
def list_model_configurations(request: Request, current: ProductCurrentUser = Depends(model_read), db: Session = Depends(get_db)):
    return make_response(ProductAdminOpsService(db).list_model_configurations(current, _context(request)), request=request)


@router.post("/admin/model-configurations", response_model=APIResponse[ModelConfigurationView], status_code=status.HTTP_201_CREATED)
def create_model_configuration(payload: CreateModelConfigurationRequest, request: Request, idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=8, max_length=128), current: ProductCurrentUser = Depends(model_write), db: Session = Depends(get_db)):
    service = ProductAdminOpsService(db)
    return make_response(service.model_view(service.create_model_configuration(current, payload, idempotency_key, _context(request))), request=request)


@router.get("/admin/model-configurations/{configuration_id}/evaluation-reports", response_model=APIResponse[list[ModelEvaluationReportView]])
def list_model_evaluation_reports(configuration_id: str, request: Request, current: ProductCurrentUser = Depends(model_read), db: Session = Depends(get_db)):
    return make_response(ProductAdminOpsService(db).list_model_evaluation_reports(current, configuration_id, _context(request)), request=request)


@router.post("/admin/model-configurations/{configuration_id}/evaluation-reports", response_model=APIResponse[ModelEvaluationReportView], status_code=status.HTTP_201_CREATED)
def create_model_evaluation_report(configuration_id: str, payload: CreateModelEvaluationReportRequest, request: Request, idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=8, max_length=128), current: ProductCurrentUser = Depends(model_write), db: Session = Depends(get_db)):
    service = ProductAdminOpsService(db)
    report = service.create_model_evaluation_report(current, configuration_id, payload, idempotency_key, _context(request))
    return make_response(service.evaluation_report_view(report), request=request)


@router.post("/admin/model-configurations/{configuration_id}/activate", response_model=APIResponse[ModelConfigurationView])
def activate_model_configuration(configuration_id: str, payload: ActivateModelConfigurationRequest, request: Request, idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=8, max_length=128), current: ProductCurrentUser = Depends(model_write), db: Session = Depends(get_db)):
    service = ProductAdminOpsService(db)
    return make_response(service.model_view(service.activate_model_configuration(current, configuration_id, payload, idempotency_key, _context(request))), request=request)


@router.get("/admin/job-sources", response_model=APIResponse[list[JobSourceAdminView]])
def list_admin_job_sources(request: Request, source_status: str | None = Query(default=None, alias="status"), key: str | None = None, period_start: datetime | None = None, period_end: datetime | None = None, current: ProductCurrentUser = Depends(jobs_read), db: Session = Depends(get_db)):
    return make_response(ProductAdminOpsService(db).job_sources(current, _context(request), source_status, key, period_start, period_end), request=request)


@router.patch("/admin/job-sources/{source_id}", response_model=APIResponse[JobSourceAdminView])
def update_admin_job_source(source_id: str, payload: UpdateJobSourceRequest, request: Request, idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=8, max_length=128), current: ProductCurrentUser = Depends(jobs_write), db: Session = Depends(get_db)):
    service = ProductAdminOpsService(db)
    source = service.update_job_source(current, source_id, payload, idempotency_key, _context(request))
    return make_response(next(item for item in service.job_sources(current, _context(request)) if item.id == source.id), request=request)


@router.get("/admin/users", response_model=APIResponse[list[AdminUserSummary]])
def search_admin_users(request: Request, q: str = Query(..., min_length=3, max_length=320), current: ProductCurrentUser = Depends(users_read), db: Session = Depends(get_db)):
    return make_response(ProductAdminOpsService(db).search_users(current, q, _context(request)), request=request)


@router.get("/admin/resources/{resource_type}/{resource_id}", response_model=APIResponse[AdminResourceSummary])
def get_admin_resource(resource_type: str, resource_id: str, request: Request, current: ProductCurrentUser = Depends(resources_read), db: Session = Depends(get_db)):
    return make_response(ProductAdminOpsService(db).resource(current, resource_type, resource_id, _context(request)), request=request)


@router.patch("/admin/users/{user_id}/status", response_model=APIResponse[AccountStatusView])
def update_admin_user_status(
    user_id: str,
    payload: UpdateAccountStatusRequest,
    request: Request,
    idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=8, max_length=128),
    current: ProductCurrentUser = Depends(users_write),
    db: Session = Depends(get_db),
):
    return make_response(
        ProductAdminOpsService(db).update_account_status(
            current,
            user_id,
            payload,
            idempotency_key,
            _context(request),
        ),
        request=request,
    )


@router.get("/admin/moderation-cases", response_model=APIResponse[list[ModerationCaseView]])
def list_moderation_cases(request: Request, case_status: str | None = Query(default="open", alias="status"), source_id: str | None = None, period_start: datetime | None = None, period_end: datetime | None = None, current: ProductCurrentUser = Depends(jobs_read), db: Session = Depends(get_db)):
    return make_response(ProductAdminOpsService(db).moderation_cases(current, case_status, source_id, period_start, period_end, _context(request)), request=request)


@router.post("/admin/moderation-cases/{case_id}/resolve", response_model=APIResponse[ModerationCaseView])
def resolve_moderation_case(case_id: str, payload: ResolveModerationCaseRequest, request: Request, idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=8, max_length=128), current: ProductCurrentUser = Depends(jobs_write), db: Session = Depends(get_db)):
    service = ProductAdminOpsService(db)
    return make_response(service.moderation_view(service.resolve_moderation_case(current, case_id, payload, idempotency_key, _context(request))), request=request)


@router.get("/ops/background-jobs", response_model=APIResponse[BackgroundJobPage])
def list_background_jobs(request: Request, job_status: str | None = Query(default=None, alias="status"), cursor: str | None = None, limit: int = Query(default=20, ge=1, le=100), current: ProductCurrentUser = Depends(ops_read), db: Session = Depends(get_db)):
    return make_response(ProductAdminOpsService(db).background_jobs(current, _context(request), job_status, cursor, limit), request=request)


@router.post("/ops/background-jobs/{job_id}/retry", response_model=APIResponse[BackgroundJobView], status_code=status.HTTP_202_ACCEPTED)
def retry_background_job(job_id: str, payload: RetryBackgroundJobRequest, request: Request, idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=8, max_length=128), current: ProductCurrentUser = Depends(ops_write), db: Session = Depends(get_db)):
    service = ProductAdminOpsService(db)
    return make_response(service.job_view(service.retry_job(current, job_id, payload, idempotency_key, _context(request))), request=request)


@router.get("/ops/diagnostics", response_model=APIResponse[OpsDiagnosticsView])
def get_ops_diagnostics(request: Request, current: ProductCurrentUser = Depends(ops_read), db: Session = Depends(get_db)):
    return make_response(ProductAdminOpsService(db).diagnostics(), request=request)


@router.get("/ops/provider-usage", response_model=APIResponse[ProviderUsageSummaryView])
def get_provider_usage(
    request: Request,
    provider: str | None = None,
    purpose: str | None = None,
    period_start: datetime | None = None,
    period_end: datetime | None = None,
    current: ProductCurrentUser = Depends(ops_read),
    db: Session = Depends(get_db),
):
    return make_response(
        ProductAdminOpsService(db).provider_usage_summary(provider, purpose, period_start, period_end),
        request=request,
    )
