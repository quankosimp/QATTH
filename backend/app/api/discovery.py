from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import CurrentUser, get_current_user
from app.schemas.common import APIResponse, make_response
from app.schemas.discovery import (
    CandidateDiscoveryProfileList,
    CandidateDiscoveryProfileRead,
    DiscoveryProfileCreateRequest,
)
from app.services.discovery import DiscoveryService

router = APIRouter(prefix="/discovery-profiles", tags=["discovery-profiles"])


@router.post("", response_model=APIResponse[CandidateDiscoveryProfileRead])
async def create_discovery_profile(
    request: Request,
    payload: DiscoveryProfileCreateRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> APIResponse[CandidateDiscoveryProfileRead]:
    result = await DiscoveryService(db=db, current_user=current_user).create(
        cv_id=payload.cv_id,
        interview_id=payload.interview_id,
        language=payload.language,
    )
    return make_response(result, request=request)


@router.get("", response_model=APIResponse[CandidateDiscoveryProfileList])
def list_discovery_profiles(
    request: Request,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> APIResponse[CandidateDiscoveryProfileList]:
    result = DiscoveryService(db=db, current_user=current_user).list()
    return make_response(result, request=request)


@router.get("/{profile_id}", response_model=APIResponse[CandidateDiscoveryProfileRead])
def get_discovery_profile(
    request: Request,
    profile_id: str,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> APIResponse[CandidateDiscoveryProfileRead]:
    result = DiscoveryService(db=db, current_user=current_user).get(profile_id=profile_id)
    return make_response(result, request=request)
