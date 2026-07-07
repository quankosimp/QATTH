from pydantic import BaseModel, Field

from app.schemas.jobs import JobPostingRead


class MatchCreateRequest(BaseModel):
    cv_id: str
    interview_id: str | None = None
    limit: int = Field(default=10, ge=1, le=50)
    location: str | None = None
    working_model: str | None = None


class JobMatchItem(BaseModel):
    job: JobPostingRead
    score: float = Field(ge=0.0, le=1.0)
    fit_reasons: list[str] = Field(default_factory=list)
    gap_reasons: list[str] = Field(default_factory=list)
    cv_evidence: list[str] = Field(default_factory=list)
    interview_evidence: list[str] = Field(default_factory=list)
    apply_url: str


class MatchRunResult(BaseModel):
    match_id: str
    cv_id: str
    interview_id: str | None = None
    items: list[JobMatchItem]
