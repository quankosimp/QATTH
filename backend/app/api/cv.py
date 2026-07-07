from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.errors import AppError
from app.core.security import CurrentUser, get_current_user
from app.schemas.common import APIResponse, make_response
from app.schemas.cv import (
    CVListResult,
    CVProfile,
    CVReadResult,
    CVSaveResult,
    CVScanResult,
    CVVersionListResult,
)
from app.schemas.profile import ConsentPayload
from app.services.cv_scan import CVScanService
from app.services.profile import ProfileService

router = APIRouter(prefix="/cvs", tags=["cvs"])


@router.get("", response_model=APIResponse[CVListResult])
def list_cvs(
    request: Request,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> APIResponse[CVListResult]:
    result = CVScanService(db=db).list(current_user=current_user)
    return make_response(result, request=request)


@router.post("/scan", response_model=APIResponse[CVScanResult])
async def scan_cv(
    request: Request,
    file: UploadFile = File(...),
    target_role: str | None = Form(default=None),
    language: str = Form(default="vi"),
    consent_accepted: bool = Form(default=False),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> APIResponse[CVScanResult]:
    if not consent_accepted:
        raise AppError(
            status_code=422,
            code="CV_PROCESSING_CONSENT_REQUIRED",
            message="CV processing consent is required before scanning a CV.",
        )
    ProfileService(db=db, current_user=current_user).record_consent(
        ConsentPayload(consent_type="cv_processing", accepted=True)
    )
    result = await CVScanService(db=db).scan(
        upload_file=file,
        target_role=target_role,
        language=language,
        current_user=current_user,
    )
    return make_response(result, request=request)


@router.put("/{cv_id}/profile", response_model=APIResponse[CVSaveResult])
def save_cv_profile(
    request: Request,
    cv_id: str,
    profile: CVProfile,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> APIResponse[CVSaveResult]:
    result = CVScanService(db=db).save_profile(
        cv_id=cv_id,
        profile=profile,
        current_user=current_user,
    )
    return make_response(result, request=request)


@router.get("/{cv_id}/versions", response_model=APIResponse[CVVersionListResult])
def list_cv_versions(
    request: Request,
    cv_id: str,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> APIResponse[CVVersionListResult]:
    result = CVScanService(db=db).list_versions(cv_id=cv_id, current_user=current_user)
    return make_response(result, request=request)


@router.get("/{cv_id}", response_model=APIResponse[CVReadResult])
def get_cv(
    request: Request,
    cv_id: str,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> APIResponse[CVReadResult]:
    result = CVScanService(db=db).get(cv_id=cv_id, current_user=current_user)
    return make_response(result, request=request)
