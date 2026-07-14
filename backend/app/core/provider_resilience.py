from __future__ import annotations

import random
import threading
import time
from dataclasses import dataclass
from functools import lru_cache
from typing import Callable, Generic, TypeVar
from uuid import uuid4

import redis
import structlog
from structlog.contextvars import get_contextvars

from app.core.config import get_settings
from app.core.errors import AppError

try:
    from prometheus_client import Counter, Gauge, Histogram

    PROVIDER_CALLS = Counter(
        "qatth_provider_calls_total",
        "External provider calls by outcome.",
        ["provider", "purpose", "outcome"],
    )
    PROVIDER_LATENCY = Histogram(
        "qatth_provider_call_duration_seconds",
        "External provider call latency.",
        ["provider", "purpose"],
    )
    PROVIDER_IN_FLIGHT = Gauge(
        "qatth_provider_in_flight",
        "Provider calls admitted by the local process.",
        ["provider", "purpose"],
    )
    PROVIDER_CIRCUIT_OPENED = Counter(
        "qatth_provider_circuit_opened_total",
        "Provider circuit breaker transitions to open.",
        ["provider", "purpose"],
    )
except ImportError:  # pragma: no cover - prometheus is optional outside API runtime
    PROVIDER_CALLS = PROVIDER_LATENCY = PROVIDER_IN_FLIGHT = PROVIDER_CIRCUIT_OPENED = None


T = TypeVar("T")
logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class ProviderExecution(Generic[T]):
    value: T
    correlation_id: str
    attempts: int
    latency_ms: int


