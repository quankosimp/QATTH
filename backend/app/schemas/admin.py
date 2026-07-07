from datetime import datetime

from pydantic import BaseModel

from app.schemas.auth import UserRead
from app.schemas.ai import ModelRunRead
from app.schemas.jobs import JobPostingRead


class AdminOverview(BaseModel):
    users_total: int
    cvs_total: int
    cvs_pending_review: int
    interviews_total: int
    interviews_completed: int
    jobs_total: int
    crawl_runs_failed: int


class AdminCVScanRead(BaseModel):
    cv_id: str
    user_id: str | None = None
    original_file_name: str
    scan_status: str
    warnings_count: int
    failure_reason: str | None = None
    created_at: datetime | None = None


class AdminInterviewRead(BaseModel):
    interview_id: str
    user_id: str | None = None
    cv_id: str
    target_role: str
    status: str
    failure_reason: str | None = None
    created_at: datetime | None = None
    ended_at: datetime | None = None


class AdminCrawlRunRead(BaseModel):
    crawl_run_id: str
    source: str
    query: str | None = None
    status: str
    jobs_found: int
    failure_reason: str | None = None
    created_at: datetime | None = None


class UserStatusUpdate(BaseModel):
    is_active: bool


class AdminUserList(BaseModel):
    items: list[UserRead]
    total: int


class AdminCVScanList(BaseModel):
    items: list[AdminCVScanRead]
    total: int


class AdminInterviewList(BaseModel):
    items: list[AdminInterviewRead]
    total: int


class AdminCrawlRunList(BaseModel):
    items: list[AdminCrawlRunRead]
    total: int


class AdminJobList(BaseModel):
    items: list[JobPostingRead]
    total: int


class AdminModelRunList(BaseModel):
    items: list[ModelRunRead]
    total: int
