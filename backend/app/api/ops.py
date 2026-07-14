from fastapi import APIRouter, Depends, Request
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import get_db
from app.core.security import CurrentUser, require_admin
from app.schemas.common import APIResponse, make_response
from app.schemas.ops import LivenessResult, OpsMetrics, ReadinessCheck, ReadinessResult
from app.services.admin import AdminService

router = APIRouter(prefix="/ops", tags=["ops"])


@router.get("/liveness", response_model=APIResponse[LivenessResult])
def liveness(request: Request) -> APIResponse[LivenessResult]:
    settings = get_settings()
    return make_response(
        LivenessResult(alive=True, service=settings.app_name),
        request=request,
    )


@router.get("/readiness", response_model=APIResponse[ReadinessResult])
def readiness(
    request: Request,
    db: Session = Depends(get_db),
) -> APIResponse[ReadinessResult]:
    settings = get_settings()
    checks: list[ReadinessCheck] = []

    try:
        db.execute(text("SELECT 1"))
        checks.append(ReadinessCheck(name="database", ok=True))
    except Exception:
        checks.append(ReadinessCheck(name="database", ok=False, detail="Unavailable"))

    checks.append(
        ReadinessCheck(
            name="upload_dir",
            ok=settings.upload_dir.exists(),
            detail="Available" if settings.upload_dir.exists() else "Missing",
        )
    )
    checks.append(
        ReadinessCheck(
            name="generated_dir",
            ok=settings.generated_dir.exists(),
            detail="Available" if settings.generated_dir.exists() else "Missing",
        )
    )
    checks.append(
        ReadinessCheck(
            name="gemini_api_key",
            ok=bool(settings.gemini_api_key),
            detail="Configured" if settings.gemini_api_key else "Missing; demo fallback mode",
        )
    )

    result = ReadinessResult(ready=all(check.ok for check in checks), checks=checks)
    return make_response(result, request=request)


@router.get("/metrics", response_model=APIResponse[OpsMetrics])
def metrics(
    request: Request,
    db: Session = Depends(get_db),
    _: CurrentUser = Depends(require_admin),
) -> APIResponse[OpsMetrics]:
    overview = AdminService(db=db).overview()
    result = OpsMetrics(**overview.model_dump())
    return make_response(result, request=request)
