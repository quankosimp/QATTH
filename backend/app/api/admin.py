from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import CurrentUser, require_admin
from app.schemas.admin import (
    AdminCVScanList,
    AdminCrawlRunList,
    AdminInterviewList,
    AdminJobList,
    AdminOverview,
    AdminUserList,
    UserStatusUpdate,
)
from app.schemas.auth import UserRead
from app.schemas.common import APIResponse, make_response
from app.services.admin import AdminService

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/overview", response_model=APIResponse[AdminOverview])
def overview(
    request: Request,
    db: Session = Depends(get_db),
    _: CurrentUser = Depends(require_admin),
) -> APIResponse[AdminOverview]:
    return make_response(AdminService(db=db).overview(), request=request)


@router.get("/users", response_model=APIResponse[AdminUserList])
def list_users(
    request: Request,
    db: Session = Depends(get_db),
    _: CurrentUser = Depends(require_admin),
) -> APIResponse[AdminUserList]:
    return make_response(AdminService(db=db).list_users(), request=request)


@router.patch("/users/{user_id}/status", response_model=APIResponse[UserRead])
def update_user_status(
    request: Request,
    user_id: str,
    payload: UserStatusUpdate,
    db: Session = Depends(get_db),
    _: CurrentUser = Depends(require_admin),
) -> APIResponse[UserRead]:
    result = AdminService(db=db).update_user_status(user_id=user_id, is_active=payload.is_active)
    return make_response(result, request=request)


@router.get("/cv-scans", response_model=APIResponse[AdminCVScanList])
def list_cv_scans(
    request: Request,
    status: str | None = None,
    db: Session = Depends(get_db),
    _: CurrentUser = Depends(require_admin),
) -> APIResponse[AdminCVScanList]:
    return make_response(AdminService(db=db).list_cv_scans(status=status), request=request)


@router.get("/interviews", response_model=APIResponse[AdminInterviewList])
def list_interviews(
    request: Request,
    status: str | None = None,
    db: Session = Depends(get_db),
    _: CurrentUser = Depends(require_admin),
) -> APIResponse[AdminInterviewList]:
    return make_response(AdminService(db=db).list_interviews(status=status), request=request)


@router.get("/crawl-runs", response_model=APIResponse[AdminCrawlRunList])
def list_crawl_runs(
    request: Request,
    status: str | None = None,
    db: Session = Depends(get_db),
    _: CurrentUser = Depends(require_admin),
) -> APIResponse[AdminCrawlRunList]:
    return make_response(AdminService(db=db).list_crawl_runs(status=status), request=request)


@router.get("/jobs", response_model=APIResponse[AdminJobList])
def list_jobs(
    request: Request,
    source: str | None = None,
    db: Session = Depends(get_db),
    _: CurrentUser = Depends(require_admin),
) -> APIResponse[AdminJobList]:
    return make_response(AdminService(db=db).list_jobs(source=source), request=request)
