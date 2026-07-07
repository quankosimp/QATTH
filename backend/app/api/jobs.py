from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.errors import AppError
from app.models.db import JobPosting
from app.schemas.common import APIResponse, make_response
from app.schemas.jobs import CrawlRunCreateRequest, CrawlRunResult, JobListResult, JobPostingRead
from app.services.job_crawler import JobCrawlerService

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.post("/crawl-runs", response_model=APIResponse[CrawlRunResult])
async def create_crawl_run(
    request: Request,
    payload: CrawlRunCreateRequest,
    db: Session = Depends(get_db),
) -> APIResponse[CrawlRunResult]:
    run = await JobCrawlerService(db=db).run(
        source=payload.source,
        query=payload.query,
        max_pages=payload.max_pages,
    )
    result = CrawlRunResult(
        crawl_run_id=run.id,
        source=run.source,
        status=run.status,
        jobs_found=run.jobs_found,
        failure_reason=run.failure_reason,
    )
    return make_response(result, request=request)


@router.get("", response_model=APIResponse[JobListResult])
def list_jobs(
    request: Request,
    q: str | None = None,
    skill: str | None = None,
    level: str | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> APIResponse[JobListResult]:
    statement = select(JobPosting)
    count_statement = select(func.count()).select_from(JobPosting)

    if q:
        statement = statement.where(JobPosting.title.ilike(f"%{q}%"))
        count_statement = count_statement.where(JobPosting.title.ilike(f"%{q}%"))
    if level:
        statement = statement.where(JobPosting.level == level)
        count_statement = count_statement.where(JobPosting.level == level)

    jobs = list(db.scalars(statement.offset(offset).limit(limit)).all())
    if skill:
        skill_lower = skill.lower()
        jobs = [job for job in jobs if skill_lower in {item.lower() for item in (job.skills or [])}]

    total = db.scalar(count_statement) or len(jobs)
    result = JobListResult(
        items=[_to_read(job) for job in jobs],
        total=total,
        limit=limit,
        offset=offset,
    )
    return make_response(result, request=request)


@router.get("/{job_id}", response_model=APIResponse[JobPostingRead])
def get_job(
    request: Request,
    job_id: str,
    db: Session = Depends(get_db),
) -> APIResponse[JobPostingRead]:
    job = db.get(JobPosting, job_id)
    if not job:
        raise AppError(
            status_code=404,
            code="JOB_NOT_FOUND",
            message="Job was not found.",
            details={"job_id": job_id},
        )
    return make_response(_to_read(job), request=request)


def _to_read(job: JobPosting) -> JobPostingRead:
    return JobPostingRead(
        job_id=job.id,
        source=job.source,
        external_id=job.external_id,
        source_url=job.source_url,
        title=job.title,
        company=job.company,
        location=job.location,
        working_model=job.working_model,
        level=job.level,
        salary_range=job.salary_range,
        skills=job.skills or [],
        jd_text=job.jd_text,
        posted_at=job.posted_at,
        crawled_at=job.crawled_at,
    )
