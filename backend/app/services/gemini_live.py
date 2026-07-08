import asyncio
import json
from typing import Any

import websockets
from fastapi import WebSocket
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.schemas.interview import InterviewClientEvent
from app.services.interview import InterviewService


class GeminiLiveProxy:
    endpoint = (
        "wss://generativelanguage.googleapis.com/ws/"
        "google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContent"
    )

    def __init__(self, *, db: Session, settings: Settings | None = None) -> None:
        self.db = db
        self.settings = settings or get_settings()
        self.interviews = InterviewService(db=db)

    async def run(self, *, websocket: WebSocket, interview_id: str) -> None:
        uri = f"{self.endpoint}?key={self.settings.gemini_api_key}"
        async with websockets.connect(uri, max_size=32 * 1024 * 1024) as upstream:
            await upstream.send(json.dumps(self._setup_payload(interview_id=interview_id)))
            await websocket.send_json(
                {
                    "type": "interview.state",
                    "payload": {"state": "gemini_live_connecting"},
                }
            )

            client_task = asyncio.create_task(
                self._client_to_gemini(
                    websocket=websocket,
                    upstream=upstream,
                    interview_id=interview_id,
                )
            )
            gemini_task = asyncio.create_task(
                self._gemini_to_client(
                    websocket=websocket,
                    upstream=upstream,
                    interview_id=interview_id,
                )
            )

            done, pending = await asyncio.wait(
                {client_task, gemini_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in pending:
                task.cancel()
            for task in done:
                task.result()

    async def _client_to_gemini(self, *, websocket: WebSocket, upstream, interview_id: str) -> None:
        while True:
            raw_event = await websocket.receive_json()
            event = InterviewClientEvent.model_validate(raw_event)

            if event.type == "text.message":
                text = str(event.payload.get("text") or "").strip()
                if not text:
                    continue
                self.interviews.record_user_text(
                    interview_id=interview_id,
                    text=text,
                    payload=event.payload,
                )
                await upstream.send(
                    json.dumps(
                        {
                            "clientContent": {
                                "turns": [{"role": "user", "parts": [{"text": text}]}],
                                "turnComplete": True,
                            }
                        }
                    )
                )

            elif event.type == "audio.chunk":
                self.interviews.record_user_audio(interview_id=interview_id, payload=event.payload)
                mime = event.payload.get("mime") or "audio/pcm"
                sample_rate = event.payload.get("sample_rate") or 16000
                await upstream.send(
                    json.dumps(
                        {
                            "realtimeInput": {
                                "mediaChunks": [
                                    {
                                        "mimeType": f"{mime};rate={sample_rate}",
                                        "data": event.payload.get("data_base64"),
                                    }
                                ]
                            }
                        }
                    )
                )

            elif event.type == "control.end_turn":
                await upstream.send(json.dumps({"clientContent": {"turnComplete": True}}))

            elif event.type == "control.end":
                return

    async def _gemini_to_client(self, *, websocket: WebSocket, upstream, interview_id: str) -> None:
        async for message in upstream:
            payload = json.loads(message)

            if "setupComplete" in payload:
                await websocket.send_json(
                    {"type": "interview.state", "payload": {"state": "live"}}
                )
                continue

            server_content = payload.get("serverContent") or {}
            input_transcript = server_content.get("inputTranscription", {}).get("text")
            output_transcript = server_content.get("outputTranscription", {}).get("text")

            if input_transcript:
                await websocket.send_json(
                    {
                        "type": "transcript.user",
                        "payload": {"text": input_transcript, "final": True},
                    }
                )

            if output_transcript:
                self.interviews.record_model_text(
                    interview_id=interview_id,
                    text=output_transcript,
                    payload={"source": "gemini_live_output_transcription"},
                )
                await websocket.send_json(
                    {
                        "type": "transcript.model",
                        "payload": {"text": output_transcript, "final": True},
                    }
                )

            model_turn = server_content.get("modelTurn") or {}
            for part in model_turn.get("parts", []):
                text = part.get("text")
                if text:
                    self.interviews.record_model_text(
                        interview_id=interview_id,
                        text=text,
                        payload={"source": "gemini_live_model_turn"},
                    )
                    await websocket.send_json(
                        {
                            "type": "transcript.model",
                            "payload": {
                                "text": text,
                                "final": bool(server_content.get("turnComplete")),
                            },
                        }
                    )

                inline_data = part.get("inlineData") or {}
                if inline_data.get("data"):
                    await websocket.send_json(
                        {
                            "type": "audio.chunk",
                            "payload": {
                                "mime": inline_data.get("mimeType", "audio/pcm"),
                                "sample_rate": 24000,
                                "data_base64": inline_data["data"],
                            },
                        }
                    )

            if "goAway" in payload:
                await websocket.send_json(
                    {
                        "type": "interview.state",
                        "payload": {"state": "gemini_live_goaway"},
                    }
                )
                return

    def _setup_payload(self, *, interview_id: str) -> dict[str, Any]:
        result = self.interviews.get_result(interview_id=interview_id)
        model = self.settings.gemini_live_model
        if not model.startswith("models/"):
            model = f"models/{model}"

        if result.interview_type == "diagnostic":
            instruction = (
                "You are a career-fit diagnostic interviewer for IT students. "
                "The candidate may not know which JD or role fits them yet. "
                "Ask one concise question at a time to understand skills, projects, confidence, "
                "constraints, preferred work model, and realistic entry-level roles. "
                "Do not optimize for a specific JD during this interview."
            )
        else:
            instruction = (
                "You are a friendly but rigorous technical interviewer for IT students. "
                f"Interview for target role: {result.target_role}. "
                "Ask one question at a time, adapt to the candidate CV and answers, "
                "and keep responses concise."
            )

        return {
            "setup": {
                "model": model,
                "generationConfig": {
                    "responseModalities": ["AUDIO"],
                    "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": "Aoede"}}},
                },
                "systemInstruction": {"parts": [{"text": instruction}]},
            }
        }
