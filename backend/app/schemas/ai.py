from datetime import datetime
from typing import Any

from pydantic import BaseModel


class ModelRunRead(BaseModel):
    run_id: str
    user_id: str | None = None
    run_type: str
    provider: str
    model: str
    status: str
    prompt_version_id: str | None = None
    input_hash: str | None = None
    output_schema: str | None = None
    latency_ms: int | None = None
    output_json: dict[str, Any] | None = None
    error_message: str | None = None
    created_at: datetime | None = None
    completed_at: datetime | None = None


class ModelRunList(BaseModel):
    items: list[ModelRunRead]
    total: int


class PromptVersionRead(BaseModel):
    version_id: str
    template_key: str
    version: str
    model: str
    is_active: bool
