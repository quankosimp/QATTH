import asyncio
import base64
import json
from types import SimpleNamespace

import redis.asyncio as redis
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import Response

import app.core.middleware as middleware_module
from app.core.middleware import DistributedRateLimitMiddleware


class FakeRedis:
    def __init__(self, fail: bool = False) -> None:
        self.counts: dict[str, int] = {}
        self.keys: list[str] = []
        self.fail = fail

    async def eval(self, _script, number_of_keys, *args):
        if self.fail:
            raise redis.RedisError("unavailable")
        keys = list(args[:number_of_keys])
        self.keys.extend(keys)
        current = 0
        for key in keys:
            self.counts[key] = self.counts.get(key, 0) + 1
            current = max(current, self.counts[key])
        return [current, 60]


def _request(path: str, token: str | None = None) -> Request:
    headers = [(b"cf-connecting-ip", b"203.0.113.9")]
    if token:
        headers.append((b"authorization", ("Bearer " + token).encode()))
    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "POST",
            "scheme": "https",
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "headers": headers,
            "client": ("10.1.2.3", 12345),
            "server": ("api.example", 443),
        }
    )


def _token(subject: str) -> str:
    payload = base64.urlsafe_b64encode(json.dumps({"sub": subject}).encode()).decode().rstrip("=")
    return "header." + payload + ".signature"


def _middleware(monkeypatch, client: FakeRedis, environment: str = "production"):
    settings = SimpleNamespace(
        rate_limit_enabled=True,
        rate_limit_requests_per_minute=2,
        rate_limit_ai_requests_per_minute=1,
        redis_key_prefix="qatth:test",
        app_env=environment,
        trusted_proxy_cidrs=["10.0.0.0/8"],
        redis_url="rediss://redis.example/0",
    )
    monkeypatch.setattr(middleware_module, "get_settings", lambda: settings)
    monkeypatch.setattr(middleware_module.redis.Redis, "from_url", lambda *args, **kwargs: client)
    return DistributedRateLimitMiddleware(Starlette())


def test_rate_limit_uses_ip_and_principal_buckets_with_normalized_action(monkeypatch) -> None:
    client = FakeRedis()
    limiter = _middleware(monkeypatch, client)
    path = "/v1/cv-versions/123e4567-e89b-12d3-a456-426614174000/analyses"
    request = _request(path, _token("user-1"))

    async def call_next(_request):
        return Response(status_code=200)

    first = asyncio.run(limiter.dispatch(request, call_next))
    second = asyncio.run(limiter.dispatch(_request(path, _token("user-1")), call_next))
    assert first.status_code == 200
    assert second.status_code == 429
    assert any(":rate:ip:" in key for key in client.keys)
    assert any(":rate:principal:" in key for key in client.keys)
    assert all("123e4567-e89b-12d3-a456-426614174000" not in key for key in client.keys)
    assert all("POST:/v1/cv-versions/{id}/analyses" in key for key in client.keys)


def test_rate_limit_fails_closed_when_redis_is_unavailable(monkeypatch) -> None:
    limiter = _middleware(monkeypatch, FakeRedis(fail=True))

    async def call_next(_request):
        return Response(status_code=200)

    response = asyncio.run(limiter.dispatch(_request("/v1/job-search-runs"), call_next))
    assert response.status_code == 503
    assert response.headers["Retry-After"] == "5"
