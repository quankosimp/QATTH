from __future__ import annotations

from fastapi import APIRouter, Depends, Header, Request, Response, status
from sqlalchemy.orm import Session

from backend.app.core.db import get_db
from backend.app.core.identity_security import ProductCurrentUser, get_product_user
from backend.app.schemas.common import APIResponse, make_response
from backend.app.schemas.product_cv import (
    CompleteUploadRequest,
    CreateUploadIntentRequest,
    FileAssetView,
    SignedUrlView,
    UploadIntentView,
)
from backend.app.services.product_files import ProductFileService

router = APIRouter(prefix="/files", tags=["Files"])


@router.post("/upload-intents", response_model=APIResponse[UploadIntentView], status_code=status.HTTP_201_CREATED)
def create_upload_intent(
    payload: CreateUploadIntentRequest,
    request: Request,
    current: ProductCurrentUser = Depends(get_product_user),
    db: Session = Depends(get_db),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key", max_length=255),
):
    return make_response(ProductFileService(db).create_intent(current, payload), request=request)


@router.put("/local-upload/{object_key:path}", status_code=status.HTTP_204_NO_CONTENT, include_in_schema=False)
async def local_upload(
    object_key: str,
    request: Request,
    db: Session = Depends(get_db),
):
    ProductFileService(db).put_local(object_key, await request.body(), request.headers.get("content-type"))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{file_id}/complete", response_model=APIResponse[FileAssetView])
def complete_upload(
    file_id: str,
    payload: CompleteUploadRequest,
    request: Request,
    current: ProductCurrentUser = Depends(get_product_user),
    db: Session = Depends(get_db),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key", max_length=255),
):
    return make_response(FileAssetView.model_validate(ProductFileService(db).complete(current, file_id, payload)), request=request)


@router.post("/{file_id}/download-url", response_model=APIResponse[SignedUrlView])
def create_download_url(
    file_id: str,
    request: Request,
    current: ProductCurrentUser = Depends(get_product_user),
    db: Session = Depends(get_db),
):
    url, expires_at = ProductFileService(db).download_url(current, file_id)
    return make_response(SignedUrlView(url=url, expires_at=expires_at), request=request)
