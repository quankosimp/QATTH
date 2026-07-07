from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.core.security import CurrentUser
from app.models.db import CVRecord, InterviewSession, JobPosting, MatchRun
from app.schemas.cv import CVProfile
from app.schemas.interview import InterviewResult
from app.schemas.jobs import JobPostingRead
from app.schemas.matching import JobMatchItem, MatchRunResult
from app.services.embedding import EmbeddingService


class MatchingService:
    def __init__(
        self,
        *,
        db: Session,
        current_user: CurrentUser | None = None,
        embedding: EmbeddingService | None = None,
    ) -> None:
        self.db = db
        self.current_user = current_user
        self.embedding = embedding or EmbeddingService()

    def create_match(
        self,
        *,
        cv_id: str,
        interview_id: str | None,
        limit: int,
        location: str | None,
        working_model: str | None,
    ) -> MatchRunResult:
        cv_record = self.db.get(CVRecord, cv_id)
        if not cv_record or cv_record.scan_status != "completed":
            raise AppError(
                status_code=404,
                code="CV_NOT_READY",
                message="CV was not found or has not been scanned successfully.",
            )
        self._ensure_owner(owner_id=cv_record.user_id, resource="CV")

        profile = CVProfile.model_validate(cv_record.parsed_profile or {})
        interview_result = self._load_interview_result(interview_id)
        jobs = self._load_jobs(location=location, working_model=working_model)

        if not jobs:
            raise AppError(
                status_code=404,
                code="NO_JOBS_AVAILABLE",
                message="No jobs available. Run /v1/jobs/crawl-runs first.",
            )

        candidate_text = self._candidate_text(profile=profile, interview_result=interview_result)
        candidate_embedding = self.embedding.embed(candidate_text)
        items = [
            self._score_job(
                job=job,
                profile=profile,
                interview_result=interview_result,
                candidate_embedding=candidate_embedding,
            )
            for job in jobs
        ]
        items.sort(key=lambda item: item.score, reverse=True)
        items = items[:limit]

        match_run = MatchRun(
            user_id=self.current_user.id if self.current_user else cv_record.user_id,
            cv_id=cv_id,
            interview_id=interview_id,
            results=[item.model_dump(mode="json") for item in items],
        )
        self.db.add(match_run)
        self.db.commit()
        self.db.refresh(match_run)

        return MatchRunResult(
            match_id=match_run.id,
            cv_id=cv_id,
            interview_id=interview_id,
            items=items,
        )

    def get_match(self, *, match_id: str) -> MatchRunResult:
        match_run = self.db.get(MatchRun, match_id)
        if not match_run:
            raise AppError(
                status_code=404,
                code="MATCH_NOT_FOUND",
                message="Match run was not found.",
            )
        self._ensure_owner(owner_id=match_run.user_id, resource="Match run")
        return MatchRunResult(
            match_id=match_run.id,
            cv_id=match_run.cv_id,
            interview_id=match_run.interview_id,
            items=[JobMatchItem.model_validate(item) for item in match_run.results],
        )

    def _load_interview_result(self, interview_id: str | None) -> InterviewResult | None:
        if not interview_id:
            return None
        session = self.db.get(InterviewSession, interview_id)
        if not session:
            raise AppError(
                status_code=404,
                code="INTERVIEW_NOT_FOUND",
                message="Interview was not found.",
            )
        self._ensure_owner(owner_id=session.user_id, resource="Interview")
        return InterviewResult.model_validate(session.result) if session.result else None

    def _ensure_owner(self, *, owner_id: str | None, resource: str) -> None:
        if self.current_user and not self.current_user.is_admin and owner_id not in {None, self.current_user.id}:
            raise AppError(
                status_code=404,
                code=f"{resource.upper().replace(' ', '_')}_NOT_FOUND",
                message=f"{resource} was not found.",
            )

    def _load_jobs(self, *, location: str | None, working_model: str | None) -> list[JobPosting]:
        statement = select(JobPosting)
        if location:
            statement = statement.where(JobPosting.location.ilike(f"%{location}%"))
        if working_model:
            statement = statement.where(JobPosting.working_model == working_model)
        return list(self.db.scalars(statement).all())

    def _score_job(
        self,
        *,
        job: JobPosting,
        profile: CVProfile,
        interview_result: InterviewResult | None,
        candidate_embedding: list[float],
    ) -> JobMatchItem:
        if not job.embedding:
            job.embedding = self.embedding.embed(self._job_text(job))
            self.db.add(job)

        semantic = self.embedding.cosine_similarity(candidate_embedding, job.embedding or [])
        skill_overlap = self._skill_overlap(profile=profile, job=job)
        level_fit = self._level_fit(profile=profile, job=job)
        interview_signal = (interview_result.overall_score / 10.0) if interview_result else 0.5
        score = 0.50 * semantic + 0.25 * skill_overlap + 0.15 * level_fit + 0.10 * interview_signal
        score = max(0.0, min(1.0, score))

        profile_skills = {skill.name.lower() for skill in profile.skills}
        job_skills = {skill.lower() for skill in (job.skills or [])}
        common = sorted(profile_skills.intersection(job_skills))
        gaps = sorted(job_skills.difference(profile_skills))[:5]

        return JobMatchItem(
            job=self._to_job_read(job),
            score=round(score, 4),
            fit_reasons=[
                f"Semantic similarity score: {semantic:.2f}",
                f"Skill overlap: {', '.join(common) if common else 'low explicit overlap'}",
                f"Level fit signal: {level_fit:.2f}",
            ],
            gap_reasons=[f"Missing or weak signal: {gap}" for gap in gaps],
            cv_evidence=[
                profile.summary or "CV summary unavailable.",
                f"Detected skills: {', '.join(skill.name for skill in profile.skills[:8])}",
            ],
            interview_evidence=[
                interview_result.transcript_summary if interview_result else "No interview result provided."
            ],
            apply_url=job.source_url,
        )

    def _skill_overlap(self, *, profile: CVProfile, job: JobPosting) -> float:
        profile_skills = {skill.name.lower() for skill in profile.skills}
        job_skills = {skill.lower() for skill in (job.skills or [])}
        if not job_skills:
            return 0.0
        return len(profile_skills.intersection(job_skills)) / len(job_skills)

    def _level_fit(self, *, profile: CVProfile, job: JobPosting) -> float:
        level = (job.level or "").lower()
        seniority = profile.seniority_estimate.lower()
        if not level:
            return 0.6
        if level in {"internship", "fresher", "junior"} and seniority in {"student", "intern", "fresher"}:
            return 1.0
        if level == "junior" and seniority == "junior":
            return 1.0
        if level == "senior":
            return 0.2
        return 0.5

    def _candidate_text(self, *, profile: CVProfile, interview_result: InterviewResult | None) -> str:
        skills = ", ".join(skill.name for skill in profile.skills)
        projects = " ".join(project.description or project.name for project in profile.projects)
        interview = interview_result.transcript_summary if interview_result else ""
        return " ".join(
            [
                profile.summary or "",
                skills,
                projects,
                " ".join(profile.target_roles),
                interview,
            ]
        )

    def _job_text(self, job: JobPosting) -> str:
        return " ".join(
            [
                job.title,
                job.company,
                job.location or "",
                job.level or "",
                " ".join(job.skills or []),
                job.jd_text,
            ]
        )

    def _to_job_read(self, job: JobPosting) -> JobPostingRead:
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