class ProviderExecutor:
    def __init__(
        self,
        *,
        redis_client=None,
        retry_attempts: int | None = None,
        base_delay: float | None = None,
        max_delay: float | None = None,
        failure_threshold: int | None = None,
        open_seconds: int | None = None,
        bulkhead_limit: int | None = None,
        bulkhead_lease_seconds: int | None = None,
        sleep: Callable[[float], None] = time.sleep,
        random_uniform: Callable[[float, float], float] = random.uniform,
        wall_clock: Callable[[], float] = time.time,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        settings = get_settings()
        self.redis = redis_client or redis.Redis.from_url(
            settings.redis_url,
            decode_responses=True,
            socket_connect_timeout=1,
            socket_timeout=1,
        )
        self.prefix = settings.redis_key_prefix
        self.retry_attempts = retry_attempts or settings.provider_retry_attempts
        self.base_delay = base_delay if base_delay is not None else settings.provider_retry_base_delay_seconds
        self.max_delay = max_delay if max_delay is not None else settings.provider_retry_max_delay_seconds
        self.failure_threshold = failure_threshold or settings.provider_circuit_failure_threshold
        self.open_seconds = open_seconds or settings.provider_circuit_open_seconds
        self.bulkhead_limit = bulkhead_limit or settings.provider_bulkhead_limit
        self.bulkhead_lease_seconds = bulkhead_lease_seconds or settings.provider_bulkhead_lease_seconds
        self.sleep = sleep
        self.random_uniform = random_uniform
        self.wall_clock = wall_clock
        self.monotonic = monotonic
        self._local_lock = threading.Lock()
        self._local_in_flight: dict[str, int] = {}
        self._local_circuits: dict[str, tuple[int, float]] = {}

    def execute(self, provider: str, purpose: str, operation: Callable[[], T]) -> ProviderExecution[T]:
        correlation_id = str(get_contextvars().get("request_id") or uuid4())
        key = provider + ":" + purpose
        self._ensure_circuit_closed(key, provider, purpose)
        lease_backend = self._acquire_bulkhead(key, provider, purpose)
        started = self.monotonic()
        if PROVIDER_IN_FLIGHT:
            PROVIDER_IN_FLIGHT.labels(provider, purpose).inc()
        try:
            for attempt in range(1, self.retry_attempts + 1):
                try:
                    value = operation()
                    self._record_success(key)
                    latency = max(0, int((self.monotonic() - started) * 1000))
                    self._metric(provider, purpose, "success", latency)
                    return ProviderExecution(value, correlation_id, attempt, latency)
                except Exception as exc:
                    retryable = isinstance(exc, AppError) and exc.retryable
                    if not retryable or attempt >= self.retry_attempts:
                        self._record_failure(key, provider, purpose)
                        latency = max(0, int((self.monotonic() - started) * 1000))
                        self._metric(provider, purpose, "failure", latency)
                        raise
                    upper = min(self.max_delay, self.base_delay * (2 ** (attempt - 1)))
                    delay = self.random_uniform(0.0, upper)
                    logger.warning(
                        "provider_call_retry",
                        provider=provider,
                        purpose=purpose,
                        attempt=attempt,
                        delay_seconds=round(delay, 3),
                        error_code=exc.code,
                        request_id=correlation_id,
                    )
                    self.sleep(delay)
            raise RuntimeError("provider retry loop terminated unexpectedly")
        finally:
            if PROVIDER_IN_FLIGHT:
                PROVIDER_IN_FLIGHT.labels(provider, purpose).dec()
            self._release_bulkhead(key, lease_backend)

    def _ensure_circuit_closed(self, key: str, provider: str, purpose: str) -> None:
        redis_key = self._circuit_key(key)
        try:
            state = self.redis.hgetall(redis_key)
            open_until = float(state.get("open_until") or 0)
        except redis.RedisError:
            with self._local_lock:
                _, open_until = self._local_circuits.get(key, (0, 0.0))
        if open_until > self.wall_clock():
            if PROVIDER_CALLS:
                PROVIDER_CALLS.labels(provider, purpose, "circuit_open").inc()
            raise AppError(
                503,
                "PROVIDER_CIRCUIT_OPEN",
                "Provider is temporarily unavailable",
                details={"provider": provider, "purpose": purpose},
                retryable=True,
            )

    def _record_success(self, key: str) -> None:
        try:
            self.redis.delete(self._circuit_key(key))
        except redis.RedisError:
            with self._local_lock:
                self._local_circuits.pop(key, None)

    def _record_failure(self, key: str, provider: str, purpose: str) -> None:
        opened = False
        try:
            failures = int(self.redis.hincrby(self._circuit_key(key), "failures", 1))
            if failures >= self.failure_threshold:
                self.redis.hset(
                    self._circuit_key(key),
                    mapping={"open_until": self.wall_clock() + self.open_seconds},
                )
                opened = True
            self.redis.expire(self._circuit_key(key), self.open_seconds * 2)
        except redis.RedisError:
            with self._local_lock:
                failures, _ = self._local_circuits.get(key, (0, 0.0))
                failures += 1
                open_until = self.wall_clock() + self.open_seconds if failures >= self.failure_threshold else 0.0
                self._local_circuits[key] = (failures, open_until)
                opened = bool(open_until)
        if opened and PROVIDER_CIRCUIT_OPENED:
            PROVIDER_CIRCUIT_OPENED.labels(provider, purpose).inc()

    def _acquire_bulkhead(self, key: str, provider: str, purpose: str) -> str:
        redis_key = self._bulkhead_key(key)
        try:
            current = int(self.redis.incr(redis_key))
            self.redis.expire(redis_key, self.bulkhead_lease_seconds)
            if current <= self.bulkhead_limit:
                return "redis"
            self.redis.decr(redis_key)
        except redis.RedisError:
            with self._local_lock:
                current = self._local_in_flight.get(key, 0)
                if current < self.bulkhead_limit:
                    self._local_in_flight[key] = current + 1
                    return "local"
        if PROVIDER_CALLS:
            PROVIDER_CALLS.labels(provider, purpose, "bulkhead_rejected").inc()
        raise AppError(
            503,
            "PROVIDER_BULKHEAD_FULL",
            "Provider concurrency limit has been reached",
            details={"provider": provider, "purpose": purpose},
            retryable=True,
        )

    def _release_bulkhead(self, key: str, backend: str) -> None:
        if backend == "redis":
            try:
                if int(self.redis.decr(self._bulkhead_key(key))) <= 0:
                    self.redis.delete(self._bulkhead_key(key))
                return
            except redis.RedisError:
                return
        with self._local_lock:
            current = self._local_in_flight.get(key, 0) - 1
            if current <= 0:
                self._local_in_flight.pop(key, None)
            else:
                self._local_in_flight[key] = current

    def _metric(self, provider: str, purpose: str, outcome: str, latency_ms: int) -> None:
        if PROVIDER_CALLS:
            PROVIDER_CALLS.labels(provider, purpose, outcome).inc()
            PROVIDER_LATENCY.labels(provider, purpose).observe(latency_ms / 1000)

    def _circuit_key(self, key: str) -> str:
        return f"{self.prefix}:provider:circuit:{key}"

    def _bulkhead_key(self, key: str) -> str:
        return f"{self.prefix}:provider:bulkhead:{key}"


@lru_cache
def get_provider_executor() -> ProviderExecutor:
    return ProviderExecutor()
