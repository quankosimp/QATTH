import json
from types import SimpleNamespace

import structlog
from structlog.contextvars import bind_contextvars, clear_contextvars

from app.core import logging as product_logging


def test_structured_log_contains_runtime_correlation_and_safe_error_code(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        product_logging,
        "get_settings",
        lambda: SimpleNamespace(log_level="INFO", app_name="qatth-test", app_env="test"),
    )
    product_logging.configure_logging()
    clear_contextvars()
    bind_contextvars(request_id="request-structured-log")

    structlog.get_logger("test").warning(
        "dependency_unavailable",
        error_code="DEPENDENCY_UNAVAILABLE",
        error_type="TimeoutError",
    )

    clear_contextvars()
    record = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert record == {
        "environment": "test",
        "error_code": "DEPENDENCY_UNAVAILABLE",
        "error_type": "TimeoutError",
        "event": "dependency_unavailable",
        "level": "warning",
        "request_id": "request-structured-log",
        "service": "qatth-test",
        "severity": "WARNING",
        "timestamp": record["timestamp"],
    }
