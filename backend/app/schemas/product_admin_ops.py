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
    evaluation_report_id: str = Field(min_length=36, max_length=36)
    rollout_percentage: int = Field(ge=1, le=100)


class ModelEvaluationMetricInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=2, max_length=80, pattern=r"^[a-z][a-z0-9_]{1,79}$")
    value: float = Field(ge=0, le=1)


class CreateModelEvaluationReportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dataset_key: str = Field(min_length=2, max_length=120, pattern=r"^[a-z][a-z0-9_.-]{1,119}$")
    dataset_version: str = Field(min_length=1, max_length=80)
    dataset_sha256: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-fA-F]{64}$")
    evaluator_version: str = Field(min_length=1, max_length=80)
    sample_count: int = Field(ge=1)
    metrics: list[ModelEvaluationMetricInput] = Field(min_length=1, max_length=20)
    external_report_id: str | None = Field(default=None, max_length=255)


class ModelEvaluationReportView(BaseModel):
    id: str
    model_configuration_id: str
    dataset_key: str
    dataset_version: str
    dataset_sha256: str
    quality_policy_version: str
    evaluator_version: str
    sample_count: int
    metrics: dict[str, float]
    criteria: list[dict[str, Any]]
    status: Literal["passed", "failed"]
    external_report_id: str | None
    created_at: datetime


class ModelConfigurationView(BaseModel):
    id: str
    purpose: str
    version: str
    status: Literal["draft", "canary", "active", "retired"]
    provider: str
    model: str
    output_schema_version: str | None
    evaluation_report_id: str | None
    rollout_percentage: int
    activated_at: datetime | None
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


class AdminResourceSummary(BaseModel):
    resource_type: str
    id: str
    owner_user_id: str | None
    status: str | None
    created_at: datetime | None
    metadata: dict[str, Any]


class UpdateAccountStatusRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["active", "locked", "disabled"]
    reason: str = Field(min_length=3, max_length=500)


class AccountStatusView(BaseModel):
    event_id: str
    user_id: str
    previous_status: str
    new_status: Literal["active", "locked", "disabled"]
    reason: str
    effective_at: datetime
    sessions_revoked: int
    tokens_revoked: int


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


class ProviderUsageSummaryView(BaseModel):
    period_start: datetime
    period_end: datetime
    provider: str | None
    purpose: str | None
    calls: int
    failures: int
    estimated_cost_minor: int
    input_tokens: int
    output_tokens: int
    average_latency_ms: float | None
