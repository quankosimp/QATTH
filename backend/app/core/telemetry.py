from __future__ import annotations

import threading
from typing import Any

from app.core.config import get_settings

_lock = threading.Lock()
_provider = None
_base_instrumented = False
_celery_instrumented = False


def _trace_endpoint(endpoint: str) -> str:
    normalized = endpoint.rstrip("/")
    return normalized if normalized.endswith("/v1/traces") else normalized + "/v1/traces"


def _sanitize_server_span(span: Any, scope: dict[str, Any]) -> None:
    if span is None or not span.is_recording():
        return
    path = str(scope.get("path") or "/")
    span.set_attribute("url.path", path)
    span.set_attribute("url.full", path)
    span.set_attribute("http.target", path)
    if scope.get("query_string"):
        span.set_attribute("url.query", "[REDACTED]")


def configure_telemetry(*, app=None, service_role: str) -> Any | None:
    global _base_instrumented, _provider

    settings = get_settings()
    if not settings.otel_enabled:
        return None

    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
        from opentelemetry.sdk.resources import SERVICE_NAME, Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.sdk.trace.sampling import ParentBased, TraceIdRatioBased
    except ImportError as exc:  # pragma: no cover - production image contract
        raise RuntimeError("OpenTelemetry runtime dependencies are not installed") from exc

    with _lock:
        if _provider is None:
            resource = Resource.create(
                {
                    SERVICE_NAME: settings.otel_service_name,
                    "service.namespace": "qatth",
                    "deployment.environment.name": settings.app_env,
                    "qatth.runtime.role": service_role,
                }
            )
            _provider = TracerProvider(
                resource=resource,
                sampler=ParentBased(TraceIdRatioBased(settings.trace_sample_ratio)),
            )
            _provider.add_span_processor(
                BatchSpanProcessor(
                    OTLPSpanExporter(endpoint=_trace_endpoint(settings.otel_exporter_otlp_endpoint))
                )
            )
            trace.set_tracer_provider(_provider)

        if not _base_instrumented:
            from app.core.db import engine

            SQLAlchemyInstrumentor().instrument(
                engine=engine,
                tracer_provider=_provider,
                enable_commenter=False,
            )
            _base_instrumented = True

        if app is not None and not getattr(app.state, "otel_instrumented", False):
            FastAPIInstrumentor.instrument_app(
                app,
                tracer_provider=_provider,
                excluded_urls="/health/live,/metrics",
                server_request_hook=_sanitize_server_span,
            )
            app.state.otel_instrumented = True

        return _provider


def instrument_celery() -> None:
    global _celery_instrumented

    provider = configure_telemetry(service_role="worker")
    if provider is None:
        return
    with _lock:
        if _celery_instrumented:
            return
        try:
            from opentelemetry.instrumentation.celery import CeleryInstrumentor
        except ImportError as exc:  # pragma: no cover - production image contract
            raise RuntimeError("OpenTelemetry Celery instrumentation is not installed") from exc
        CeleryInstrumentor().instrument(tracer_provider=provider)
        _celery_instrumented = True


def shutdown_telemetry() -> None:
    if _provider is not None:
        _provider.force_flush()
        _provider.shutdown()
