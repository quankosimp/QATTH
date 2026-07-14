from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import secrets
from contextlib import suppress
from typing import Any
from urllib.parse import quote

import websockets
from fastapi import WebSocket
from pydantic import ValidationError

from backend.app.core.db import SessionLocal
from backend.app.core.errors import AppError
from backend.app.models.product_interview import ProductInterview
from backend.app.schemas.product_interview import RealtimeClientEvent
from backend.app.services.product_interview import ProductInterviewService


class GeminiInterviewGateway:
    endpoint = (
        "wss://generativelanguage.googleapis.com/ws/"
        "google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContent"
    )

    async def run(self, websocket: WebSocket, interview: ProductInterview) -> None:
        api_key = os.getenv("GEMINI_API_KEY", "")
        if not api_key:
            raise AppError(503, "GEMINI_LIVE_UNAVAILABLE", "Gemini Live is not configured", retryable=True)
        uri = self.endpoint + "?key=" + quote(api_key)
        try:
            async with websockets.connect(
                uri,
                max_size=32 * 1024 * 1024,
                ping_interval=20,
                ping_timeout=20,
                close_timeout=5,
            ) as upstream:
                await upstream.send(json.dumps(self._setup(interview)))
                first = json.loads(await asyncio.wait_for(upstream.recv(), timeout=15))
                if "setupComplete" not in first:
                    raise AppError(502, "GEMINI_SETUP_FAILED", "Gemini Live setup failed", retryable=True)
                self._record(interview.id, "provider", "provider.setup_complete", payload={})
                await websocket.send_json({"type": "session.ready", "payload": {"interview_id": interview.id}})
                client_task = asyncio.create_task(self._client_loop(websocket, upstream, interview.id))
                provider_task = asyncio.create_task(
                    self._provider_loop(
                        websocket,
                        upstream,
                        interview.id,
                        secrets.token_hex(12),
                    )
                )
                done, pending = await asyncio.wait({client_task, provider_task}, return_when=asyncio.FIRST_COMPLETED)
                for task in pending:
                    task.cancel()
                for task in pending:
                    with suppress(asyncio.CancelledError):
                        await task
                for task in done:
                    task.result()
        except AppError:
            raise
        except (OSError, websockets.WebSocketException, asyncio.TimeoutError) as exc:
            raise AppError(503, "GEMINI_LIVE_UNAVAILABLE", "Gemini Live connection failed", retryable=True) from exc

    async def _client_loop(self, websocket: WebSocket, upstream, interview_id: str) -> None:
        while True:
            try:
                event = RealtimeClientEvent.model_validate(await websocket.receive_json())
            except ValidationError as exc:
                await websocket.send_json({"type": "error", "payload": {"code": "INVALID_REALTIME_EVENT", "message": str(exc)}})
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
                self._validate_audio(data, mime)
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
                self._record(interview_id, "client", "audio.commit", client_event_id=event.event_id)
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
        connection_id: str,
    ) -> None:
        provider_sequence = 0
        async for raw_message in upstream:
            provider_sequence += 1
            payload = json.loads(raw_message)
            provider_id = str(
                payload.get("id") or (connection_id + ":connection-event-" + str(provider_sequence))
            )
            if "sessionResumptionUpdate" in payload:
                update = payload["sessionResumptionUpdate"]
                handle = update.get("newHandle") if update.get("resumable") else None
                with SessionLocal() as db:
                    ProductInterviewService(db).update_resumption_handle(interview_id, handle)
                self._record(interview_id, "provider", "session.resumption", payload={"resumable": bool(handle)}, provider_event_id=provider_id)
                continue
            if "goAway" in payload:
                self._record(interview_id, "provider", "provider.go_away", payload={}, provider_event_id=provider_id)
                await websocket.send_json({"type": "warning", "payload": {"code": "PROVIDER_GO_AWAY", "reconnect": True}})
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

    def _setup(self, interview: ProductInterview) -> dict[str, Any]:
        model = interview.gemini_model
        if not model.startswith("models/"):
            model = "models/" + model
        instruction = (
            "You are a rigorous but supportive interviewer for an IT student. Ask one concise question at a time. "
            "Never make a hiring decision. Ground follow-ups in the candidate CV and answers. Interview plan: "
            + json.dumps(interview.plan_snapshot, ensure_ascii=False)
            + ". CV snapshot: "
            + json.dumps(interview.cv_snapshot, ensure_ascii=False)
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
        }
        if interview.gemini_resumption_handle:
            setup["sessionResumption"] = {"handle": interview.gemini_resumption_handle}
        return {"setup": setup}

    @staticmethod
    def _validate_audio(data: str, mime: str) -> None:
        if not data or not mime.startswith("audio/pcm;rate="):
            raise AppError(422, "INVALID_AUDIO_CHUNK", "Audio must be raw PCM with an explicit sample rate")
        try:
            decoded = base64.b64decode(data, validate=True)
        except ValueError as exc:
            raise AppError(422, "INVALID_AUDIO_CHUNK", "Audio chunk is not valid base64") from exc
        if len(decoded) > 384 * 1024:
            raise AppError(413, "AUDIO_CHUNK_TOO_LARGE", "Audio chunk exceeds 384 KiB")

    @staticmethod
    def _record(interview_id: str, direction: str, event_type: str, **kwargs):
        with SessionLocal() as db:
            return ProductInterviewService(db).record_event(interview_id, direction, event_type, **kwargs)
