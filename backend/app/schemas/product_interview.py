from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class CreateInterviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cv_version_id: str
    job_id: str | None = None
    target_role: str = Field(min_length=1, max_length=200)
    interview_type: Literal["behavioral", "technical", "mixed"]
    language: Literal["vi", "en"] = "vi"
    duration_minutes: int = Field(default=20, ge=5, le=30)


class InterviewView(BaseModel):
    id: str
    status: str
    target_role: str
    interview_type: str
    cv_version_id: str
    job_id: str | None
    language: str
    duration_minutes: int
    started_at: datetime | None
    ended_at: datetime | None
    reconnect_until: datetime | None
    created_at: datetime


class InterviewPage(BaseModel):
    items: list[InterviewView]
    next_cursor: str | None


class RealtimeTokenView(BaseModel):
    token: str
    websocket_url: str
    expires_at: datetime


class RealtimeClientEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(min_length=8, max_length=128)
    type: Literal["session.start", "audio.append", "audio.commit", "session.end", "ping"]
    payload: dict[str, Any] = Field(default_factory=dict)

    @field_validator("payload")
    @classmethod
    def bound_audio_payload(cls, value: dict[str, Any]) -> dict[str, Any]:
        data = value.get("data_base64")
        if isinstance(data, str) and len(data) > 512 * 1024:
            raise ValueError("audio chunk exceeds 384 KiB")
        return value


class EvidenceFinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1, max_length=2000)
    evidence_event_ids: list[str] = Field(default_factory=list, max_length=50)


class InterviewReportView(BaseModel):
    id: str
    interview_id: str
    status: str
    rubric_version: str
    scores: dict[str, float]
    strengths: list[EvidenceFinding]
    gaps: list[EvidenceFinding]
    actions: list[str]
    disclaimer: str
    created_at: datetime


class InterviewFeedbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: Literal["transcript_incorrect", "evaluation_incorrect", "unsafe", "other"]
    message: str = Field(min_length=3, max_length=5000)
    event_ids: list[str] = Field(default_factory=list, max_length=50)


class InterviewFeedbackView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    interview_id: str
    report_id: str
    category: str
    message: str
    event_ids: list[str]
    status: str
    created_at: datetime
