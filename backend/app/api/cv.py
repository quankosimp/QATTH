from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import CurrentUser, get_current_user
from app.schemas.common import APIResponse, make_response
from app.schemas.cv import CVProfile, CVReadResult, CVSaveResult, CVScanResult
from app.services.cv_scan import CVScanService

router = APIRouter(prefix="/cvs", tags=["cvs"])


@router.post("/scan", response_model=APIResponse[CVScanResult])
async def scan_cv(
    request: Request,
    file: UploadFile = File(...),
    target_role: str | None = Form(default=None),
    language: str = Form(default="vi"),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> APIResponse[CVScanResult]:
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


@router.get("/{cv_id}", response_model=APIResponse[CVReadResult])
def get_cv(
    request: Request,
    cv_id: str,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> APIResponse[CVReadResult]:
    result = CVScanService(db=db).get(cv_id=cv_id, current_user=current_user)
    return make_response(result, request=request)
