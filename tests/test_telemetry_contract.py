from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.core import telemetry
from app.core.config import Settings


ROOT = Path(__file__).resolve().parents[1]


def test_disabled_telemetry_is_a_dependency_free_noop(monkeypatch) -> None:
    monkeypatch.setattr(telemetry, "get_settings", lambda: SimpleNamespace(otel_enabled=False))

    assert telemetry.configure_telemetry(service_role="test") is None


def test_telemetry_configuration_rejects_unsafe_values() -> None:
    with pytest.raises(ValidationError, match="TRACE_SAMPLE_RATIO"):
        Settings(_env_file=None, trace_sample_ratio=1.1)
    with pytest.raises(ValidationError, match="OTEL_EXPORTER_OTLP_ENDPOINT"):
        Settings(_env_file=None, otel_enabled=True, otel_exporter_otlp_endpoint="collector:4318")


def test_otlp_trace_endpoint_is_canonical() -> None:
    assert telemetry._trace_endpoint("https://collector.example") == "https://collector.example/v1/traces"
    assert telemetry._trace_endpoint("https://collector.example/v1/traces") == "https://collector.example/v1/traces"


def test_enabled_telemetry_bootstraps_and_shuts_down_in_isolated_runtime() -> None:
    script = """
from types import SimpleNamespace
from fastapi import FastAPI
from app.core import telemetry

telemetry.get_settings = lambda: SimpleNamespace(
    otel_enabled=True,
    otel_service_name="qatth-test",
    otel_exporter_otlp_endpoint="http://127.0.0.1:4318",
    trace_sample_ratio=0.0,
    app_env="test",
)
app = FastAPI()
provider = telemetry.configure_telemetry(app=app, service_role="test")
assert provider is not None
assert app.state.otel_instrumented is True
telemetry.shutdown_telemetry()
"""
    subprocess.run(
        [sys.executable, "-c", script],
        cwd=ROOT,
        env={"PYTHONPATH": str(ROOT / "backend")},
        check=True,
        capture_output=True,
        text=True,
    )


def test_runtime_instruments_required_boundaries_without_sensitive_payloads() -> None:
    telemetry_source = (ROOT / "backend/app/core/telemetry.py").read_text()
    provider_source = (ROOT / "backend/app/core/provider_resilience.py").read_text()
    celery_source = (ROOT / "backend/app/core/celery_app.py").read_text()
    logging_source = (ROOT / "backend/app/core/logging.py").read_text()

    for contract in (
        "FastAPIInstrumentor.instrument_app",
        "SQLAlchemyInstrumentor().instrument",
        "CeleryInstrumentor().instrument",
        "BatchSpanProcessor",
        "ParentBased(TraceIdRatioBased",
        'span.set_attribute("url.query", "[REDACTED]")',
    ):
        assert contract in telemetry_source
    assert "instrument_celery()" in celery_source
    assert '"provider.call"' in provider_source
    assert "record_exception=False" in provider_source
    assert "trace_id" in logging_source and "span_id" in logging_source
    for sensitive in ("cv_text", "transcript", "email", "authorization"):
        assert sensitive not in telemetry_source.casefold()
