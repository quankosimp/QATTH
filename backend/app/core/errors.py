from typing import Any

import structlog
from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.schemas.common import APIResponse, ErrorDetail, Meta

logger = structlog.get_logger(__name__)


class AppError(Exception):
    def __init__(
        self,
        *,
        status_code: int,
        code: str,
        message: str,
        details: dict[str, Any] | None = None,
        retryable: bool = False,
    ) -> None:
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details
        self.retryable = retryable


def _request_id(request: Request) -> str:
    return getattr(request.state, "request_id", "unknown")


def _error_response(
    *,
    request: Request,
    status_code: int,
    code: str,
    message: str,
    details: dict[str, Any] | None = None,
    retryable: bool = False,
) -> JSONResponse:
    body = APIResponse(
        data=None,
        error=ErrorDetail(
            code=code,
            message=message,
            details=details,
            retryable=retryable,
        ),
        meta=Meta(request_id=_request_id(request)),
    )
    return JSONResponse(
        status_code=status_code,
        content=body.model_dump(mode="json"),
        headers={"X-Request-ID": _request_id(request)},
    )


async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    return _error_response(
        request=request,
        status_code=exc.status_code,
        code=exc.code,
        message=exc.message,
        details=exc.details,
        retryable=exc.retryable,
    )


async def validation_error_handler(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    return _error_response(
        request=request,
        status_code=422,
        code="VALIDATION_ERROR",
        message="Request validation failed.",
        details={"errors": exc.errors()},
    )


async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception(
        "unhandled_request_error",
        request_id=_request_id(request),
        method=request.method,
        path=request.url.path,
        error_type=type(exc).__name__,
    )
    return _error_response(
        request=request,
        status_code=500,
        code="INTERNAL_ERROR",
        message="An unexpected error occurred.",
        retryable=False,
    )
