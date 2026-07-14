from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class CreateDeletionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirmation: Literal["DELETE"]
    reason: str | None = Field(default=None, max_length=500)


class PrivacySignedUrl(BaseModel):
    url: str
    expires_at: datetime


class PrivacyRequestView(BaseModel):
    id: str
    type: Literal["export", "deletion"]
    status: Literal["queued", "processing", "awaiting_retention", "completed", "failed", "cancelled"]
    download: PrivacySignedUrl | None
    retention_exceptions: list[str]
    requested_at: datetime
    completed_at: datetime | None
