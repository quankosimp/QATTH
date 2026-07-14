from typing import Literal

import redis
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import text

from app.core.config import get_settings
from app.core.db import SessionLocal

router = APIRouter(tags=["Health"])


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded", "unavailable"]
    version: str
    checks: dict[str, str]


def _response(
    request: Request,
    *,
    status: Literal["ok", "degraded", "unavailable"],
    checks: dict[str, str],
    status_code: int,
) -> JSONResponse:
    settings = get_settings()
    body = HealthResponse(
        status=status,
        version=settings.app_version,
        checks=checks,
    )
    return JSONResponse(
        status_code=status_code,
        content=body.model_dump(mode="json"),
        headers={"X-Request-ID": getattr(request.state, "request_id", "unknown")},
    )


@router.get("/health/live", response_model=HealthResponse, operation_id="getLiveness")
def liveness(request: Request) -> JSONResponse:
    return _response(
        request,
        status="ok",
        checks={"process": "ok"},
        status_code=200,
    )


@router.get(
    "/health/ready",
    response_model=HealthResponse,
    responses={503: {"model": HealthResponse}},
    operation_id="getReadiness",
)
def readiness(request: Request) -> JSONResponse:
    settings = get_settings()
    checks: dict[str, str] = {}
    unavailable = False

    try:
        with SessionLocal() as db:
            db.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception:
        checks["database"] = "unavailable"
        unavailable = True

    if settings.rate_limit_enabled:
        try:
            client = redis.Redis.from_url(
                settings.redis_url,
                socket_connect_timeout=1,
                socket_timeout=1,
            )
            client.ping()
            checks["redis"] = "ok"
        except redis.RedisError:
            checks["redis"] = "unavailable"
            unavailable = True
    else:
        checks["redis"] = "disabled"

    return _response(
        request,
        status="unavailable" if unavailable else "ok",
        checks=checks,
        status_code=503 if unavailable else 200,
    )
