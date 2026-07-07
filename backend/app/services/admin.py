from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.models.db import CVRecord, CrawlRun, InterviewSession, JobPosting, User
from app.services.model_runs import ModelRunService
from app.services.audit import AuditService
from app.schemas.admin import (
    AdminCVScanList,
    AdminCVScanRead,
    AdminCrawlRunList,
    AdminCrawlRunRead,
    AdminInterviewList,
    AdminInterviewRead,
    AdminJobList,
    AdminModelRunList,
    AdminOverview,
    AdminUserList,
)
from app.schemas.auth import UserRead
from app.schemas.jobs import JobPostingRead


class AdminService:
    def __init__(self, *, db: Session) -> None:
        self.db = db

    def overview(self) -> AdminOverview:
        return AdminOverview(
            users_total=self._count(User),
            cvs_total=self._count(CVRecord),
            cvs_pending_review=self._count_where(CVRecord, CVRecord.scan_status == "pending_review"),
            interviews_total=self._count(InterviewSession),
            interviews_completed=self._count_where(InterviewSession, InterviewSession.status == "completed"),
            jobs_total=self._count(JobPosting),
            crawl_runs_failed=self._count_where(CrawlRun, CrawlRun.status == "failed"),
        )

    def list_users(self) -> AdminUserList:
        users = list(self.db.scalars(select(User).order_by(User.created_at.desc())).all())
        return AdminUserList(
            items=[
                UserRead(
                    user_id=user.id,
                    email=user.email,
                    full_name=user.full_name,
                    role=user.role,
                    is_active=user.is_active,
                    created_at=user.created_at,
                )
                for user in users
            ],
            total=len(users),
        )

    def update_user_status(self, *, user_id: str, is_active: bool) -> UserRead:
        user = self.db.get(User, user_id)
        if not user:
            raise AppError(status_code=404, code="USER_NOT_FOUND", message="User was not found.")
        user.is_active = is_active
        AuditService(db=self.db).record(
            actor_user_id=None,
            action="admin.update_user_status",
            resource_type="user",
            resource_id=user_id,
            metadata={"is_active": is_active},
        )
        self.db.commit()
        self.db.refresh(user)
        return UserRead(
            user_id=user.id,
            email=user.email,
            full_name=user.full_name,
            role=user.role,
            is_active=user.is_active,
            created_at=user.created_at,
        )

    def list_cv_scans(self, *, status: str | None = None) -> AdminCVScanList:
        statement = select(CVRecord)
        if status:
            statement = statement.where(CVRecord.scan_status == status)
        records = list(self.db.scalars(statement.order_by(CVRecord.created_at.desc())).all())
        return AdminCVScanList(
            items=[
                AdminCVScanRead(
                    cv_id=record.id,
                    user_id=record.user_id,
                    original_file_name=record.original_file_name,
                    scan_status=record.scan_status,
                    warnings_count=len(record.warnings or []),
                    failure_reason=record.failure_reason,
                    created_at=record.created_at,
                )
                for record in records
            ],
            total=len(records),
        )

    def list_interviews(self, *, status: str | None = None) -> AdminInterviewList:
        statement = select(InterviewSession)
        if status:
            statement = statement.where(InterviewSession.status == status)
        sessions = list(self.db.scalars(statement.order_by(InterviewSession.created_at.desc())).all())
        return AdminInterviewList(
            items=[
                AdminInterviewRead(
                    interview_id=session.id,
                    user_id=session.user_id,
                    cv_id=session.cv_id,
                    target_role=session.target_role,
                    status=session.status,
                    failure_reason=session.failure_reason,
                    created_at=session.created_at,
                    ended_at=session.ended_at,
                )
                for session in sessions
            ],
            total=len(sessions),
        )

    def list_crawl_runs(self, *, status: str | None = None) -> AdminCrawlRunList:
        statement = select(CrawlRun)
        if status:
            statement = statement.where(CrawlRun.status == status)
        runs = list(self.db.scalars(statement.order_by(CrawlRun.created_at.desc())).all())
        return AdminCrawlRunList(
            items=[
                AdminCrawlRunRead(
                    crawl_run_id=run.id,
                    source=run.source,
                    query=run.query,
                    status=run.status,
                    jobs_found=run.jobs_found,
                    failure_reason=run.failure_reason,
                    created_at=run.created_at,
                )
                for run in runs
            ],
            total=len(runs),
        )

    def list_jobs(self, *, source: str | None = None) -> AdminJobList:
        statement = select(JobPosting)
        if source:
            statement = statement.where(JobPosting.source == source)
        jobs = list(self.db.scalars(statement.order_by(JobPosting.crawled_at.desc())).all())
        return AdminJobList(
            items=[
                JobPostingRead(
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
                for job in jobs
            ],
            total=len(jobs),
        )

    def list_model_runs(self, *, status: str | None = None, run_type: str | None = None) -> AdminModelRunList:
        result = ModelRunService(db=self.db).list(status=status, run_type=run_type)
        return AdminModelRunList(items=result.items, total=result.total)

    def retry_model_run(self, *, run_id: str):
        return ModelRunService(db=self.db).mark_retry_requested(run_id=run_id)

    def _count(self, model) -> int:
        return self.db.scalar(select(func.count()).select_from(model)) or 0

    def _count_where(self, model, predicate) -> int:
        return self.db.scalar(select(func.count()).select_from(model).where(predicate)) or 0
