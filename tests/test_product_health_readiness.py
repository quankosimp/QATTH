import json
from types import SimpleNamespace

import pytest
from fastapi import Request

from app.api.v1 import health


class FakeSession:
    def __init__(self, revision: str) -> None:
        self.revision = revision

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None

    def execute(self, _query) -> None:
        return None

    def scalar(self, _query) -> str:
        return self.revision


def _request() -> Request:
    request = Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "GET",
            "scheme": "https",
            "path": "/health/ready",
            "raw_path": b"/health/ready",
            "query_string": b"",
            "headers": [],
            "client": ("127.0.0.1", 12345),
            "server": ("testserver", 443),
        }
    )
    request.state.request_id = "health-request"
    return request


def _settings():
    return SimpleNamespace(
        app_env="production",
        app_version="test",
        rate_limit_enabled=True,
        redis_url="rediss://redis/0",
        celery_broker_url="rediss://broker/0",
        celery_result_backend="rediss://result/0",
        clamav_host="clamav",
        clamav_port=3310,
        clamav_timeout_seconds=1,
    )


def _configure(monkeypatch, *, revision: str = health.REQUIRED_DATABASE_REVISION) -> None:
    monkeypatch.setattr(health, "get_settings", _settings)
    monkeypatch.setattr(health, "SessionLocal", lambda: FakeSession(revision))
    monkeypatch.setattr(health, "_redis_available", lambda _url: True)
    monkeypatch.setattr(health, "_malware_scanner_available", lambda: True)
    monkeypatch.setattr(
        health,
        "ObjectStorage",
        lambda: SimpleNamespace(check_available=lambda: True),
    )


def test_readiness_accepts_traffic_only_when_mandatory_dependencies_are_ready(monkeypatch) -> None:
    _configure(monkeypatch)

    response = health.readiness(_request())
    body = json.loads(response.body)

    assert response.status_code == 200
    assert body["status"] == "ok"
    assert body["checks"] == {
        "database": "ok",
        "schema": "ok",
        "redis": "ok",
        "queue": "ok",
        "object_storage": "ok",
        "malware_scanner": "ok",
    }


def test_readiness_rejects_incompatible_database_schema(monkeypatch) -> None:
    _configure(monkeypatch, revision="20260715_0028")

    response = health.readiness(_request())

    assert response.status_code == 503
    assert json.loads(response.body)["checks"]["schema"] == "incompatible"


def test_startup_rejects_incompatible_database_schema(monkeypatch) -> None:
    _configure(monkeypatch, revision="20260715_0028")

    with pytest.raises(RuntimeError, match="Database schema revision is incompatible"):
        health.assert_database_schema_compatible()
