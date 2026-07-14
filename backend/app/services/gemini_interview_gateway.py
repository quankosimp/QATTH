from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
import json
import secrets
import threading
import time
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import quote

import redis
import websockets
from fastapi import WebSocket
from pydantic import ValidationError

from app.core.config import Settings, get_settings
from app.core.db import SessionLocal
from app.core.errors import AppError
from app.models.product_interview import ProductInterview
from app.schemas.product_interview import RealtimeClientEvent
from app.services.product_interview import ProductInterviewService
from app.services.provider_usage import ProviderUsageService


@dataclass(frozen=True)
class GeminiSessionLease:
    token: str
    backend: str


class GeminiSessionLimiter:
    _local_lock = threading.Lock()
    _local_leases: dict[str, dict[str, float]] = {}
    _acquire_script = """
local key, now, expires, limit, token = KEYS[1], tonumber(ARGV[1]), tonumber(ARGV[2]), tonumber(ARGV[3]), ARGV[4]
redis.call('ZREMRANGEBYSCORE', key, '-inf', now)
if redis.call('ZCARD', key) >= limit then return 0 end
redis.call('ZADD', key, expires, token)
redis.call('EXPIRE', key, math.ceil(expires - now))
return 1
"""
    _refresh_script = """
local key, expires, ttl, token = KEYS[1], tonumber(ARGV[1]), tonumber(ARGV[2]), ARGV[3]
if not redis.call('ZSCORE', key, token) then return 0 end
redis.call('ZADD', key, expires, token)
redis.call('EXPIRE', key, ttl)
return 1
"""

    def __init__(
        self,
        settings: Settings,
        redis_client=None,
        clock=time.time,
    ) -> None:
        self.settings = settings
        self.clock = clock
        self.key = settings.redis_key_prefix + ":provider:live:gemini:interview"
        self.redis = redis_client or redis.Redis.from_url(
            settings.redis_url,
            decode_responses=True,
            socket_connect_timeout=1,
            socket_timeout=1,
        )

    def acquire(self) -> GeminiSessionLease:
        token = secrets.token_urlsafe(24)
        now = self.clock()
        expires = now + self.settings.gemini_live_lease_seconds
        try:
            admitted = bool(
                self.redis.eval(
                    self._acquire_script,
                    1,
                    self.key,
                    now,
                    expires,
                    self.settings.gemini_live_session_limit,
                    token,
                )
            )
            backend = "redis"
        except redis.RedisError:
            if self.settings.app_env in {"staging", "production"}:
                raise AppError(
                    503,
                    "GEMINI_SESSION_COORDINATION_UNAVAILABLE",
                    "Realtime interview coordination is unavailable",
                    retryable=True,
                )
            backend = "local"
            with self._local_lock:
                leases = self._local_leases.setdefault(self.key, {})
                leases = {key: value for key, value in leases.items() if value > now}
                self._local_leases[self.key] = leases
                admitted = len(leases) < self.settings.gemini_live_session_limit
                if admitted:
                    leases[token] = expires
        if not admitted:
            raise AppError(
                503,
                "GEMINI_SESSION_LIMIT_REACHED",
                "Realtime interview capacity is temporarily full",
                retryable=True,
            )
        return GeminiSessionLease(token=token, backend=backend)

    def refresh(self, lease: GeminiSessionLease) -> bool:
        now = self.clock()
        expires = now + self.settings.gemini_live_lease_seconds
        if lease.backend == "redis":
            try:
                return bool(
                    self.redis.eval(
                        self._refresh_script,
                        1,
                        self.key,
                        expires,
                        self.settings.gemini_live_lease_seconds,
                        lease.token,
                    )
                )
            except redis.RedisError:
                return False
        with self._local_lock:
            leases = self._local_leases.get(self.key, {})
            if lease.token not in leases:
                return False
            leases[lease.token] = expires
            return True

    def release(self, lease: GeminiSessionLease) -> None:
        if lease.backend == "redis":
            try:
                self.redis.zrem(self.key, lease.token)
            except redis.RedisError:
                pass
            return
        with self._local_lock:
            self._local_leases.get(self.key, {}).pop(lease.token, None)


