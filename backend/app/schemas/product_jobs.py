from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class SalaryView(BaseModel):
    minimum_minor: int | None = None
    maximum_minor: int | None = None
    currency: str
    period: str = "unknown"


class JobSourceReferenceView(BaseModel):
    source: str
    source_job_id: str | None
    url: str
    last_checked_at: datetime | None
    verification_status: str


class JobView(BaseModel):
    id: str
    title: str
    company_name: str
    location: str | None
    remote_mode: str
    employment_type: str | None
    seniority: str | None
    salary: SalaryView | None
    description: str | None
    description_completeness: str
    skills: list[str]
    status: str
    sources: list[JobSourceReferenceView]
    first_seen_at: datetime
    last_seen_at: datetime
    verified_at: datetime | None


class JobPage(BaseModel):
    items: list[JobView]
    next_cursor: str | None


class JobSearchFilters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    locations: list[str] = Field(default_factory=list, max_length=20)
    remote_modes: list[Literal["onsite", "hybrid", "remote", "unknown"]] = Field(default_factory=list)
    employment_types: list[str] = Field(default_factory=list, max_length=20)
    skills: list[str] = Field(default_factory=list, max_length=50)
    verified_only: bool = True


class CreateJobSearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=500)
    mode: Literal["indexed", "live", "hybrid"] = "hybrid"
    cv_version_id: str | None = None
    filters: JobSearchFilters = Field(default_factory=JobSearchFilters)
    maximum_results: int = Field(default=20, ge=1, le=100)


class JobSearchRunView(BaseModel):
    id: str
    status: str
    mode: str
    query: str
    progress: dict[str, int]
    degraded_reasons: list[str]
    events_url: str
    results_url: str
    created_at: datetime
    completed_at: datetime | None


class JobMatchView(BaseModel):
    job: JobView
    rank: int
    score: float = Field(ge=0, le=1)
    reasons: list[str]
    gaps: list[str]
    explanation_status: str


class JobMatchPage(BaseModel):
    items: list[JobMatchView]
    next_cursor: str | None
