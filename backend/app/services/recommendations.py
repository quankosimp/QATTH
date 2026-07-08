from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.core.security import CurrentUser
from app.models.db import CVRecord, InterviewSession, JobPosting, MatchRun
from app.schemas.cv import CVProfile
from app.schemas.discovery import (
    CandidateDiscoveryProfileData,
    CandidateDiscoveryProfileRead,
    JobRecommendationResult,
)
from app.schemas.interview import InterviewResult
from app.schemas.jobs import JobPostingRead
from app.schemas.matching import JobMatchItem
from app.services.discovery import DiscoveryService
from app.services.embedding import EmbeddingService
from app.services.job_search import ExternalJobSearchService


class RecommendationService:
    def __init__(
        self,
        *,
        db: Session,
        current_user: CurrentUser | None = None,
        embedding: EmbeddingService | None = None,
        job_search: ExternalJobSearchService | None = None,
    ) -> None:
        self.db = db
        self.current_user = current_user
        self.embedding = embedding or EmbeddingService()
        self.job_search = job_search or ExternalJobSearchService(db=db)

    async def recommend_jobs(
        self,
        *,
        discovery_profile_id: str,
        limit: int,
        location: str | None,
        working_model: str | None,
        allow_stored_fallback: bool,
    ) -> JobRecommendationResult:
        discovery_service = DiscoveryService(db=self.db, current_user=self.current_user)
        record = discovery_service.get_record(profile_id=discovery_profile_id)
        discovery_data = CandidateDiscoveryProfileData.model_validate(record.profile_json)
        discovery_read = CandidateDiscoveryProfileRead(
            profile_id=record.id,
            cv_id=record.cv_id,
            interview_id=record.interview_id,
            source=record.source,
            profile=discovery_data,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )
        cv_record = self.db.get(CVRecord, record.cv_id)
        if not cv_record:
            raise AppError(status_code=404, code="CV_NOT_FOUND", message="CV was not found.")
        profile = CVProfile.model_validate(cv_record.parsed_profile or {})
        interview_result = self._load_interview_result(record.interview_id)

        jobs: list[JobPosting] = []
        external_search_used = False
        fallback_used = False
        search_queries = self._queries(discovery_data=discovery_data)

        if self.job_search.is_configured:
            external_search_used = True
            for query in search_queries[:3]:
                jobs.extend(
                    await self.job_search.search_and_store(
                        query=query, location=location, limit=max(limit, 10)
                    )
                )
        elif not allow_stored_fallback:
            raise AppError(
                status_code=503,
                code="EXTERNAL_JOB_SEARCH_NOT_CONFIGURED",
                message="External live job search is not configured.",
            )

        jobs = self._dedupe_jobs(jobs)
        if not jobs and allow_stored_fallback:
            fallback_used = True
            jobs = self._load_stored_jobs(location=location, working_model=working_model)

        if not jobs:
            raise AppError(
                status_code=404,
                code="NO_JOBS_AVAILABLE",
                message="No jobs are available for recommendation.",
            )

        candidate_text = self._candidate_text(
            profile=profile, discovery_data=discovery_data, interview_result=interview_result
        )
        candidate_embedding = self.embedding.embed(candidate_text)
        items = [
            self._score_job(
                job=job,
                profile=profile,
                discovery_data=discovery_data,
                interview_result=interview_result,
                candidate_embedding=candidate_embedding,
            )
            for job in jobs
        ]
        items.sort(key=lambda item: item.score, reverse=True)
        items = items[:limit]

        match_run = MatchRun(
            user_id=self.current_user.id if self.current_user else record.user_id,
            cv_id=record.cv_id,
            interview_id=record.interview_id,
            results=[item.model_dump(mode="json") for item in items],
        )
        self.db.add(match_run)
        self.db.commit()
        self.db.refresh(match_run)

        return JobRecommendationResult(
            discovery_profile=discovery_read,
            match_id=match_run.id,
            items=items,
            external_search_used=external_search_used,
            fallback_used=fallback_used,
            search_queries=search_queries,
        )

    def _load_interview_result(self, interview_id: str | None) -> InterviewResult | None:
        if not interview_id:
            return None
        session = self.db.get(InterviewSession, interview_id)
        return InterviewResult.model_validate(session.result) if session and session.result else None

    def _load_stored_jobs(
        self, *, location: str | None, working_model: str | None
    ) -> list[JobPosting]:
        statement = select(JobPosting)
        if location:
            statement = statement.where(JobPosting.location.ilike(f"%{location}%"))
        if working_model:
            statement = statement.where(JobPosting.working_model == working_model)
        return list(self.db.scalars(statement.limit(100)).all())

    def _score_job(
        self,
        *,
        job: JobPosting,
        profile: CVProfile,
        discovery_data: CandidateDiscoveryProfileData,
        interview_result: InterviewResult | None,
        candidate_embedding: list[float],
    ) -> JobMatchItem:
        if not job.embedding:
            job.embedding = self.embedding.embed(self._job_text(job))
            self.db.add(job)

        semantic = self.embedding.cosine_similarity(candidate_embedding, job.embedding or [])
        role_fit = self._role_fit(discovery_data=discovery_data, job=job)
        skill_overlap = self._skill_overlap(profile=profile, job=job)
        level_fit = self._level_fit(profile=profile, job=job)
        interview_signal = (interview_result.overall_score / 10.0) if interview_result else 0.5
        score = (
            0.35 * role_fit
            + 0.30 * semantic
            + 0.20 * skill_overlap
            + 0.10 * level_fit
            + 0.05 * interview_signal
        )
        score = max(0.0, min(1.0, score))

        profile_skills = {skill.name.lower() for skill in profile.skills}
        job_skills = {skill.lower() for skill in (job.skills or [])}
        common = sorted(profile_skills.intersection(job_skills))
        gaps = sorted(job_skills.difference(profile_skills))[:5]
        if not gaps:
            gaps = discovery_data.skill_gaps[:3]

        return JobMatchItem(
            job=self._to_job_read(job),
            score=round(score, 4),
            fit_reasons=[
                f"Discovery role fit: {role_fit:.2f}",
                f"Semantic similarity: {semantic:.2f}",
                f"Skill overlap: {', '.join(common) if common else 'low explicit overlap'}",
            ],
            gap_reasons=[f"Missing or weak signal: {gap}" for gap in gaps],
            cv_evidence=[
                profile.summary or "CV summary unavailable.",
                f"Detected skills: {', '.join(skill.name for skill in profile.skills[:8])}",
            ],
            interview_evidence=[
                interview_result.transcript_summary if interview_result else discovery_data.headline
            ],
            apply_url=job.source_url,
        )

    def _role_fit(self, *, discovery_data: CandidateDiscoveryProfileData, job: JobPosting) -> float:
        job_text = " ".join([job.title, job.jd_text]).lower()
        best = 0.0
        for role in discovery_data.recommended_roles:
            tokens = self._tokens(role.role)
            keyword_tokens = {token for keyword in role.search_keywords for token in self._tokens(keyword)}
            all_tokens = tokens.union(keyword_tokens)
            if not all_tokens:
                continue
            overlap = sum(1 for token in all_tokens if token in job_text) / len(all_tokens)
            best = max(best, min(1.0, 0.5 * role.score + 0.5 * overlap))
        return best or 0.4

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
        if level in {"internship", "fresher", "junior"} and seniority in {
            "student",
            "intern",
            "fresher",
            "junior",
        }:
            return 1.0
        if level == "senior":
            return 0.2
        return 0.5

    def _candidate_text(
        self,
        *,
        profile: CVProfile,
        discovery_data: CandidateDiscoveryProfileData,
        interview_result: InterviewResult | None,
    ) -> str:
        skills = ", ".join(skill.name for skill in profile.skills)
        roles = ", ".join(role.role for role in discovery_data.recommended_roles)
        projects = " ".join(project.description or project.name for project in profile.projects)
        interview = interview_result.transcript_summary if interview_result else ""
        return " ".join([profile.summary or "", skills, roles, projects, discovery_data.headline, interview])

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

    def _queries(self, *, discovery_data: CandidateDiscoveryProfileData) -> list[str]:
        if discovery_data.search_queries:
            return discovery_data.search_queries[:6]
        return [f"{role.role} jobs Vietnam" for role in discovery_data.recommended_roles[:3]]

    def _dedupe_jobs(self, jobs: list[JobPosting]) -> list[JobPosting]:
        seen: set[str] = set()
        unique: list[JobPosting] = []
        for job in jobs:
            if job.id in seen:
                continue
            seen.add(job.id)
            unique.append(job)
        return unique

    def _tokens(self, text: str) -> set[str]:
        return {token for token in re.split(r"[^a-z0-9+#.]+", text.lower()) if len(token) >= 3}

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
