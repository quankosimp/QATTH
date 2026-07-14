from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, Depends, Header, Request, Response, status
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.identity_security import ProductCurrentUser, get_product_user
from app.schemas.common import APIResponse, make_response
from app.schemas.product_cv import (
    CompleteUploadRequest,
    CreateUploadIntentRequest,
    FileAssetView,
    SignedUrlView,
    UploadIntentView,
)
from app.services.product_files import ProductFileService

router = APIRouter(prefix="/files", tags=["Files"])


@router.post("/upload-intents", response_model=APIResponse[UploadIntentView], status_code=status.HTTP_201_CREATED)
def create_upload_intent(
    payload: CreateUploadIntentRequest,
    request: Request,
    current: ProductCurrentUser = Depends(get_product_user),
    db: Session = Depends(get_db),
    idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=8, max_length=128),
):
    return make_response(ProductFileService(db).create_intent(current, payload, idempotency_key), request=request)


@router.put("/local-upload/{object_key:path}", status_code=status.HTTP_204_NO_CONTENT, include_in_schema=False)
async def local_upload(
    object_key: str,
    request: Request,
    db: Session = Depends(get_db),
):
    ProductFileService(db).put_local(object_key, await request.body(), request.headers.get("content-type"))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/local-download/{object_key:path}", include_in_schema=False)
def local_download(
    object_key: str,
    current: ProductCurrentUser = Depends(get_product_user),
    db: Session = Depends(get_db),
):
    asset, content = ProductFileService(db).read_local_owned(current, object_key)
    return Response(
        content=content,
        media_type=asset.content_type,
        headers={
            "Cache-Control": "private, no-store",
            "Content-Disposition": "attachment; filename*=UTF-8''" + quote(asset.original_filename),
        },
    )


@router.post("/{file_id}/complete", response_model=APIResponse[FileAssetView])
def complete_upload(
    file_id: str,
    payload: CompleteUploadRequest,
    request: Request,
    current: ProductCurrentUser = Depends(get_product_user),
    db: Session = Depends(get_db),
    idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=8, max_length=128),
):
    return make_response(FileAssetView.model_validate(ProductFileService(db).complete(current, file_id, payload, idempotency_key)), request=request)


@router.post("/{file_id}/download-url", response_model=APIResponse[SignedUrlView])
def create_download_url(
    file_id: str,
    request: Request,
    current: ProductCurrentUser = Depends(get_product_user),
    db: Session = Depends(get_db),
):
    url, expires_at = ProductFileService(db).download_url(current, file_id)
    return make_response(SignedUrlView(url=url, expires_at=expires_at), request=request)
