from __future__ import annotations

import base64
import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.core.identity_security import ProductCurrentUser
from app.models.identity import UserProductProfile
from app.models.product_cv import ProductCvVersion
from app.models.product_interview import ProductInterview, ProductInterviewReport
from app.models.product_jobs import CandidateProfile, JobSearchResult, JobSearchRun, ProductJob
from app.models.product_recommendations import (
    JobApplication,
    JobApplicationEvent,
    JobInteraction,
    JobModerationCase,
    RecommendationDispatch,
    RecommendationMatch,
    RecommendationRun,
)
from app.schemas.product_recommendations import (
    CreateJobApplicationRequest,
    CreateRecommendationRunRequest,
    JobApplicationEventView,
    JobApplicationPage,
    JobApplicationView,
    JobInteractionView,
    RecommendationMatchPage,
    RecommendationMatchView,
    RecommendationRunView,
    UpdateJobApplicationRequest,
    UpsertJobInteractionRequest,
)
from app.services.product_job_search import ProductJobSearchService


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _request_hash(payload: Any) -> str:
    return hashlib.sha256(payload.model_dump_json(exclude_none=False).encode("utf-8")).hexdigest()


def _cursor(created_at: datetime, item_id: str) -> str:
    return base64.urlsafe_b64encode((created_at.isoformat() + "|" + item_id).encode()).decode().rstrip("=")


def _parse_cursor(value: str) -> tuple[datetime, str]:
    try:
        decoded = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4)).decode()
        timestamp, item_id = decoded.rsplit("|", 1)
        return datetime.fromisoformat(timestamp), item_id
    except (ValueError, UnicodeDecodeError) as exc:
        raise AppError(422, "INVALID_CURSOR", "Cursor is invalid") from exc