@dataclass
class GeminiConnectionState:
    connection_id: str
    provider_run_id: str | None = None
    provider_session_id: str | None = None
    usage: dict[str, Any] = field(default_factory=dict)


class GeminiInterviewGateway:
    endpoint = (
        "wss://generativelanguage.googleapis.com/ws/"
        "google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContent"
    )

    def __init__(
        self,
        settings: Settings | None = None,
        connect=None,
        limiter: GeminiSessionLimiter | None = None,
        monotonic=time.monotonic,
    ) -> None:
        self.settings = settings or get_settings()
        self.connect = connect or websockets.connect
        self.limiter = limiter or GeminiSessionLimiter(self.settings)
        self.monotonic = monotonic

    async def run(self, websocket: WebSocket, interview: ProductInterview) -> None:
        api_key = self.settings.gemini_api_key or ""
        if not api_key:
            raise AppError(503, "GEMINI_LIVE_UNAVAILABLE", "Gemini Live is not configured", retryable=True)
        uri = self.endpoint + "?key=" + quote(api_key)
        lease = self.limiter.acquire()
        started = self.monotonic()
        state = GeminiConnectionState(connection_id=secrets.token_hex(12))
        provider_error: AppError | None = None
        try:
            async with self.connect(
                uri,
                max_size=32 * 1024 * 1024,
                max_queue=8,
                write_limit=64 * 1024,
                ping_interval=20,
                ping_timeout=20,
                close_timeout=5,
            ) as upstream:
                await upstream.send(json.dumps(self._setup(interview)))
                first = self._decode_provider_message(
                    await asyncio.wait_for(
                        upstream.recv(),
                        timeout=self.settings.gemini_live_setup_timeout_seconds,
                    )
                )
                if "setupComplete" not in first:
                    raise AppError(502, "GEMINI_SETUP_FAILED", "Gemini Live setup failed", retryable=True)
                setup = first.get("setupComplete") or {}
                state.provider_session_id = str(setup.get("sessionId") or "") or None
                state.provider_run_id = (
                    (state.provider_session_id + ":" if state.provider_session_id else "")
                    + state.connection_id
                )
                self._merge_usage(state, first)
                self._record(
                    interview.id,
                    "provider",
                    "provider.setup_complete",
                    payload={"provider_session_id": state.provider_session_id},
                    provider_event_id=state.provider_run_id + ":setup",
                )
                await websocket.send_json(
                    {
                        "type": "session.ready",
                        "payload": {
                            "interview_id": interview.id,
                            "input_mime_type": "audio/pcm;rate=16000",
                            "output_mime_type": "audio/pcm;rate=24000",
                        },
                    }
                )
                await self._run_streams(websocket, upstream, interview, state, lease)
        except AppError as exc:
            if exc.code.startswith("GEMINI_") or exc.code.startswith("PROVIDER_"):
                provider_error = exc
            raise
        except (OSError, websockets.WebSocketException, asyncio.TimeoutError) as exc:
            provider_error = AppError(
                503,
                "GEMINI_LIVE_UNAVAILABLE",
                "Gemini Live connection failed",
                retryable=True,
            )
            raise provider_error from exc
        finally:
            self.limiter.release(lease)
            self._persist_usage(
                interview,
                state,
                max(0, int((self.monotonic() - started) * 1000)),
                provider_error,
            )

    async def _run_streams(
        self,
        websocket: WebSocket,
        upstream,
        interview: ProductInterview,
        state: GeminiConnectionState,
        lease: GeminiSessionLease,
    ) -> None:
        client_task = asyncio.create_task(self._client_loop(websocket, upstream, interview.id))
        provider_task = asyncio.create_task(
            self._provider_loop(websocket, upstream, interview.id, state)
        )
        heartbeat_task = asyncio.create_task(self._lease_heartbeat(lease))
        tasks = {client_task, provider_task, heartbeat_task}
        remaining = self._remaining_seconds(interview)
        try:
            done, pending = await asyncio.wait(
                tasks,
                timeout=remaining,
                return_when=asyncio.FIRST_COMPLETED,
            )
            if not done:
                self._record(interview.id, "system", "session.duration_reached", payload={})
                with SessionLocal() as db:
                    ProductInterviewService(db).timeout_realtime(interview.id)
                await websocket.send_json(
                    {"type": "session.ended", "payload": {"interview_id": interview.id, "reason": "duration_limit"}}
                )
                return
            for task in done:
                task.result()
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            for task in tasks:
                if task.cancelled() or task.done():
                    continue
                with suppress(asyncio.CancelledError):
                    await task

    async def _lease_heartbeat(self, lease: GeminiSessionLease) -> None:
        interval = max(5, self.settings.gemini_live_lease_seconds // 3)
        while True:
            await asyncio.sleep(interval)
            if not self.limiter.refresh(lease):
                raise AppError(
                    503,
                    "GEMINI_SESSION_LEASE_LOST",
                    "Realtime interview capacity lease was lost",
                    retryable=True,
                )

    async def _client_loop(self, websocket: WebSocket, upstream, interview_id: str) -> None:
        while True:
            try:
                raw_event = await asyncio.wait_for(
                    websocket.receive_json(),
                    timeout=self.settings.gemini_live_idle_timeout_seconds,
                )
                event = RealtimeClientEvent.model_validate(raw_event)
            except asyncio.TimeoutError:
                self._record(interview_id, "system", "session.idle_timeout", payload={})
                await websocket.send_json(
                    {"type": "warning", "payload": {"code": "REALTIME_IDLE_TIMEOUT", "reconnect": True}}
                )
                return
            except (ValidationError, ValueError):
                await websocket.send_json({"type": "error", "payload": {"code": "INVALID_REALTIME_EVENT", "message": "Realtime event does not match the contract"}})
                continue
            if event.type == "ping":
                self._record(interview_id, "client", "ping", client_event_id=event.event_id)
                await websocket.send_json({"type": "pong", "payload": {"event_id": event.event_id}})
                continue
            if event.type == "session.start":
                self._record(interview_id, "client", "session.start", client_event_id=event.event_id)
                continue
            if event.type == "audio.append":
                data = str(event.payload.get("data_base64") or "")
                mime = str(event.payload.get("mime_type") or "audio/pcm;rate=16000")
                try:
                    self._validate_audio(data, mime)
                except AppError as exc:
                    await websocket.send_json(
                        {"type": "error", "payload": {"code": exc.code, "message": exc.message}}
                    )
                    continue
                persisted = self._record(
                    interview_id,
                    "client",
                    "audio.append",
                    payload={"mime_type": mime, "size_base64": len(data), "sha256": hashlib.sha256(data.encode()).hexdigest()},
                    client_event_id=event.event_id,
                )
                if not getattr(persisted, "_deduplicated", False):
                    await upstream.send(json.dumps({"realtimeInput": {"audio": {"data": data, "mimeType": mime}}}))
                continue
            if event.type == "audio.commit":
                persisted = self._record(interview_id, "client", "audio.commit", client_event_id=event.event_id)
                if not getattr(persisted, "_deduplicated", False):
                    await upstream.send(json.dumps({"realtimeInput": {"audioStreamEnd": True}}))
                continue
            if event.type == "session.end":
                self._record(interview_id, "client", "session.end", client_event_id=event.event_id)
                with SessionLocal() as db:
                    ProductInterviewService(db).end_realtime(interview_id)
                await websocket.send_json({"type": "session.ended", "payload": {"interview_id": interview_id}})
                return

    async def _provider_loop(
        self,
        websocket: WebSocket,
        upstream,
        interview_id: str,
        state: GeminiConnectionState,
    ) -> None:
        provider_sequence = 0
        billable_marked = False
        async for raw_message in upstream:
            provider_sequence += 1
            payload = self._decode_provider_message(raw_message)
            self._merge_usage(state, payload)
            provider_id = str(
                payload.get("id") or (state.connection_id + ":connection-event-" + str(provider_sequence))
            )
            if "sessionResumptionUpdate" in payload:
                update = payload["sessionResumptionUpdate"]
                handle = update.get("newHandle") if update.get("resumable") else None
                with SessionLocal() as db:
                    ProductInterviewService(db).update_resumption_handle(interview_id, handle)
                self._record(
                    interview_id,
                    "provider",
                    "session.resumption",
                    payload={
                        "resumable": bool(handle),
                        "last_consumed_client_message_index": update.get("lastConsumedClientMessageIndex"),
                    },
                    provider_event_id=provider_id,
                )
                continue
            if "goAway" in payload:
                time_left = (payload.get("goAway") or {}).get("timeLeft")
                self._record(interview_id, "provider", "provider.go_away", payload={"time_left": time_left}, provider_event_id=provider_id)
                await websocket.send_json({"type": "warning", "payload": {"code": "PROVIDER_GO_AWAY", "reconnect": True, "time_left": time_left}})
                return
            content = payload.get("serverContent") or {}
            input_text = (content.get("inputTranscription") or {}).get("text")
            output_text = (content.get("outputTranscription") or {}).get("text")
            if input_text:
                event = self._record(
                    interview_id,
                    "provider",
                    "transcript.final" if content.get("turnComplete") else "transcript.delta",
                    speaker="candidate",
                    text=str(input_text),
                    provider_event_id=provider_id + ":input",
                )
                await websocket.send_json({"type": event.event_type, "payload": {"event_id": event.id, "speaker": "candidate", "text": input_text}})
            if output_text:
                event = self._record(
                    interview_id,
                    "provider",
                    "transcript.final" if content.get("turnComplete") else "transcript.delta",
                    speaker="interviewer",
                    text=str(output_text),
                    provider_event_id=provider_id + ":output",
                )
                await websocket.send_json({"type": event.event_type, "payload": {"event_id": event.id, "speaker": "interviewer", "text": output_text}})
                if not billable_marked:
                    with SessionLocal() as db:
                        ProductInterviewService(db).mark_billable_started(interview_id, event.id)
                    billable_marked = True
            for index, part in enumerate((content.get("modelTurn") or {}).get("parts", [])):
                inline = part.get("inlineData") or {}
                if inline.get("data"):
                    audio = str(inline["data"])
                    event = self._record(
                        interview_id,
                        "provider",
                        "audio.delta",
                        payload={
                            "mime_type": inline.get("mimeType", "audio/pcm;rate=24000"),
                            "size_base64": len(audio),
                            "sha256": hashlib.sha256(audio.encode()).hexdigest(),
                        },
                        provider_event_id=provider_id + ":audio:" + str(index),
                    )
                    await websocket.send_json(
                        {
                            "type": "audio.delta",
                            "payload": {
                                "event_id": event.id,
                                "mime_type": inline.get("mimeType", "audio/pcm;rate=24000"),
                                "data_base64": audio,
                            },
                        }
                    )
                    if not billable_marked:
                        with SessionLocal() as db:
                            ProductInterviewService(db).mark_billable_started(interview_id, event.id)
                        billable_marked = True
            if content.get("generationComplete"):
                event = self._record(
                    interview_id,
                    "provider",
                    "generation.complete",
                    payload={},
                    provider_event_id=provider_id + ":generation",
                )
                await websocket.send_json(
                    {"type": "generation.complete", "payload": {"event_id": event.id}}
                )
            if content.get("turnComplete"):
                event = self._record(
                    interview_id,
                    "provider",
                    "turn.complete",
                    payload={},
                    provider_event_id=provider_id + ":turn",
                )
                await websocket.send_json(
                    {"type": "turn.complete", "payload": {"event_id": event.id}}
                )
            if content.get("interrupted"):
                event = self._record(
                    interview_id,
                    "provider",
                    "generation.interrupted",
                    payload={},
                    provider_event_id=provider_id + ":interrupted",
                )
                await websocket.send_json(
                    {"type": "generation.interrupted", "payload": {"event_id": event.id}}
                )
        raise AppError(
            503,
            "GEMINI_LIVE_DISCONNECTED",
            "Gemini Live disconnected without a resumable handoff",
            retryable=True,
        )

    def _setup(self, interview: ProductInterview) -> dict[str, Any]:
        model = interview.gemini_model
        if not model.startswith("models/"):
            model = "models/" + model
        instruction = (
            "You are a rigorous but supportive interviewer for an IT student. Ask one concise question at a time. "
            "Never make a hiring decision. Ground follow-ups in the candidate CV, target job, and answers. "
            "Conduct the entire interview in "
            + ("Vietnamese" if interview.language == "vi" else "English")
            + ". Interview plan: "
            + json.dumps(interview.plan_snapshot, ensure_ascii=False)
            + ". CV snapshot: "
            + json.dumps(interview.cv_snapshot, ensure_ascii=False)
        )
        if interview.job_snapshot:
            instruction += ". Target job snapshot: " + json.dumps(
                interview.job_snapshot,
                ensure_ascii=False,
            )
        if interview.plan_snapshot.get("instruction_prefix"):
            instruction = str(interview.plan_snapshot["instruction_prefix"]) + "\n" + instruction
        setup: dict[str, Any] = {
            "model": model,
            "generationConfig": {
                "responseModalities": ["AUDIO"],
                "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": "Aoede"}}},
            },
            "systemInstruction": {"parts": [{"text": instruction}]},
            "inputAudioTranscription": {},
            "outputAudioTranscription": {},
            "sessionResumption": {},
            "contextWindowCompression": {"slidingWindow": {}},
        }
        if interview.gemini_resumption_handle:
            setup["sessionResumption"] = {"handle": interview.gemini_resumption_handle}
        return {"setup": setup}

    def _validate_audio(self, data: str, mime: str) -> None:
        if not data or mime != "audio/pcm;rate=16000":
            raise AppError(422, "INVALID_AUDIO_CHUNK", "Audio must be 16 kHz raw PCM")
        try:
            decoded = base64.b64decode(data, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise AppError(422, "INVALID_AUDIO_CHUNK", "Audio chunk is not valid base64") from exc
        if len(decoded) > self.settings.gemini_live_audio_chunk_max_bytes:
            raise AppError(413, "AUDIO_CHUNK_TOO_LARGE", "Audio chunk exceeds the configured limit")

    @staticmethod
    def _decode_provider_message(raw_message: Any) -> dict[str, Any]:
        try:
            payload = json.loads(raw_message)
        except (TypeError, ValueError) as exc:
            raise AppError(502, "GEMINI_PROTOCOL_ERROR", "Gemini Live returned invalid JSON", retryable=True) from exc
        if not isinstance(payload, dict):
            raise AppError(502, "GEMINI_PROTOCOL_ERROR", "Gemini Live returned an invalid message", retryable=True)
        return payload

    @staticmethod
    def _merge_usage(state: GeminiConnectionState, payload: dict[str, Any]) -> None:
        usage = payload.get("usageMetadata")
        if not isinstance(usage, dict):
            return
        for key, value in usage.items():
            if isinstance(value, (int, float)):
                state.usage[key] = max(value, state.usage.get(key, 0))
            elif isinstance(value, (str, bool)):
                state.usage[key] = value

    def _persist_usage(
        self,
        interview: ProductInterview,
        state: GeminiConnectionState,
        latency_ms: int,
        error: AppError | None,
    ) -> None:
        metadata = {
            "model": interview.gemini_model,
            "provider_run_id": state.provider_run_id,
            "latency_ms": latency_ms,
            "usage": {
                **state.usage,
                "provider_session_id": state.provider_session_id,
            },
        }
        with SessionLocal() as db:
            usage = ProviderUsageService(db)
            if error is None:
                usage.success(
                    user_id=interview.user_id,
                    provider="gemini",
                    purpose="interview_live",
                    resource_type="interview",
                    resource_id=interview.id,
                    metadata=metadata,
                )
            else:
                usage.failure(
                    user_id=interview.user_id,
                    provider="gemini",
                    purpose="interview_live",
                    resource_type="interview",
                    resource_id=interview.id,
                    error=error,
                    metadata=metadata,
                )
            db.commit()

    @staticmethod
    def _remaining_seconds(interview: ProductInterview) -> float:
        started_at = interview.started_at or datetime.now(timezone.utc)
        if started_at.tzinfo is None:
            started_at = started_at.replace(tzinfo=timezone.utc)
        deadline = started_at + timedelta(minutes=interview.duration_minutes)
        return max(0.0, (deadline - datetime.now(timezone.utc)).total_seconds())

    @staticmethod
    def _record(interview_id: str, direction: str, event_type: str, **kwargs):
        with SessionLocal() as db:
            return ProductInterviewService(db).record_event(interview_id, direction, event_type, **kwargs)
