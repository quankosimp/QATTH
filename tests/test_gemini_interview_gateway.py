import asyncio
import base64
from types import SimpleNamespace
from uuid import uuid4

import pytest
import redis

from app.core.config import Settings
from app.core.errors import AppError
from app.services.gemini_interview_gateway import (
    GeminiConnectionState,
    GeminiInterviewGateway,
    GeminiSessionLimiter,
)
from app.services.product_interview import ProductInterviewService


def _settings(**overrides) -> Settings:
    return Settings(
        app_env="test",
        redis_key_prefix="qatth:test:" + str(uuid4()),
        gemini_api_key="test-key",
        **overrides,
    )


def _interview(**overrides):
    values = {
        "id": "interview-1",
        "user_id": "user-1",
        "gemini_model": "gemini-3.1-flash-live-preview",
        "gemini_resumption_handle": "resume-handle",
        "plan_snapshot": {"target_role": "Backend Intern"},
        "cv_snapshot": {"content": {"skills": ["Python"]}},
        "job_snapshot": {"title": "Platform Engineer", "skills": ["Kubernetes"]},
        "language": "vi",
        "duration_minutes": 20,
        "started_at": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_setup_enables_long_session_resumption_and_job_grounding() -> None:
    setup = GeminiInterviewGateway(settings=_settings())._setup(_interview())["setup"]

    assert setup["contextWindowCompression"] == {"slidingWindow": {}}
    assert setup["sessionResumption"] == {"handle": "resume-handle"}
    instruction = setup["systemInstruction"]["parts"][0]["text"]
    assert "Platform Engineer" in instruction
    assert "Kubernetes" in instruction
    assert "Vietnamese" in instruction


def test_audio_contract_requires_bounded_16khz_pcm() -> None:
    gateway = GeminiInterviewGateway(
        settings=_settings(gemini_live_audio_chunk_max_bytes=3200)
    )
    gateway._validate_audio(base64.b64encode(b"x" * 3200).decode(), "audio/pcm;rate=16000")

    with pytest.raises(AppError, match="16 kHz"):
        gateway._validate_audio(base64.b64encode(b"x").decode(), "audio/pcm;rate=48000")
    with pytest.raises(AppError) as raised:
        gateway._validate_audio(base64.b64encode(b"x" * 3201).decode(), "audio/pcm;rate=16000")
    assert raised.value.code == "AUDIO_CHUNK_TOO_LARGE"


class _UnavailableRedis:
    def eval(self, *_args):
        raise redis.RedisError("offline")

    def zrem(self, *_args):
        raise redis.RedisError("offline")


def test_session_limiter_enforces_local_fallback_capacity() -> None:
    limiter = GeminiSessionLimiter(
        _settings(gemini_live_session_limit=1),
        redis_client=_UnavailableRedis(),
    )
    first = limiter.acquire()
    with pytest.raises(AppError) as raised:
        limiter.acquire()
    assert raised.value.code == "GEMINI_SESSION_LIMIT_REACHED"
    limiter.release(first)
    limiter.release(limiter.acquire())


def test_session_limiter_fails_closed_without_redis_in_shared_environment() -> None:
    settings = _settings()
    settings.app_env = "staging"
    limiter = GeminiSessionLimiter(settings, redis_client=_UnavailableRedis())

    with pytest.raises(AppError) as raised:
        limiter.acquire()

    assert raised.value.code == "GEMINI_SESSION_COORDINATION_UNAVAILABLE"


class _ProviderMessages:
    def __init__(self, messages):
        self.messages = iter(messages)

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return json_dumps(next(self.messages))
        except StopIteration as exc:
            raise StopAsyncIteration from exc


class _ClientSocket:
    def __init__(self):
        self.sent = []

    async def send_json(self, payload):
        self.sent.append(payload)


def json_dumps(value):
    import json

    return json.dumps(value)


def test_provider_loop_persists_resumption_usage_and_goaway(monkeypatch) -> None:
    gateway = GeminiInterviewGateway(settings=_settings())
    recorded = []
    handles = []

    def record(_interview_id, _direction, event_type, **_kwargs):
        recorded.append(event_type)
        return SimpleNamespace(id="event-" + str(len(recorded)), event_type=event_type)

    monkeypatch.setattr(gateway, "_record", record)
    monkeypatch.setattr(
        ProductInterviewService,
        "update_resumption_handle",
        lambda _service, _interview_id, handle: handles.append(handle),
    )
    state = GeminiConnectionState(connection_id="connection-1")
    client = _ClientSocket()
    provider = _ProviderMessages(
        [
            {
                "sessionResumptionUpdate": {
                    "resumable": True,
                    "newHandle": "new-handle",
                    "lastConsumedClientMessageIndex": 4,
                },
                "usageMetadata": {"promptTokenCount": 10},
            },
            {
                "serverContent": {
                    "outputTranscription": {"text": "Xin chao"},
                    "generationComplete": True,
                    "turnComplete": True,
                },
                "usageMetadata": {"promptTokenCount": 12, "responseTokenCount": 5},
            },
            {"goAway": {"timeLeft": "5s"}},
        ]
    )

    asyncio.run(gateway._provider_loop(client, provider, "interview-1", state))

    assert handles == ["new-handle"]
    assert state.usage["promptTokenCount"] == 12
    assert state.usage["responseTokenCount"] == 5
    assert {"session.resumption", "generation.complete", "turn.complete", "provider.go_away"}.issubset(recorded)
    assert client.sent[-1]["payload"]["time_left"] == "5s"


def test_reconnect_window_is_explicitly_enforced() -> None:
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)
    assert ProductInterviewService._reconnect_expired(
        SimpleNamespace(status="interrupted", reconnect_until=now - timedelta(seconds=1)),
        now,
    )
    assert not ProductInterviewService._reconnect_expired(
        SimpleNamespace(status="interrupted", reconnect_until=now + timedelta(seconds=1)),
        now,
    )