class ProductRecommendationService:
    _transitions = {
        "planned": {"applied", "withdrawn"},
        "applied": {"screening", "rejected", "withdrawn"},
        "screening": {"interviewing", "rejected", "withdrawn"},
        "interviewing": {"offered", "rejected", "withdrawn"},
        "offered": {"accepted", "rejected", "withdrawn"},
        "accepted": set(),
        "rejected": set(),
        "withdrawn": set(),
    }

    def __init__(self, db: Session) -> None:
        self.db = db

    def upsert_interaction(
        self,
        current: ProductCurrentUser,
        job_id: str,
        payload: UpsertJobInteractionRequest,
    ) -> JobInteraction:
        job = self.db.get(ProductJob, job_id)
        if job is None:
            raise AppError(404, "JOB_NOT_FOUND", "Job was not found")
        if payload.interaction_type == "reported" and not payload.reason_code:
            raise AppError(422, "REPORT_REASON_REQUIRED", "A reason code is required when reporting a job")
        interaction = self.db.scalar(
            select(JobInteraction).where(
                JobInteraction.user_id == current.id,
                JobInteraction.job_id == job.id,
                JobInteraction.interaction_type == payload.interaction_type,
            )
        )
        if interaction is None:
            interaction = JobInteraction(
                user_id=current.id,
                job_id=job.id,
                interaction_type=payload.interaction_type,
            )
            self.db.add(interaction)
            self.db.flush()
        interaction.reason_code = payload.reason_code
        interaction.note = payload.note
        interaction.context = payload.context
        if payload.interaction_type == "reported":
            moderation = self.db.scalar(select(JobModerationCase).where(JobModerationCase.interaction_id == interaction.id))
            if moderation is None:
                self.db.add(
                    JobModerationCase(
                        interaction_id=interaction.id,
                        job_id=job.id,
                        reporter_user_id=current.id,
                        reason_code=payload.reason_code,
                        details=payload.note,
                    )
                )
            elif moderation.status == "open":
                moderation.reason_code = payload.reason_code
                moderation.details = payload.note
        self.db.commit()
        self.db.refresh(interaction)
        return interaction

    @staticmethod
    def interaction_view(interaction: JobInteraction) -> JobInteractionView:
        return JobInteractionView(
            id=interaction.id,
            job_id=interaction.job_id,
            interaction_type=interaction.interaction_type,
            reason_code=interaction.reason_code,
            note=interaction.note,
            taxonomy_version=interaction.taxonomy_version,
            created_at=interaction.created_at,
            updated_at=interaction.updated_at,
        )

    def create_application(
        self,
        current: ProductCurrentUser,
        payload: CreateJobApplicationRequest,
        idempotency_key: str | None,
    ) -> JobApplication:
        payload_hash = _request_hash(payload)
        if idempotency_key:
            existing = self.db.scalar(
                select(JobApplication).where(
                    JobApplication.user_id == current.id,
                    JobApplication.idempotency_key == idempotency_key,
                )
            )
            if existing is not None:
                if existing.request_hash != payload_hash:
                    raise AppError(409, "IDEMPOTENCY_KEY_REUSED", "Idempotency-Key was already used with a different request")
                return existing
        job = self.db.get(ProductJob, payload.job_id)
        if job is None:
            raise AppError(404, "JOB_NOT_FOUND", "Job was not found")
        job_snapshot = ProductJobSearchService(self.db).job_view(job).model_dump(mode="json")
        application = JobApplication(
            user_id=current.id,
            job_id=job.id,
            status=payload.status,
            source_url=payload.source_url,
            notes=payload.notes,
            job_snapshot=job_snapshot,
            idempotency_key=idempotency_key,
            request_hash=payload_hash,
            applied_at=_utcnow() if payload.status != "planned" else None,
            closed_at=_utcnow() if payload.status in {"accepted", "rejected", "withdrawn"} else None,
        )
        self.db.add(application)
        self.db.flush()
        self.db.add(
            JobApplicationEvent(
                application_id=application.id,
                sequence=1,
                from_status=None,
                to_status=application.status,
                actor_user_id=current.id,
                metadata_json={"source": "application_created"},
            )
        )
        self.db.commit()
        self.db.refresh(application)
        return application

    def update_application(
        self,
        current: ProductCurrentUser,
        application_id: str,
        payload: UpdateJobApplicationRequest,
    ) -> JobApplication:
        application = self.db.scalar(select(JobApplication).where(JobApplication.id == application_id).with_for_update())
        if application is None or (current.role != "admin" and application.user_id != current.id):
            raise AppError(404, "JOB_APPLICATION_NOT_FOUND", "Job application was not found")
        if application.version != payload.expected_version:
            raise AppError(409, "APPLICATION_VERSION_CONFLICT", "Job application has changed; reload it before updating")
        if payload.status != application.status and payload.status not in self._transitions.get(application.status, set()):
            raise AppError(409, "INVALID_APPLICATION_TRANSITION", "The requested application status transition is not allowed")
        previous_status = application.status
        application.status = payload.status
        application.notes = payload.notes
        application.version += 1
        if payload.status == "applied" and application.applied_at is None:
            application.applied_at = _utcnow()
        if payload.status in {"accepted", "rejected", "withdrawn"}:
            application.closed_at = _utcnow()
        next_sequence = self.db.scalar(
            select(func.max(JobApplicationEvent.sequence)).where(JobApplicationEvent.application_id == application.id)
        ) or 0
        self.db.add(
            JobApplicationEvent(
                application_id=application.id,
                sequence=next_sequence + 1,
                from_status=previous_status,
                to_status=payload.status,
                actor_user_id=current.id,
                reason_code=payload.reason_code,
                metadata_json={"version": application.version},
            )
        )
        self.db.commit()
        self.db.refresh(application)
        return application

    def applications(
        self,
        current: ProductCurrentUser,
        application_status: str | None,
        cursor: str | None,
        limit: int,
    ) -> JobApplicationPage:
        query = select(JobApplication).where(JobApplication.user_id == current.id)
        if application_status:
            query = query.where(JobApplication.status == application_status)
        if cursor:
            created_at, item_id = _parse_cursor(cursor)
            query = query.where(
                (JobApplication.created_at < created_at)
                | ((JobApplication.created_at == created_at) & (JobApplication.id < item_id))
            )
        items = list(self.db.scalars(query.order_by(JobApplication.created_at.desc(), JobApplication.id.desc()).limit(limit + 1)))
        has_more = len(items) > limit
        items = items[:limit]
        return JobApplicationPage(
            items=[self.application_view(item) for item in items],
            next_cursor=_cursor(items[-1].created_at, items[-1].id) if has_more and items else None,
        )

    def application_view(self, application: JobApplication) -> JobApplicationView:
        events = list(
            self.db.scalars(
                select(JobApplicationEvent)
                .where(JobApplicationEvent.application_id == application.id)
                .order_by(JobApplicationEvent.sequence)
            )
        )
        return JobApplicationView(
            id=application.id,
            job_id=application.job_id,
            status=application.status,
            version=application.version,
            source_url=application.source_url,
            notes=application.notes,
            job_snapshot=application.job_snapshot,
            events=[
                JobApplicationEventView(
                    sequence=event.sequence,
                    from_status=event.from_status,
                    to_status=event.to_status,
                    actor_type=event.actor_type,
                    reason_code=event.reason_code,
                    created_at=event.created_at,
                )
                for event in events
            ],
            applied_at=application.applied_at,
            closed_at=application.closed_at,
            created_at=application.created_at,
            updated_at=application.updated_at,
        )

    def create_recommendation_run(
        self,
        current: ProductCurrentUser,
        payload: CreateRecommendationRunRequest,
        idempotency_key: str | None,
    ) -> RecommendationRun:
        payload_hash = _request_hash(payload)
        if idempotency_key:
            existing = self.db.scalar(
                select(RecommendationRun).where(
                    RecommendationRun.user_id == current.id,
                    RecommendationRun.idempotency_key == idempotency_key,
                )
            )
            if existing is not None:
                if existing.request_hash != payload_hash:
                    raise AppError(409, "IDEMPOTENCY_KEY_REUSED", "Idempotency-Key was already used with a different request")
                return existing
        search_run = None
        if payload.search_run_id:
            search_run = self.db.get(JobSearchRun, payload.search_run_id)
            if search_run is None or search_run.user_id != current.id:
                raise AppError(404, "JOB_SEARCH_RUN_NOT_FOUND", "Job search run was not found")
            if search_run.status != "completed":
                raise AppError(409, "JOB_SEARCH_NOT_READY", "Job search run is not completed")
        cv_version_id = payload.cv_version_id or (search_run.cv_version_id if search_run else None)
        candidate = self._candidate_profile(current, cv_version_id, search_run)
        assignment = {"ranking": "control", "explanation": "evidence-v1"}
        run = RecommendationRun(
            user_id=current.id,
            cv_version_id=cv_version_id,
            search_run_id=search_run.id if search_run else None,
            candidate_profile_id=candidate.id,
            candidate_profile_version=candidate.version,
            maximum_results=payload.maximum_results,
            experiment_assignment=assignment,
            input_snapshot={
                "candidate_profile": candidate.profile_json,
                "candidate_profile_id": candidate.id,
                "candidate_profile_version": candidate.version,
                "cv_version_id": candidate.cv_version_id,
                "preference_version": candidate.preference_version,
                "interview_report_ids": candidate.interview_report_ids,
                "search_run_id": search_run.id if search_run else None,
            },
            idempotency_key=idempotency_key,
            request_hash=payload_hash,
        )
        self.db.add(run)
        self.db.flush()
        self.db.add(RecommendationDispatch(run_id=run.id, payload={"run_id": run.id}))
        self.db.commit()
        self.db.refresh(run)
        self.publish_dispatch_for_run(run.id)
        return run

    def _candidate_profile(
        self,
        current: ProductCurrentUser,
        cv_version_id: str | None,
        search_run: JobSearchRun | None,
    ) -> CandidateProfile:
        if search_run and search_run.candidate_profile_id:
            candidate = self.db.get(CandidateProfile, search_run.candidate_profile_id)
            if candidate is not None:
                return candidate
        if cv_version_id:
            version = self.db.scalar(
                select(ProductCvVersion).where(ProductCvVersion.id == cv_version_id, ProductCvVersion.user_id == current.id)
            )
            if version is None:
                raise AppError(404, "CV_VERSION_NOT_FOUND", "CV version was not found")
        else:
            version = self.db.scalar(
                select(ProductCvVersion)
                .where(ProductCvVersion.user_id == current.id)
                .order_by(ProductCvVersion.created_at.desc())
            )
            if version is None:
                raise AppError(409, "CANDIDATE_PROFILE_INPUT_REQUIRED", "A confirmed CV version is required")
        product_profile = self.db.scalar(select(UserProductProfile).where(UserProductProfile.user_id == current.id))
        preference_version = product_profile.preference_version if product_profile else 1
        reports = list(
            self.db.scalars(
                select(ProductInterviewReport)
                .join(ProductInterview, ProductInterview.id == ProductInterviewReport.interview_id)
                .where(
                    ProductInterview.user_id == current.id,
                    ProductInterview.cv_version_id == version.id,
                    ProductInterviewReport.status == "ready",
                )
                .order_by(ProductInterviewReport.completed_at)
            )
        )
        report_ids = [report.id for report in reports]
        existing = self.db.scalar(
            select(CandidateProfile)
            .where(
                CandidateProfile.user_id == current.id,
                CandidateProfile.cv_version_id == version.id,
                CandidateProfile.preference_version == preference_version,
                CandidateProfile.interview_report_ids == report_ids,
                CandidateProfile.status == "fresh",
            )
            .order_by(CandidateProfile.version.desc())
        )
        if existing is not None:
            return existing
        fresh_profiles = list(
            self.db.scalars(
                select(CandidateProfile).where(CandidateProfile.user_id == current.id, CandidateProfile.status == "fresh")
            )
        )
        for profile in fresh_profiles:
            profile.status = "stale"
        content = version.content or {}
        skills = [item.get("name") for item in content.get("skills", []) if isinstance(item, dict) and item.get("name")]
        basics = content.get("basics", {})
        preferences = product_profile.job_preferences if product_profile else {}
        next_version = (self.db.scalar(select(func.max(CandidateProfile.version)).where(CandidateProfile.user_id == current.id)) or 0) + 1
        candidate = CandidateProfile(
            user_id=current.id,
            version=next_version,
            cv_version_id=version.id,
            preference_version=preference_version,
            preference_snapshot=preferences,
            interview_report_ids=report_ids,
            profile_json={
                "skills": skills,
                "summary": basics.get("summary"),
                "target_roles": preferences.get("roles", []),
                "locations": preferences.get("locations", []),
                "remote_modes": preferences.get("remote_modes", []),
                "interview_scores": [report.scores for report in reports],
            },
            generation_version="candidate-v2",
            status="fresh",
        )
        self.db.add(candidate)
        self.db.flush()
        return candidate

    def publish_dispatch_for_run(self, run_id: str) -> bool:
        dispatch = self.db.scalar(select(RecommendationDispatch).where(RecommendationDispatch.run_id == run_id).with_for_update())
        if dispatch is None or dispatch.status == "published":
            return True
        dispatch.attempts += 1
        try:
            from app.workers.tasks import execute_product_recommendation_task

            execute_product_recommendation_task.delay(run_id)
        except Exception as exc:
            dispatch.last_error = str(exc)[:1000]
            dispatch.available_at = _utcnow() + timedelta(seconds=min(300, 2 ** min(dispatch.attempts, 8)))
            self.db.commit()
            return False
        dispatch.status = "published"
        dispatch.published_at = _utcnow()
        dispatch.last_error = None
        self.db.commit()
        return True

    def publish_pending_dispatches(self, limit: int = 100) -> int:
        dispatches = list(
            self.db.scalars(
                select(RecommendationDispatch)
                .where(RecommendationDispatch.status == "pending", RecommendationDispatch.available_at <= _utcnow())
                .order_by(RecommendationDispatch.created_at)
                .limit(limit)
            )
        )
        return sum(1 for item in dispatches if self.publish_dispatch_for_run(item.run_id))

    def execute(self, run_id: str) -> None:
        run = self.db.scalar(select(RecommendationRun).where(RecommendationRun.id == run_id).with_for_update())
        if run is None or run.status == "completed":
            return
        run.status = "processing"
        run.started_at = run.started_at or _utcnow()
        self.db.commit()
        profile = run.input_snapshot.get("candidate_profile", {})
        candidate_skills = self._normalize(profile.get("skills", []))
        roles = self._normalize(profile.get("target_roles", []))
        locations = self._normalize(profile.get("locations", []))
        remote_modes = self._normalize(profile.get("remote_modes", []))
        if run.search_run_id:
            source_rows = list(
                self.db.execute(
                    select(ProductJob, JobSearchResult.final_score)
                    .join(JobSearchResult, JobSearchResult.job_id == ProductJob.id)
                    .where(JobSearchResult.run_id == run.search_run_id)
                    .order_by(JobSearchResult.rank)
                )
            )
        else:
            source_rows = [(job, 0.0) for job in self.db.scalars(
                select(ProductJob)
                .where(ProductJob.status == "active", ProductJob.verified_at.is_not(None))
                .order_by(ProductJob.last_seen_at.desc())
                .limit(500)
            )]
        scored: list[dict[str, Any]] = []
        for job, search_score in source_rows:
            job_skills = self._normalize(job.skills or [])
            matched = sorted(candidate_skills & job_skills)
            missing = sorted(job_skills - candidate_skills)[:10]
            skill_score = len(matched) / max(1, len(job_skills))
            role_score = 1.0 if any(role in job.title.casefold() for role in roles) else 0.0
            location_score = 1.0 if locations and any(value in (job.location_text or "").casefold() for value in locations) else 0.0
            remote_score = 1.0 if job.remote_mode.casefold() in remote_modes else 0.0
            preference_score = max(role_score, location_score, remote_score)
            normalized_search = max(0.0, min(1.0, float(search_score or 0.0)))
            final = max(0.0, min(1.0, 0.65 * skill_score + 0.2 * normalized_search + 0.15 * preference_score))
            scored.append({
                "job": job,
                "score": final,
                "breakdown": {
                    "skill_match": round(skill_score, 6),
                    "search_relevance": round(normalized_search, 6),
                    "preference_match": round(preference_score, 6),
                },
                "reasons": (["Matched skills: " + ", ".join(matched[:8])] if matched else []) + (["Matches a job preference"] if preference_score else []),
                "gaps": ["Skills to verify or develop: " + ", ".join(missing)] if missing else [],
                "evidence": {
                    "matched_candidate_skills": matched,
                    "unmatched_job_skills": missing,
                    "candidate_profile_version": run.candidate_profile_version,
                    "ranking_version": run.ranking_version,
                    "job_last_verified_at": job.verified_at.isoformat() if job.verified_at else None,
                },
            })
        scored.sort(key=lambda item: (-item["score"], item["job"].id))
        self.db.query(RecommendationMatch).filter(RecommendationMatch.run_id == run.id).delete()
        job_service = ProductJobSearchService(self.db)
        for rank, item in enumerate(scored[: run.maximum_results], 1):
            job = item["job"]
            self.db.add(
                RecommendationMatch(
                    run_id=run.id,
                    job_id=job.id,
                    rank=rank,
                    score=item["score"],
                    score_breakdown=item["breakdown"],
                    reasons=item["reasons"],
                    gaps=item["gaps"],
                    evidence=item["evidence"],
                    result_snapshot=job_service.job_view(job).model_dump(mode="json"),
                )
            )
        run.status = "completed"
        run.completed_at = _utcnow()
        self.db.commit()

    def get_run(self, current: ProductCurrentUser, run_id: str) -> RecommendationRun:
        run = self.db.get(RecommendationRun, run_id)
        if run is None or (current.role != "admin" and run.user_id != current.id):
            raise AppError(404, "RECOMMENDATION_RUN_NOT_FOUND", "Recommendation run was not found")
        return run

    @staticmethod
    def run_view(run: RecommendationRun) -> RecommendationRunView:
        return RecommendationRunView(
            id=run.id,
            status=run.status,
            cv_version_id=run.cv_version_id,
            search_run_id=run.search_run_id,
            candidate_profile_version=run.candidate_profile_version,
            ranking_version=run.ranking_version,
            experiment_assignment=run.experiment_assignment,
            created_at=run.created_at,
            started_at=run.started_at,
            completed_at=run.completed_at,
            error=run.error,
        )

    def results(self, current: ProductCurrentUser, run_id: str, cursor: str | None, limit: int) -> RecommendationMatchPage:
        run = self.get_run(current, run_id)
        query = select(RecommendationMatch).where(RecommendationMatch.run_id == run.id)
        if cursor:
            try:
                after_rank = int(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)).decode())
            except (ValueError, UnicodeDecodeError) as exc:
                raise AppError(422, "INVALID_CURSOR", "Cursor is invalid") from exc
            query = query.where(RecommendationMatch.rank > after_rank)
        items = list(self.db.scalars(query.order_by(RecommendationMatch.rank).limit(limit + 1)))
        has_more = len(items) > limit
        items = items[:limit]
        return RecommendationMatchPage(
            items=[
                RecommendationMatchView(
                    job=item.result_snapshot,
                    rank=item.rank,
                    score=item.score,
                    score_breakdown=item.score_breakdown,
                    reasons=item.reasons,
                    gaps=item.gaps,
                    evidence=item.evidence,
                )
                for item in items
            ],
            next_cursor=base64.urlsafe_b64encode(str(items[-1].rank).encode()).decode().rstrip("=") if has_more and items else None,
        )

    @staticmethod
    def _normalize(values: list[Any]) -> set[str]:
        return {" ".join(str(value).casefold().strip().split()) for value in values if str(value).strip()}
