from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class CreateModelConfigurationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    purpose: str = Field(min_length=2, max_length=120, pattern=r"^[a-z][a-z0-9_]{1,119}$")
    version: str = Field(min_length=1, max_length=80)
    provider: Literal["openai", "gemini"]
    model: str = Field(min_length=1, max_length=160)
    configuration: dict[str, Any]
    output_schema_version: str | None = Field(default=None, max_length=80)


class ActivateModelConfigurationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=3, max_length=500)


class ModelConfigurationView(BaseModel):
    id: str
    purpose: str
    version: str
    status: Literal["draft", "active", "retired"]
    provider: str
    model: str
    output_schema_version: str | None
    created_at: datetime


class JobSourceAdminView(BaseModel):
    id: str
    key: str
    name: str
    status: Literal["active", "degraded", "disabled"]
    quality_score: float = Field(ge=0, le=1)
    last_healthy_at: datetime | None
    stale_rate: float | None


class UpdateJobSourceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["active", "degraded", "disabled"] | None = None
    quality_score: float | None = Field(default=None, ge=0, le=1)
    reason: str = Field(min_length=3, max_length=500)


class AdminUserSummary(BaseModel):
    id: str
    email: str
    role: str
    account_status: str
    created_at: datetime


class ModerationCaseView(BaseModel):
    id: str
    job_id: str
    reporter_user_id: str
    reason_code: str
    details: str | None
    status: str
    assigned_to_user_id: str | None
    resolution: dict[str, Any] | None
    created_at: datetime
    updated_at: datetime


class ResolveModerationCaseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["dismiss", "invalidate_job", "disable_source"]
    reason: str = Field(min_length=3, max_length=500)


class BackgroundJobView(BaseModel):
    id: str
    type: str
    queue: str
    status: Literal["queued", "running", "succeeded", "failed", "cancelled", "dead_letter"]
    attempt: int
    max_attempts: int
    resource_type: str | None
    resource_id: str | None
    error_code: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class BackgroundJobPage(BaseModel):
    items: list[BackgroundJobView]
    next_cursor: str | None


class RetryBackgroundJobRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=3, max_length=500)


class OpsDiagnosticsView(BaseModel):
    status: Literal["ok", "degraded"]
    database: str
    redis: str
    failed_jobs_24h: int
    pending_jobs: int
    pending_dispatches: int
