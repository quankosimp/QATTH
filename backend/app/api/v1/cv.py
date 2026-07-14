from __future__ import annotations

from fastapi import APIRouter, Depends, Header, Request, status
from sqlalchemy.orm import Session

from backend.app.core.db import get_db
from backend.app.core.errors import AppError
from backend.app.core.identity_security import ProductCurrentUser, get_product_user
from backend.app.schemas.common import APIResponse, make_response
from backend.app.schemas.product_cv import (
    ConfirmCvDraftRequest,
    CreateCvScanRequest,
    CvAnalysisView,
    CvDraftPatch,
    CvDraftView,
    CvPage,
    CvScanView,
    CvVersionView,
    SetActiveVersionRequest,
)
from backend.app.services.product_cv import ProductCvService

router = APIRouter(tags=["CV"])


def _revision(if_match: str) -> int:
    value = if_match.strip().removeprefix('W/').strip('"')
    try:
        return int(value)
    except ValueError as exc:
        raise AppError(422, "INVALID_IF_MATCH", "If-Match must contain the current numeric revision") from exc


@router.post("/cv-scans", response_model=APIResponse[CvScanView], status_code=status.HTTP_202_ACCEPTED)
def create_scan(
    payload: CreateCvScanRequest,
    request: Request,
    current: ProductCurrentUser = Depends(get_product_user),
    db: Session = Depends(get_db),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key", max_length=255),
):
    service = ProductCvService(db)
    return make_response(service.scan_view(service.create_scan(current, payload)), request=request)


@router.get("/cv-scans/{scan_id}", response_model=APIResponse[CvScanView])
def get_scan(
    scan_id: str,
    request: Request,
    current: ProductCurrentUser = Depends(get_product_user),
    db: Session = Depends(get_db),
):
    service = ProductCvService(db)
    return make_response(service.scan_view(service.get_scan(current, scan_id)), request=request)


@router.get("/cv-scans/{scan_id}/draft", response_model=APIResponse[CvDraftView])
def get_draft(
    scan_id: str,
    request: Request,
    current: ProductCurrentUser = Depends(get_product_user),
    db: Session = Depends(get_db),
):
    service = ProductCvService(db)
    return make_response(service.draft_view(service.get_draft(current, scan_id)), request=request)


@router.patch("/cv-scans/{scan_id}/draft", response_model=APIResponse[CvDraftView])
def update_draft(
    scan_id: str,
    payload: CvDraftPatch,
    request: Request,
    if_match: str = Header(alias="If-Match"),
    current: ProductCurrentUser = Depends(get_product_user),
    db: Session = Depends(get_db),
):
    service = ProductCvService(db)
    draft = service.update_draft(current, scan_id, _revision(if_match), payload)
    return make_response(service.draft_view(draft), request=request)


@router.post("/cv-scans/{scan_id}/confirm", response_model=APIResponse[CvVersionView], status_code=status.HTTP_201_CREATED)
def confirm_draft(
    scan_id: str,
    payload: ConfirmCvDraftRequest,
    request: Request,
    current: ProductCurrentUser = Depends(get_product_user),
    db: Session = Depends(get_db),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key", max_length=255),
):
    service = ProductCvService(db)
    version = service.confirm(current, scan_id, payload)
    return make_response(service.version_view(version), request=request)


@router.get("/cvs", response_model=APIResponse[CvPage])
def list_cvs(
    request: Request,
    cursor: str | None = None,
    limit: int = 20,
    current: ProductCurrentUser = Depends(get_product_user),
    db: Session = Depends(get_db),
):
    if limit < 1 or limit > 100:
        raise AppError(422, "INVALID_LIMIT", "Limit must be between 1 and 100")
    return make_response(ProductCvService(db).list_cvs(current, cursor, limit), request=request)


@router.get("/cvs/{cv_id}/versions", response_model=APIResponse[list[CvVersionView]])
def list_versions(
    cv_id: str,
    request: Request,
    current: ProductCurrentUser = Depends(get_product_user),
    db: Session = Depends(get_db),
):
    service = ProductCvService(db)
    return make_response([service.version_view(item) for item in service.list_versions(current, cv_id)], request=request)


@router.put("/cvs/{cv_id}/active-version", response_model=APIResponse[CvVersionView])
def set_active_version(
    cv_id: str,
    payload: SetActiveVersionRequest,
    request: Request,
    current: ProductCurrentUser = Depends(get_product_user),
    db: Session = Depends(get_db),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key", max_length=255),
):
    service = ProductCvService(db)
    return make_response(service.version_view(service.set_active_version(current, cv_id, payload.version_id)), request=request)


@router.post("/cv-versions/{version_id}/analyses", response_model=APIResponse[CvAnalysisView], status_code=status.HTTP_202_ACCEPTED)
def create_analysis(
    version_id: str,
    request: Request,
    current: ProductCurrentUser = Depends(get_product_user),
    db: Session = Depends(get_db),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key", max_length=255),
):
    service = ProductCvService(db)
    return make_response(service.analysis_view(service.create_analysis(current, version_id)), request=request)


@router.get("/cv-analyses/{analysis_id}", response_model=APIResponse[CvAnalysisView])
def get_analysis(
    analysis_id: str,
    request: Request,
    current: ProductCurrentUser = Depends(get_product_user),
    db: Session = Depends(get_db),
):
    service = ProductCvService(db)
    return make_response(service.analysis_view(service.get_analysis(current, analysis_id)), request=request)
