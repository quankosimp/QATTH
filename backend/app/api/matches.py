from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.schemas.common import APIResponse, make_response
from app.schemas.matching import MatchCreateRequest, MatchRunResult
from app.services.matching import MatchingService

router = APIRouter(prefix="/matches", tags=["matches"])


@router.post("", response_model=APIResponse[MatchRunResult])
def create_match(
    request: Request,
    payload: MatchCreateRequest,
    db: Session = Depends(get_db),
) -> APIResponse[MatchRunResult]:
    result = MatchingService(db=db).create_match(
        cv_id=payload.cv_id,
        interview_id=payload.interview_id,
        limit=payload.limit,
        location=payload.location,
        working_model=payload.working_model,
    )
    return make_response(result, request=request)


@router.get("/{match_id}", response_model=APIResponse[MatchRunResult])
def get_match(
    request: Request,
    match_id: str,
    db: Session = Depends(get_db),
) -> APIResponse[MatchRunResult]:
    result = MatchingService(db=db).get_match(match_id=match_id)
    return make_response(result, request=request)
