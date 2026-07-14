import base64
import hashlib
import json
import re
from ipaddress import ip_address, ip_network
from uuid import uuid4

import redis.asyncio as redis
import structlog
from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response
from structlog.contextvars import bind_contextvars, clear_contextvars

from app.core.config import get_settings

_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
_UUID_PATH_PATTERN = re.compile(
    r"(?<=/)[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}(?=/|$)"
)
_AI_COST_PATHS = (
    "/v1/cv-scans",
    "/v1/cv-versions/",
    "/v1/interviews/",
    "/v1/job-search-runs",
    "/v1/recommendation-runs",
)
_RATE_LIMIT_SCRIPT = """
local maximum = 0
local ttl = tonumber(ARGV[2])
for index, key in ipairs(KEYS) do
  local current = redis.call('INCR', key)
  if current == 1 then
    redis.call('EXPIRE', key, tonumber(ARGV[1]))
  end
  if current > maximum then
    maximum = current
  end
  local key_ttl = redis.call('TTL', key)
  if key_ttl > 0 and key_ttl < ttl then
    ttl = key_ttl
  end
end
return {maximum, ttl}
"""
logger = structlog.get_logger(__name__)


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        incoming = request.headers.get("X-Request-ID")
        request_id = incoming if incoming and _REQUEST_ID_PATTERN.fullmatch(incoming) else str(uuid4())
        request.state.request_id = request_id
        clear_contextvars()
        bind_contextvars(request_id=request_id, method=request.method, path=request.url.path)
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
        self.default_limit = settings.rate_limit_requests_per_minute
        self.ai_limit = settings.rate_limit_ai_requests_per_minute
        self.prefix = settings.redis_key_prefix
        self.fail_closed = settings.app_env in {"staging", "production"}
        self.trusted_proxy_networks = tuple(ip_network(cidr, strict=False) for cidr in settings.trusted_proxy_cidrs)
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
        action = self._action_key(request)
        limit = self._limit_for(request)
        ip_identifier = self._hash_identifier(self._client_ip(request))
        keys = [f"{self.prefix}:rate:ip:{ip_identifier}:{action}"]
        principal = self._principal_identifier(request)
        if principal:
            keys.append(f"{self.prefix}:rate:principal:{principal}:{action}")
        try:
            current, ttl = await self.client.eval(_RATE_LIMIT_SCRIPT, len(keys), *keys, 60, 60)
            current = int(current)
            ttl = max(int(ttl), 1)
        except redis.RedisError as exc:
            logger.warning(
                "rate_limit_redis_unavailable",
                error_code="RATE_LIMIT_BACKEND_UNAVAILABLE",
                error_type=type(exc).__name__,
            )
            if not self.fail_closed:
                return await call_next(request)
            return self._error_response(
                request_id,
                503,
                "RATE_LIMIT_UNAVAILABLE",
                "Request admission is temporarily unavailable.",
                5,
            )

        if current > limit:
            return self._error_response(request_id, 429, "RATE_LIMITED", "Too many requests.", ttl, limit)

        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(limit)
        response.headers["X-RateLimit-Remaining"] = str(max(limit - current, 0))
        return response

    @staticmethod
    def _error_response(
        request_id: str,
        status_code: int,
        code: str,
        message: str,
        retry_after: int,
        limit: int | None = None,
    ) -> JSONResponse:
        headers = {"X-Request-ID": request_id, "Retry-After": str(retry_after)}
        if limit is not None:
            headers.update({"X-RateLimit-Limit": str(limit), "X-RateLimit-Remaining": "0"})
        return JSONResponse(
            status_code=status_code,
            headers=headers,
            content={
                "data": None,
                "error": {
                    "code": code,
                    "message": message,
                    "details": {"retry_after_seconds": retry_after},
                    "retryable": True,
                },
                "meta": {"request_id": request_id, "version": "v1"},
            },
        )

    def _client_ip(self, request: Request) -> str:
        peer = request.client.host if request.client else "0.0.0.0"
        try:
            trusted = any(ip_address(peer) in network for network in self.trusted_proxy_networks)
        except ValueError:
            trusted = False
        if trusted:
            forwarded = request.headers.get("CF-Connecting-IP") or request.headers.get("X-Forwarded-For", "").split(",")[0]
            try:
                return str(ip_address(forwarded.strip()))
            except ValueError:
                pass
        try:
            return str(ip_address(peer))
        except ValueError:
            return "0.0.0.0"

    @staticmethod
    def _principal_identifier(request: Request) -> str | None:
        authorization = request.headers.get("authorization")
        if not authorization:
            return None
        token = authorization.removeprefix("Bearer ").strip()
        parts = token.split(".")
        if len(parts) == 3:
            try:
                claims = json.loads(base64.urlsafe_b64decode(parts[1] + "=" * (-len(parts[1]) % 4)))
                subject = str(claims.get("sub") or "")
                if subject:
                    return DistributedRateLimitMiddleware._hash_identifier(subject)
            except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
                pass
        return DistributedRateLimitMiddleware._hash_identifier(token)

    @staticmethod
    def _hash_identifier(value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()[:24]

    @staticmethod
    def _action_key(request: Request) -> str:
        normalized_path = _UUID_PATH_PATTERN.sub("{id}", request.url.path.rstrip("/") or "/")
        return request.method.upper() + ":" + normalized_path

    def _limit_for(self, request: Request) -> int:
        if request.method.upper() in {"POST", "PUT", "PATCH"} and request.url.path.startswith(_AI_COST_PATHS):
            return self.ai_limit
        return self.default_limit
