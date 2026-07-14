import pytest

from app.core.errors import AppError
from app.core.provider_resilience import ProviderExecutor


class FakeRedis:
    def __init__(self) -> None:
        self.values = {}
        self.hashes = {}

    def incr(self, key):
        self.values[key] = int(self.values.get(key, 0)) + 1
        return self.values[key]

    def decr(self, key):
        self.values[key] = int(self.values.get(key, 0)) - 1
        return self.values[key]

    def expire(self, key, seconds):
        return True

    def get(self, key):
        return self.values.get(key)

    def incrby(self, key, amount):
        self.values[key] = int(self.values.get(key, 0)) + amount
        return self.values[key]

    def delete(self, key):
        self.values.pop(key, None)
        self.hashes.pop(key, None)

    def hgetall(self, key):
        return dict(self.hashes.get(key, {}))

    def hincrby(self, key, field, amount):
        row = self.hashes.setdefault(key, {})
        row[field] = int(row.get(field, 0)) + amount
        return row[field]

    def hset(self, key, mapping):
        self.hashes.setdefault(key, {}).update(mapping)


def executor(redis_client, **overrides):
    return ProviderExecutor(
        redis_client=redis_client,
        retry_attempts=overrides.get("retry_attempts", 3),
        base_delay=0.1,
        max_delay=1,
        failure_threshold=overrides.get("failure_threshold", 2),
        open_seconds=30,
        bulkhead_limit=overrides.get("bulkhead_limit", 2),
        bulkhead_lease_seconds=60,
        sleep=lambda _: None,
        random_uniform=lambda low, high: high,
        wall_clock=lambda: 100.0,
        monotonic=lambda: 1.0,
    )


def test_retryable_provider_error_uses_bounded_retry() -> None:
    attempts = []

    def operation():
        attempts.append(1)
        if len(attempts) < 3:
            raise AppError(503, "TRANSIENT", "temporary", retryable=True)
        return "ok"

    result = executor(FakeRedis()).execute("openai", "cv_analysis", operation)
    assert result.value == "ok"
    assert result.attempts == 3


def test_circuit_opens_after_failure_threshold() -> None:
    policy = executor(FakeRedis(), retry_attempts=1, failure_threshold=2)

    def fail():
        raise AppError(503, "TRANSIENT", "temporary", retryable=True)

    with pytest.raises(AppError):
        policy.execute("openai", "job_search", fail)
    with pytest.raises(AppError):
        policy.execute("openai", "job_search", fail)
    with pytest.raises(AppError) as blocked:
        policy.execute("openai", "job_search", lambda: "not called")
    assert blocked.value.code == "PROVIDER_CIRCUIT_OPEN"


def test_app_error_supports_existing_positional_call_sites() -> None:
    error = AppError(409, "CONFLICT", "conflict")
    assert error.status_code == 409
