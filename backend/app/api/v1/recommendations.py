from fastapi import APIRouter, Depends, Header, Query, Request, status
from sqlalchemy.orm import Session

from backend.app.core.db import get_db
from backend.app.core.identity_security import ProductCurrentUser, get_product_user
from backend.app.schemas.common import APIResponse, make_response
from backend.app.schemas.product_recommendations import (
    CreateJobApplicationRequest,
    CreateRecommendationRunRequest,
    JobApplicationPage,
    JobApplicationView,
    JobInteractionView,
    RecommendationMatchPage,
    RecommendationRunView,
    UpdateJobApplicationRequest,
    UpsertJobInteractionRequest,
)
from backend.app.services.product_recommendations import ProductRecommendationService

router = APIRouter(tags=["Recommendations"])


@router.put("/jobs/{job_id}/interactions", response_model=APIResponse[JobInteractionView])
def upsert_job_interaction(
    job_id: str,
    payload: UpsertJobInteractionRequest,
    request: Request,
    current: ProductCurrentUser = Depends(get_product_user),
    db: Session = Depends(get_db),
):
    service = ProductRecommendationService(db)
    return make_response(service.interaction_view(service.upsert_interaction(current, job_id, payload)), request=request)


@router.get("/job-applications", response_model=APIResponse[JobApplicationPage])
def list_job_applications(
    request: Request,
    application_status: str | None = Query(default=None, alias="status"),
    cursor: str | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    current: ProductCurrentUser = Depends(get_product_user),
    db: Session = Depends(get_db),
):
    return make_response(ProductRecommendationService(db).applications(current, application_status, cursor, limit), request=request)


@router.post("/job-applications", response_model=APIResponse[JobApplicationView], status_code=status.HTTP_201_CREATED)
def create_job_application(
    payload: CreateJobApplicationRequest,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key", max_length=255),
    current: ProductCurrentUser = Depends(get_product_user),
    db: Session = Depends(get_db),
):
    service = ProductRecommendationService(db)
    application = service.create_application(current, payload, idempotency_key)
    return make_response(service.application_view(application), request=request)


@router.patch("/job-applications/{application_id}", response_model=APIResponse[JobApplicationView])
def update_job_application(
    application_id: str,
    payload: UpdateJobApplicationRequest,
    request: Request,
    current: ProductCurrentUser = Depends(get_product_user),
    db: Session = Depends(get_db),
):
    service = ProductRecommendationService(db)
    return make_response(service.application_view(service.update_application(current, application_id, payload)), request=request)


@router.post("/recommendation-runs", response_model=APIResponse[RecommendationRunView], status_code=status.HTTP_202_ACCEPTED)
def create_recommendation_run(
    payload: CreateRecommendationRunRequest,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key", max_length=255),
    current: ProductCurrentUser = Depends(get_product_user),
    db: Session = Depends(get_db),
):
    service = ProductRecommendationService(db)
    run = service.create_recommendation_run(current, payload, idempotency_key)
    return make_response(service.run_view(run), request=request)


@router.get("/recommendation-runs/{run_id}", response_model=APIResponse[RecommendationRunView])
def get_recommendation_run(
    run_id: str,
    request: Request,
    current: ProductCurrentUser = Depends(get_product_user),
    db: Session = Depends(get_db),
):
    service = ProductRecommendationService(db)
    return make_response(service.run_view(service.get_run(current, run_id)), request=request)


@router.get("/recommendation-runs/{run_id}/results", response_model=APIResponse[RecommendationMatchPage])
def get_recommendation_results(
    run_id: str,
    request: Request,
    cursor: str | None = None,
    limit: int = Query(default=20, ge=1, le=50),
    current: ProductCurrentUser = Depends(get_product_user),
    db: Session = Depends(get_db),
):
    return make_response(ProductRecommendationService(db).results(current, run_id, cursor, limit), request=request)
