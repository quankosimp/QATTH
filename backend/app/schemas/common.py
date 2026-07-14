from typing import Any, Generic, TypeVar

from fastapi import Request
from pydantic import BaseModel, Field

T = TypeVar("T")


class ErrorDetail(BaseModel):
    code: str
    message: str
    details: dict[str, Any] | None = None
    retryable: bool = False


class Meta(BaseModel):
    request_id: str
    version: str = "v1"
    next_cursor: str | None = None
    has_more: bool | None = None


class APIResponse(BaseModel, Generic[T]):
    data: T | None
    error: ErrorDetail | None = None
    meta: Meta


class CursorPage(BaseModel, Generic[T]):
    items: list[T] = Field(default_factory=list)
    next_cursor: str | None = None


def make_response(
    data: T,
    *,
    request: Request,
    version: str = "v1",
    next_cursor: str | None = None,
    has_more: bool | None = None,
) -> APIResponse[T]:
    request_id = getattr(request.state, "request_id", "unknown")
    return APIResponse(
        data=data,
        error=None,
        meta=Meta(
            request_id=request_id,
            version=version,
            next_cursor=next_cursor,
            has_more=has_more,
        ),
    )
