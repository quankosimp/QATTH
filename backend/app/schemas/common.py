from typing import Any, Generic, TypeVar

from fastapi import Request
from pydantic import BaseModel

T = TypeVar("T")


class ErrorDetail(BaseModel):
    code: str
    message: str
    details: dict[str, Any] | None = None


class Meta(BaseModel):
    request_id: str
    version: str = "v1"


class APIResponse(BaseModel, Generic[T]):
    data: T | None
    error: ErrorDetail | None = None
    meta: Meta


def make_response(data: T, *, request: Request, version: str = "v1") -> APIResponse[T]:
    request_id = getattr(request.state, "request_id", "unknown")
    return APIResponse(data=data, error=None, meta=Meta(request_id=request_id, version=version))
