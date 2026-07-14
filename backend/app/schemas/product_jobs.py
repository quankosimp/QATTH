from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


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
    salary_min_minor: int | None = Field(default=None, ge=0)
    salary_max_minor: int | None = Field(default=None, ge=0)
    salary_currency: str | None = Field(default=None, min_length=3, max_length=3)
    salary_period: str | None = Field(default=None, min_length=1, max_length=20)
    verified_only: bool = True

    @field_validator("salary_currency")
    @classmethod
    def normalize_currency(cls, value: str | None) -> str | None:
        return value.upper() if value else None

    @model_validator(mode="after")
    def validate_salary_range(self) -> "JobSearchFilters":
        if self.salary_min_minor is not None and self.salary_max_minor is not None:
            if self.salary_min_minor > self.salary_max_minor:
                raise ValueError("salary_min_minor must not exceed salary_max_minor")
        if (self.salary_min_minor is not None or self.salary_max_minor is not None) and not self.salary_currency:
            raise ValueError("salary_currency is required when salary range is provided")
        return self


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
    provider: str | None
    provider_run_id: str | None
    provider_model: str | None
    provider_model_configuration_id: str | None
    provider_usage: dict[str, Any] | None
    provider_estimated_cost_minor: int | None
    error: dict[str, Any] | None
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
