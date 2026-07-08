from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import CurrentUser, get_current_user
from app.schemas.common import APIResponse, make_response
from app.schemas.discovery import JobRecommendationRequest, JobRecommendationResult
from app.services.recommendations import RecommendationService

router = APIRouter(prefix="/recommendations", tags=["recommendations"])


@router.post("/jobs", response_model=APIResponse[JobRecommendationResult])
async def recommend_jobs(
    request: Request,
    payload: JobRecommendationRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> APIResponse[JobRecommendationResult]:
    result = await RecommendationService(db=db, current_user=current_user).recommend_jobs(
        discovery_profile_id=payload.discovery_profile_id,
        limit=payload.limit,
        location=payload.location,
        working_model=payload.working_model,
        allow_stored_fallback=payload.allow_stored_fallback,
    )
    return make_response(result, request=request)
