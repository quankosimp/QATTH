import hashlib
import re
from uuid import uuid4

import redis
import structlog
from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response
from structlog.contextvars import bind_contextvars, clear_contextvars

from app.core.config import get_settings

_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
logger = structlog.get_logger(__name__)


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        incoming = request.headers.get("X-Request-ID")
        request_id = (
            incoming
            if incoming and _REQUEST_ID_PATTERN.fullmatch(incoming)
            else str(uuid4())
        )
        request.state.request_id = request_id
        clear_contextvars()
        bind_contextvars(
            request_id=request_id,
            method=request.method,
            path=request.url.path,
        )
        try:
            response = await call_next(request)
            response.headers["X-Request-ID"] = request_id
            return response
        finally:
            clear_contextvars()


class DistributedRateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app) -> None:
        super().__init__(app)
        settings = get_settings()
        self.enabled = settings.rate_limit_enabled
        self.limit = settings.rate_limit_requests_per_minute
        self.prefix = settings.redis_key_prefix
        self.fail_closed = settings.app_env in {"staging", "production"}
        self.client = redis.Redis.from_url(
            settings.redis_url,
            decode_responses=True,
            socket_connect_timeout=1,
            socket_timeout=1,
        )

    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        if not self.enabled or request.url.path.startswith(("/health/", "/metrics")):
            return await call_next(request)

        request_id = getattr(request.state, "request_id", "unknown")
        identifier = self._identifier(request)
        key = f"{self.prefix}:rate:{identifier}:{request.url.path}"
        try:
            current = int(self.client.incr(key))
            if current == 1:
                self.client.expire(key, 60)
            ttl = max(int(self.client.ttl(key)), 1)
        except redis.RedisError as exc:
            logger.warning("rate_limit_redis_unavailable", error_type=type(exc).__name__)
            if not self.fail_closed:
                return await call_next(request)
            return JSONResponse(
                status_code=503,
                headers={"X-Request-ID": request_id, "Retry-After": "5"},
                content={
                    "data": None,
                    "error": {
                        "code": "RATE_LIMIT_UNAVAILABLE",
                        "message": "Request admission is temporarily unavailable.",
                        "details": None,
                        "retryable": True,
                    },
                    "meta": {"request_id": request_id, "version": "v1"},
                },
            )

        if current > self.limit:
            return JSONResponse(
                status_code=429,
                headers={
                    "X-Request-ID": request_id,
                    "Retry-After": str(ttl),
                    "X-RateLimit-Limit": str(self.limit),
                    "X-RateLimit-Remaining": "0",
                },
                content={
                    "data": None,
                    "error": {
                        "code": "RATE_LIMITED",
                        "message": "Too many requests.",
                        "details": {"retry_after_seconds": ttl},
                        "retryable": True,
                    },
                    "meta": {"request_id": request_id, "version": "v1"},
                },
            )

        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(self.limit)
        response.headers["X-RateLimit-Remaining"] = str(max(self.limit - current, 0))
        return response

    @staticmethod
    def _identifier(request: Request) -> str:
        authorization = request.headers.get("authorization")
        if authorization:
            return hashlib.sha256(authorization.encode("utf-8")).hexdigest()[:24]
        client_host = request.client.host if request.client else "unknown"
        return hashlib.sha256(client_host.encode("utf-8")).hexdigest()[:24]
