from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import CurrentUser, get_current_user
from app.schemas.common import APIResponse, make_response
from app.schemas.files import FileAssetRead, SignedUrlResult
from app.services.files import FileAssetService

router = APIRouter(prefix="/files", tags=["files"])


@router.get("/{file_id}", response_model=APIResponse[FileAssetRead])
def get_file_asset(
    request: Request,
    file_id: str,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> APIResponse[FileAssetRead]:
    result = FileAssetService(db=db, current_user=current_user).get(file_id=file_id)
    return make_response(result, request=request)


@router.get("/{file_id}/signed-url", response_model=APIResponse[SignedUrlResult])
def get_signed_url(
    request: Request,
    file_id: str,
    expires_seconds: int = Query(default=900, ge=60, le=3600),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> APIResponse[SignedUrlResult]:
    result = FileAssetService(db=db, current_user=current_user).signed_url(
        file_id=file_id,
        expires_seconds=expires_seconds,
    )
    return make_response(result, request=request)
