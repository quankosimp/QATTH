from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class BackgroundTaskRead(BaseModel):
    task_id: str
    celery_task_id: str | None = None
    user_id: str | None = None
    task_type: str
    status: str
    resource_type: str | None = None
    resource_id: str | None = None
    attempts: int
    max_attempts: int
    result_payload: dict[str, Any] | None = None
    error_payload: dict[str, Any] | None = None
    created_at: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None


class BackgroundTaskList(BaseModel):
    items: list[BackgroundTaskRead]
    total: int


class BackgroundTaskCreate(BaseModel):
    task_type: str = Field(default="noop")
    resource_type: str | None = None
    resource_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
