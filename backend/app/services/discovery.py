from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.core.security import CurrentUser
from app.models.db import CandidateDiscoveryProfile, CVRecord, InterviewSession, UserJobPreference
from app.schemas.cv import CVProfile
from app.schemas.discovery import (
    CandidateDiscoveryProfileData,
    CandidateDiscoveryProfileList,
    CandidateDiscoveryProfileRead,
    RoleFitRecommendation,
)
from app.schemas.interview import InterviewResult
from app.services.gemini import GeminiService
from app.services.model_runs import ModelRunService


class DiscoveryService:
    def __init__(
        self,
        *,
        db: Session,
        current_user: CurrentUser | None = None,
        gemini: GeminiService | None = None,
    ) -> None:
        self.db = db
        self.current_user = current_user
        self.gemini = gemini or GeminiService()

    async def create(
        self,
        *,
        cv_id: str,
        interview_id: str | None,
        language: str,
    ) -> CandidateDiscoveryProfileRead:
        cv_record = self._get_cv(cv_id)
        profile = CVProfile.model_validate(cv_record.parsed_profile or {})
        session, interview_result = self._load_interview(
            interview_id=interview_id, cv_id=cv_record.id
        )
        preference = self._load_preferences()

        source = "fallback"
        profile_data = self._fallback_profile(
            profile=profile, interview_result=interview_result, preference=preference
        )

        if self.gemini.is_configured:
            timer = ModelRunService(db=self.db).start(
                user_id=cv_record.user_id,
                run_type="candidate_discovery",
                provider="gemini",
                model=self.gemini.settings.gemini_evaluation_model,
                input_payload={
                    "cv_id": cv_record.id,
                    "interview_id": session.id if session else None,
                    "language": language,
                },
                output_schema="CandidateDiscoveryProfileData",
            )
            try:
                payload = await self.gemini.generate_discovery_profile(
                    profile=profile.model_dump(mode="json"),
                    interview_result=(
                        interview_result.model_dump(mode="json") if interview_result else None
                    ),
                    preferences=self._preference_payload(preference),
                    language=language,
                    response_schema=CandidateDiscoveryProfileData,
                )
                profile_data = CandidateDiscoveryProfileData.model_validate(payload)
                source = "gemini"
                timer.complete(output_json=profile_data.model_dump(mode="json"))
            except Exception as exc:
                timer.fail(error=str(exc))
                raise

        record = CandidateDiscoveryProfile(
            user_id=self.current_user.id if self.current_user else cv_record.user_id,
            cv_id=cv_record.id,
            interview_id=session.id if session else None,
            source=source,
            profile_json=profile_data.model_dump(mode="json"),
            recommended_roles=[
                item.model_dump(mode="json") for item in profile_data.recommended_roles
            ],
            skill_gaps=profile_data.skill_gaps,
            search_queries=profile_data.search_queries,
            confidence=profile_data.confidence,
        )
        self.db.add(record)
        self.db.commit()
        self.db.refresh(record)
        return self._to_read(record)

    def list(self) -> CandidateDiscoveryProfileList:
        statement = select(CandidateDiscoveryProfile).order_by(
            CandidateDiscoveryProfile.created_at.desc()
        )
        if self.current_user and not self.current_user.is_admin:
            statement = statement.where(CandidateDiscoveryProfile.user_id == self.current_user.id)
        records = list(self.db.scalars(statement).all())
        return CandidateDiscoveryProfileList(
            items=[self._to_read(record) for record in records], total=len(records)
        )

    def get(self, *, profile_id: str) -> CandidateDiscoveryProfileRead:
        record = self.db.get(CandidateDiscoveryProfile, profile_id)
        if not record:
            raise AppError(
                status_code=404,
                code="DISCOVERY_PROFILE_NOT_FOUND",
                message="Discovery profile was not found.",
            )
        self._ensure_owner(owner_id=record.user_id, resource="Discovery profile")
        return self._to_read(record)

    def get_record(self, *, profile_id: str) -> CandidateDiscoveryProfile:
        record = self.db.get(CandidateDiscoveryProfile, profile_id)
        if not record:
            raise AppError(
                status_code=404,
                code="DISCOVERY_PROFILE_NOT_FOUND",
                message="Discovery profile was not found.",
            )
        self._ensure_owner(owner_id=record.user_id, resource="Discovery profile")
        return record

    def _get_cv(self, cv_id: str) -> CVRecord:
        cv_record = self.db.get(CVRecord, cv_id)
        if not cv_record or cv_record.scan_status != "completed":
            raise AppError(
                status_code=404,
                code="CV_NOT_READY",
                message="CV was not found or has not been reviewed successfully.",
            )
        self._ensure_owner(owner_id=cv_record.user_id, resource="CV")
        return cv_record

    def _load_interview(
        self, *, interview_id: str | None, cv_id: str
    ) -> tuple[InterviewSession | None, InterviewResult | None]:
        if not interview_id:
            return None, None
        session = self.db.get(InterviewSession, interview_id)
        if not session:
            raise AppError(
                status_code=404,
                code="INTERVIEW_NOT_FOUND",
                message="Interview was not found.",
            )
        self._ensure_owner(owner_id=session.user_id, resource="Interview")
        if session.cv_id != cv_id:
            raise AppError(
                status_code=409,
                code="INTERVIEW_CV_MISMATCH",
                message="Interview does not belong to the selected CV.",
            )
        if session.status != "completed" or not session.result:
            raise AppError(
                status_code=409,
                code="INTERVIEW_NOT_COMPLETED",
                message="Interview must be completed before creating a discovery profile.",
                details={"status": session.status},
            )
        return session, InterviewResult.model_validate(session.result)

    def _load_preferences(self) -> UserJobPreference | None:
        if not self.current_user:
            return None
        return self.db.scalar(
            select(UserJobPreference).where(UserJobPreference.user_id == self.current_user.id)
        )

    def _ensure_owner(self, *, owner_id: str | None, resource: str) -> None:
        if self.current_user and not self.current_user.is_admin and owner_id not in {None, self.current_user.id}:
            raise AppError(
                status_code=404,
                code=f"{resource.upper().replace(' ', '_')}_NOT_FOUND",
                message=f"{resource} was not found.",
            )

    def _fallback_profile(
        self,
        *,
        profile: CVProfile,
        interview_result: InterviewResult | None,
        preference: UserJobPreference | None,
    ) -> CandidateDiscoveryProfileData:
        skills = [skill.name for skill in profile.skills]
        skill_set = {skill.lower() for skill in skills}
        preferred_roles = list(profile.target_roles or [])
        if preference and preference.target_roles:
            preferred_roles.extend(role for role in preference.target_roles if role not in preferred_roles)
        if interview_result:
            preferred_roles.extend(
                role for role in interview_result.recommended_roles if role not in preferred_roles
            )

        role_candidates = self._infer_role_candidates(skill_set=skill_set, preferred_roles=preferred_roles)
        skill_gaps = list(interview_result.skill_gaps if interview_result else [])[:5]
        if not skill_gaps:
            skill_gaps = ["Testing fundamentals", "Project impact metrics", "Interview storytelling"]
        location = self._preferred_location(preference=preference)
        search_queries = self._build_queries(roles=role_candidates, location=location)

        return CandidateDiscoveryProfileData(
            headline=profile.summary or "Entry-level IT candidate seeking suitable roles.",
            current_level=profile.seniority_estimate,
            strongest_signals=[
                f"Skill: {skill}" for skill in skills[:5]
            ] + [project.name for project in profile.projects[:2]],
            preferred_roles=preferred_roles[:5],
            recommended_roles=role_candidates,
            not_recommended_roles=[
                RoleFitRecommendation(
                    role="Senior Software Engineer",
                    score=0.2,
                    reason="Current evidence is more suitable for internship, fresher, or junior roles.",
                    evidence=["Seniority estimate: " + profile.seniority_estimate],
                    search_keywords=["senior software engineer"],
                )
            ],
            skill_gaps=skill_gaps,
            search_queries=search_queries,
            practice_plan=[
                "Prepare a 2-minute project explanation with problem, architecture, and result.",
                "Add measurable outcomes to CV bullets where possible.",
                "Practice answering role-fit questions using CV evidence.",
            ],
            evidence=[profile.summary or "CV summary unavailable."],
            confidence=max(profile.raw_confidence, 0.45),
        )

    def _infer_role_candidates(
        self, *, skill_set: set[str], preferred_roles: list[str]
    ) -> list[RoleFitRecommendation]:
        definitions = [
            (
                "Junior Python Backend Developer",
                {"python", "fastapi", "django", "sql", "postgresql"},
                ["python", "backend", "fastapi", "sql"],
            ),
            (
                "Frontend Developer Intern",
                {"javascript", "typescript", "react", "vue", "html", "css"},
                ["frontend", "react", "javascript", "intern"],
            ),
            (
                "Data Analyst Intern",
                {"sql", "python", "excel", "power bi", "tableau"},
                ["data analyst", "sql", "python", "intern"],
            ),
            (
                "QA Engineer Intern",
                {"testing", "selenium", "postman", "qa"},
                ["qa engineer", "testing", "intern"],
            ),
        ]
        roles: list[RoleFitRecommendation] = []
        for role, required, keywords in definitions:
            overlap = sorted(skill_set.intersection(required))
            if overlap or role in preferred_roles:
                score = min(1.0, 0.45 + (len(overlap) / max(len(required), 1)))
                roles.append(
                    RoleFitRecommendation(
                        role=role,
                        score=round(score, 2),
                        reason="Matches current CV/interview evidence." if overlap else "User preference signal.",
                        evidence=[f"Matched skills: {', '.join(overlap)}"] if overlap else preferred_roles[:2],
                        search_keywords=keywords,
                    )
                )
        if not roles:
            fallback = preferred_roles[0] if preferred_roles else "IT Intern"
            roles.append(
                RoleFitRecommendation(
                    role=fallback,
                    score=0.5,
                    reason="Fallback role based on limited available evidence.",
                    evidence=["CV has limited explicit role signals."],
                    search_keywords=[fallback.lower(), "intern"],
                )
            )
        roles.sort(key=lambda item: item.score, reverse=True)
        return roles[:5]

    def _build_queries(
        self, *, roles: list[RoleFitRecommendation], location: str | None
    ) -> list[str]:
        suffix = f" {location}" if location else " Vietnam"
        queries: list[str] = []
        for role in roles[:3]:
            queries.append(f"{role.role} jobs{suffix}")
            if role.search_keywords:
                queries.append(" ".join(role.search_keywords[:3]) + f" jobs{suffix}")
        return queries[:6]

    def _preferred_location(self, *, preference: UserJobPreference | None) -> str | None:
        if preference and preference.locations:
            return preference.locations[0]
        return None

    def _preference_payload(self, preference: UserJobPreference | None) -> dict:
        if not preference:
            return {}
        return {
            "target_roles": preference.target_roles or [],
            "locations": preference.locations or [],
            "working_models": preference.working_models or [],
            "salary_expectation": preference.salary_expectation,
            "preferred_skills": preference.preferred_skills or [],
        }

    def _to_read(self, record: CandidateDiscoveryProfile) -> CandidateDiscoveryProfileRead:
        return CandidateDiscoveryProfileRead(
            profile_id=record.id,
            cv_id=record.cv_id,
            interview_id=record.interview_id,
            source=record.source,
            profile=CandidateDiscoveryProfileData.model_validate(record.profile_json),
            created_at=record.created_at,
            updated_at=record.updated_at,
        )
