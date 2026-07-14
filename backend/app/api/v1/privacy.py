from fastapi import APIRouter, Depends, Header, Query, Request, Response, status
from sqlalchemy.orm import Session

from backend.app.core.db import get_db
from backend.app.core.identity_security import ProductCurrentUser, get_product_user
from backend.app.schemas.common import APIResponse, make_response
from backend.app.schemas.product_privacy import CreateDeletionRequest, PrivacyRequestView
from backend.app.services.product_privacy import ProductPrivacyService

router = APIRouter(tags=["Privacy"])


@router.post("/privacy/exports", response_model=APIResponse[PrivacyRequestView], status_code=status.HTTP_202_ACCEPTED)
def create_privacy_export(request: Request, idempotency_key: str = Header(..., alias="Idempotency-Key", max_length=255), current: ProductCurrentUser = Depends(get_product_user), db: Session = Depends(get_db)):
    service = ProductPrivacyService(db)
    return make_response(service.view(service.create_export(current, idempotency_key)), request=request)


@router.post("/privacy/deletions", response_model=APIResponse[PrivacyRequestView], status_code=status.HTTP_202_ACCEPTED)
def create_privacy_deletion(payload: CreateDeletionRequest, request: Request, idempotency_key: str = Header(..., alias="Idempotency-Key", max_length=255), current: ProductCurrentUser = Depends(get_product_user), db: Session = Depends(get_db)):
    service = ProductPrivacyService(db)
    return make_response(service.view(service.create_deletion(current, payload, idempotency_key)), request=request)


@router.get("/privacy/requests/{request_id}", response_model=APIResponse[PrivacyRequestView])
def get_privacy_request(request_id: str, request: Request, current: ProductCurrentUser = Depends(get_product_user), db: Session = Depends(get_db)):
    service = ProductPrivacyService(db)
    return make_response(service.view(service.get(current, request_id)), request=request)


@router.get("/privacy/requests/{request_id}/download", include_in_schema=False)
def download_privacy_export(request_id: str, token: str = Query(..., min_length=32, max_length=256), db: Session = Depends(get_db)):
    content = ProductPrivacyService(db).download(request_id, token)
    return Response(content=content, media_type="application/zip", headers={"Content-Disposition": 'attachment; filename="qatth-personal-data.zip"', "Cache-Control": "private, no-store"})
