from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class InterviewCreateRequest(BaseModel):
    cv_id: str
    target_role: str = Field(default="Backend Developer Intern")
    language: str = Field(default="vi")


class InterviewCreateResult(BaseModel):
    interview_id: str
    cv_id: str
    status: str
    target_role: str
    opening_message: str


class InterviewClientEvent(BaseModel):
    type: str = Field(description="audio.chunk, text.message, control.end_turn, or control.end")
    payload: dict[str, Any] = Field(default_factory=dict)


class TranscriptMessage(BaseModel):
    role: str
    text: str
    created_at: datetime | None = None


class RubricScore(BaseModel):
    name: str
    score: float = Field(ge=0.0, le=10.0)
    comment: str


class InterviewResult(BaseModel):
    overall_score: float = Field(ge=0.0, le=10.0)
    rubric_scores: list[RubricScore] = Field(default_factory=list)
    strengths: list[str] = Field(default_factory=list)
    weaknesses: list[str] = Field(default_factory=list)
    recommended_roles: list[str] = Field(default_factory=list)
    skill_gaps: list[str] = Field(default_factory=list)
    transcript_summary: str
    full_transcript_ref: str | None = None


class InterviewEndResult(BaseModel):
    interview_id: str
    status: str
    result: InterviewResult


class InterviewResultRead(BaseModel):
    interview_id: str
    cv_id: str
    status: str
    target_role: str
    result: InterviewResult | None = None
    transcript: list[TranscriptMessage] = Field(default_factory=list)
