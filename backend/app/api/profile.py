from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import CurrentUser, get_current_user
from app.schemas.common import APIResponse, make_response
from app.schemas.profile import (
    ConsentPayload,
    ConsentRead,
    DeleteMyDataResult,
    JobInteractionPayload,
    JobInteractionRead,
    JobPreferencePayload,
    JobPreferenceRead,
)
from app.services.profile import ProfileService

router = APIRouter(tags=["profile"])


@router.get("/preferences/jobs", response_model=APIResponse[JobPreferenceRead])
def get_job_preferences(
    request: Request,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> APIResponse[JobPreferenceRead]:
    result = ProfileService(db=db, current_user=current_user).get_preferences()
    return make_response(result, request=request)


@router.put("/preferences/jobs", response_model=APIResponse[JobPreferenceRead])
def save_job_preferences(
    request: Request,
    payload: JobPreferencePayload,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> APIResponse[JobPreferenceRead]:
    result = ProfileService(db=db, current_user=current_user).save_preferences(payload)
    return make_response(result, request=request)


@router.post("/jobs/{job_id}/interactions", response_model=APIResponse[JobInteractionRead])
def record_job_interaction(
    request: Request,
    job_id: str,
    payload: JobInteractionPayload,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> APIResponse[JobInteractionRead]:
    result = ProfileService(db=db, current_user=current_user).record_job_interaction(
        job_id=job_id,
        payload=payload,
    )
    return make_response(result, request=request)


@router.get("/jobs/interactions", response_model=APIResponse[list[JobInteractionRead]])
def list_job_interactions(
    request: Request,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> APIResponse[list[JobInteractionRead]]:
    result = ProfileService(db=db, current_user=current_user).list_job_interactions()
    return make_response(result, request=request)


@router.post("/privacy/consents", response_model=APIResponse[ConsentRead])
def record_consent(
    request: Request,
    payload: ConsentPayload,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> APIResponse[ConsentRead]:
    result = ProfileService(db=db, current_user=current_user).record_consent(payload)
    return make_response(result, request=request)


@router.get("/privacy/consents", response_model=APIResponse[list[ConsentRead]])
def list_consents(
    request: Request,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> APIResponse[list[ConsentRead]]:
    result = ProfileService(db=db, current_user=current_user).list_consents()
    return make_response(result, request=request)


@router.delete("/privacy/me/data", response_model=APIResponse[DeleteMyDataResult])
def delete_my_data(
    request: Request,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> APIResponse[DeleteMyDataResult]:
    result = ProfileService(db=db, current_user=current_user).delete_my_data()
    return make_response(result, request=request)
