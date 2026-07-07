from pydantic import BaseModel, Field


class ReadinessCheck(BaseModel):
    name: str
    ok: bool
    detail: str | None = None


class ReadinessResult(BaseModel):
    ready: bool
    checks: list[ReadinessCheck] = Field(default_factory=list)


class LivenessResult(BaseModel):
    alive: bool
    service: str


class OpsMetrics(BaseModel):
    users_total: int
    cvs_total: int
    cvs_pending_review: int
    interviews_total: int
    interviews_completed: int
    jobs_total: int
    crawl_runs_failed: int
