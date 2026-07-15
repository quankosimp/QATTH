import pytest

from app.core.errors import AppError
from app.core.provider_resilience import ProviderExecutor
from app.services.openai_cv import CvAnalysisOutput, OpenAICvAdapter
from app.services.openai_jobs import OpenAIJobsAdapter


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


def test_cv_schema_validation_is_inside_bounded_provider_retry() -> None:
    adapter = object.__new__(OpenAICvAdapter)
    responses = [
        {"data": {"scores": {"clarity": "invalid"}, "findings": []}},
        {"data": {"scores": {"clarity": 80}, "findings": []}},
    ]
    adapter._request = lambda **_: responses.pop(0)  # type: ignore[method-assign]

    result = executor(FakeRedis(), retry_attempts=2).execute(
        "openai",
        "cv_analysis",
        lambda: adapter._validated_request(CvAnalysisOutput, name="test", schema={}, content=[]),
    )

    assert result.attempts == 2
    assert result.value["data"]["scores"]["clarity"] == 80


def test_job_schema_validation_is_inside_bounded_provider_retry() -> None:
    adapter = object.__new__(OpenAIJobsAdapter)
    responses = [
        {
            "status": "completed",
            "output": [{"type": "message", "content": [{"type": "output_text", "text": '{"jobs":[{"title":"incomplete"}]}'}]}],
        },
        {
            "status": "completed",
            "output": [
                {"type": "web_search_call", "status": "completed", "id": "search-1", "action": {"type": "search", "sources": []}},
                {"type": "message", "content": [{"type": "output_text", "text": '{"jobs":[]}', "annotations": []}]},
            ],
        },
    ]

    def operation():
        raw = responses.pop(0)
        adapter._validate_live_response(raw)
        return raw

    result = executor(FakeRedis(), retry_attempts=2).execute("openai", "job_search", operation)
    assert result.attempts == 2


def test_job_explanation_requires_typed_schema() -> None:
    adapter = object.__new__(OpenAIJobsAdapter)
    invalid = {"output": [{"type": "message", "content": [{"type": "output_text", "text": '{"reasons":"invalid","gaps":[]}'}]}]}
    with pytest.raises(AppError) as raised:
        adapter._validate_explanation_response(invalid)
    assert raised.value.code == "EXPLANATION_RESPONSE_INVALID"
    assert raised.value.retryable is True
