from datetime import datetime

from pydantic import BaseModel, Field


class CrawlRunCreateRequest(BaseModel):
    source: str = Field(default="seed", description="seed or itviec")
    query: str | None = Field(default="it")
    max_pages: int = Field(default=1, ge=1, le=5)


class CrawlRunResult(BaseModel):
    crawl_run_id: str
    source: str
    status: str
    jobs_found: int
    failure_reason: str | None = None


class JobPostingRead(BaseModel):
    job_id: str
    source: str
    external_id: str
    source_url: str
    title: str
    company: str
    location: str | None = None
    working_model: str | None = None
    level: str | None = None
    salary_range: str | None = None
    skills: list[str] = Field(default_factory=list)
    jd_text: str
    posted_at: str | None = None
    crawled_at: datetime | None = None


class JobListResult(BaseModel):
    items: list[JobPostingRead]
    total: int
    limit: int
    offset: int
