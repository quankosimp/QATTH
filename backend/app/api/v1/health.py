import socket
from typing import Literal

import redis
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import text

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.services.object_storage import ObjectStorage

router = APIRouter(tags=["Health"])
REQUIRED_DATABASE_REVISION = "20260715_0032"


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


def _redis_available(url: str) -> bool:
    try:
        client = redis.Redis.from_url(url, socket_connect_timeout=1, socket_timeout=1)
        return bool(client.ping())
    except Exception:
        return False


def _malware_scanner_available() -> bool:
    settings = get_settings()
    if not settings.clamav_host:
        return False
    try:
        with socket.create_connection(
            (settings.clamav_host, settings.clamav_port),
            timeout=min(float(settings.clamav_timeout_seconds), 1.0),
        ) as client:
            client.sendall(b"zPING\0")
            return b"PONG" in client.recv(64)
    except OSError:
        return False


def assert_database_schema_compatible() -> None:
    settings = get_settings()
    if settings.app_env not in {"staging", "production"}:
        return
    try:
        with SessionLocal() as db:
            revision = db.scalar(text("SELECT version_num FROM alembic_version"))
    except Exception as exc:
        raise RuntimeError("Database schema compatibility check failed") from exc
    if revision != REQUIRED_DATABASE_REVISION:
        raise RuntimeError(
            f"Database schema revision is incompatible: expected {REQUIRED_DATABASE_REVISION}, got {revision or 'missing'}"
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
    strict = settings.app_env in {"staging", "production"}

    try:
        with SessionLocal() as db:
            db.execute(text("SELECT 1"))
            revision = db.scalar(text("SELECT version_num FROM alembic_version")) if strict else None
        checks["database"] = "ok"
        if strict:
            checks["schema"] = "ok" if revision == REQUIRED_DATABASE_REVISION else "incompatible"
            unavailable = unavailable or revision != REQUIRED_DATABASE_REVISION
        else:
            checks["schema"] = "not_required"
    except Exception:
        checks["database"] = "unavailable"
        checks["schema"] = "unavailable" if strict else "not_required"
        unavailable = True

    if settings.rate_limit_enabled or strict:
        redis_ok = _redis_available(settings.redis_url)
        checks["redis"] = "ok" if redis_ok else "unavailable"
        unavailable = unavailable or not redis_ok
    else:
        checks["redis"] = "disabled"

    if strict:
        queue_ok = all(
            _redis_available(url)
            for url in {settings.celery_broker_url, settings.celery_result_backend}
        )
        checks["queue"] = "ok" if queue_ok else "unavailable"
        unavailable = unavailable or not queue_ok
    else:
        checks["queue"] = "not_required"

    try:
        storage_ok = ObjectStorage().check_available()
    except Exception:
        storage_ok = False
    checks["object_storage"] = "ok" if storage_ok else "unavailable"
    unavailable = unavailable or not storage_ok

    if settings.clamav_host:
        malware_ok = _malware_scanner_available()
        checks["malware_scanner"] = "ok" if malware_ok else "unavailable"
        unavailable = unavailable or not malware_ok
    elif strict:
        checks["malware_scanner"] = "unavailable"
        unavailable = True
    else:
        checks["malware_scanner"] = "disabled"

    return _response(
        request,
        status="unavailable" if unavailable else "ok",
        checks=checks,
        status_code=503 if unavailable else 200,
    )
