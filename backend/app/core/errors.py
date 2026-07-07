from typing import Any

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.schemas.common import APIResponse, ErrorDetail, Meta


class AppError(Exception):
    def __init__(
        self,
        *,
        status_code: int,
        code: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details


def _request_id(request: Request) -> str:
    return getattr(request.state, "request_id", "unknown")


async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    body = APIResponse(
        data=None,
        error=ErrorDetail(code=exc.code, message=exc.message, details=exc.details),
        meta=Meta(request_id=_request_id(request)),
    )
    return JSONResponse(status_code=exc.status_code, content=body.model_dump(mode="json"))


async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    body = APIResponse(
        data=None,
        error=ErrorDetail(
            code="VALIDATION_ERROR",
            message="Request validation failed.",
            details={"errors": exc.errors()},
        ),
        meta=Meta(request_id=_request_id(request)),
    )
    return JSONResponse(status_code=422, content=body.model_dump(mode="json"))
