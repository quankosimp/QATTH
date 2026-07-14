from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.product_jobs import JobView


InteractionType = Literal["viewed", "saved", "dismissed", "reported"]
ApplicationStatus = Literal["planned", "applied", "screening", "interviewing", "offered", "accepted", "rejected", "withdrawn"]


class UpsertJobInteractionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    interaction_type: InteractionType
    reason_code: str | None = Field(default=None, max_length=80)
    note: str | None = Field(default=None, max_length=2000)
    context: dict[str, Any] = Field(default_factory=dict)


class JobInteractionView(BaseModel):
    id: str
    job_id: str
    interaction_type: InteractionType
    reason_code: str | None
    note: str | None
    taxonomy_version: str
    created_at: datetime
    updated_at: datetime


class CreateJobApplicationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: str
    status: ApplicationStatus = "planned"
    source_url: str | None = Field(default=None, max_length=4000)
    notes: str | None = Field(default=None, max_length=5000)


class UpdateJobApplicationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: ApplicationStatus
    expected_version: int = Field(ge=1)
    reason_code: str | None = Field(default=None, max_length=80)
    notes: str | None = Field(default=None, max_length=5000)


class JobApplicationEventView(BaseModel):
    sequence: int
    from_status: str | None
    to_status: str
    actor_type: str
    reason_code: str | None
    created_at: datetime


class JobApplicationView(BaseModel):
    id: str
    job_id: str
    status: ApplicationStatus
    version: int
    source_url: str | None
    notes: str | None
    job_snapshot: dict[str, Any]
    events: list[JobApplicationEventView]
    applied_at: datetime | None
    closed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class JobApplicationPage(BaseModel):
    items: list[JobApplicationView]
    next_cursor: str | None


class CreateRecommendationRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cv_version_id: str | None = None
    search_run_id: str | None = None
    maximum_results: int = Field(default=20, ge=1, le=50)


class RecommendationRunView(BaseModel):
    id: str
    status: str
    cv_version_id: str | None
    search_run_id: str | None
    candidate_profile_version: int
    ranking_version: str
    experiment_assignment: dict[str, str]
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    error: dict[str, Any] | None


class RecommendationMatchView(BaseModel):
    job: JobView
    rank: int
    score: float = Field(ge=0, le=1)
    score_breakdown: dict[str, float]
    reasons: list[str]
    gaps: list[str]
    evidence: dict[str, Any]


class RecommendationMatchPage(BaseModel):
    items: list[RecommendationMatchView]
    next_cursor: str | None
