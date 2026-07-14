from uuid import uuid4

from structlog.contextvars import get_contextvars


def current_correlation_id() -> str:
    return str(get_contextvars().get("request_id") or uuid4())
