from datetime import UTC, datetime

from fastapi import APIRouter, Request
from pydantic import BaseModel

from app.schemas.common import APIResponse, make_response

router = APIRouter()


class HealthCheck(BaseModel):
    status: str
    service: str
    checked_at: datetime


@router.get("/health", response_model=APIResponse[HealthCheck])
def health(request: Request) -> APIResponse[HealthCheck]:
    return make_response(
        HealthCheck(
            status="ok",
            service="qatth-career-api",
            checked_at=datetime.now(UTC),
        ),
        request=request,
    )
