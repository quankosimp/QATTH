import asyncio
import json

from fastapi import Request
from fastapi.exceptions import RequestValidationError

from app.core import errors
from app.core.errors import AppError, safe_error_code, safe_error_payload


def _request() -> Request:
    request = Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "POST",
            "scheme": "https",
            "path": "/v1/cv-scans",
            "raw_path": b"/v1/cv-scans",
            "query_string": b"",
            "headers": [],
            "client": ("127.0.0.1", 12345),
            "server": ("testserver", 443),
        }
    )
    request.state.request_id = "request-1"
    return request


def test_safe_error_payload_never_persists_exception_message() -> None:
    secret = "SECRET CV CONTENT"
    payload = safe_error_payload(
        AppError(503, "PROVIDER_UNAVAILABLE", secret),
        "CV_EXTRACTION_FAILED",
        "CV extraction failed.",
    )

    assert payload == {"code": "PROVIDER_UNAVAILABLE", "message": "CV extraction failed."}
    assert secret not in json.dumps(payload)
    assert safe_error_code(AppError(500, "invalid code", secret), "SAFE_FALLBACK") == "SAFE_FALLBACK"


def test_validation_response_omits_submitted_input() -> None:
    secret = "SECRET ACCESS TOKEN"
    exc = RequestValidationError(
        [
            {
                "type": "string_too_short",
                "loc": ("body", "token"),
                "msg": "String should have at least 20 characters",
                "input": secret,
                "ctx": {"min_length": 20},
            }
        ]
    )

    response = asyncio.run(errors.validation_error_handler(_request(), exc))

    assert secret.encode() not in response.body
    assert b'"input"' not in response.body
    assert b'"ctx"' not in response.body


def test_unhandled_error_log_does_not_serialize_exception_text(monkeypatch) -> None:
    events: list[tuple[str, dict]] = []

    class RecordingLogger:
        def error(self, event: str, **fields) -> None:
            events.append((event, fields))

    secret = "SECRET PROVIDER PAYLOAD"
    monkeypatch.setattr(errors, "logger", RecordingLogger())

    response = asyncio.run(errors.unhandled_error_handler(_request(), RuntimeError(secret)))

    assert response.status_code == 500
    assert secret.encode() not in response.body
    assert secret not in json.dumps(events)
    assert events == [
        (
            "unhandled_request_error",
            {
                "request_id": "request-1",
                "method": "POST",
                "path": "/v1/cv-scans",
                "error_type": "RuntimeError",
            },
        )
    ]
