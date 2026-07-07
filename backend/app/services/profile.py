from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.core.security import CurrentUser
from app.models.db import (
    AuthToken,
    CVRecord,
    CVVersion,
    ConsentRecord,
    InterviewSession,
    InterviewTurn,
    JobInteraction,
    JobPosting,
    MatchRun,
    User,
    UserJobPreference,
)
from app.schemas.profile import (
    ConsentPayload,
    ConsentRead,
    DeleteMyDataResult,
    JobInteractionPayload,
    JobInteractionRead,
    JobPreferencePayload,
    JobPreferenceRead,
)


class ProfileService:
    def __init__(self, *, db: Session, current_user: CurrentUser) -> None:
        self.db = db
        self.current_user = current_user

    def get_preferences(self) -> JobPreferenceRead:
        preference = self._get_or_create_preferences()
        return self._preference_read(preference)

    def save_preferences(self, payload: JobPreferencePayload) -> JobPreferenceRead:
        preference = self._get_or_create_preferences()
        preference.target_roles = payload.target_roles
        preference.locations = payload.locations
        preference.working_models = payload.working_models
        preference.salary_expectation = payload.salary_expectation
        preference.preferred_skills = payload.preferred_skills
        preference.updated_at = datetime.now(UTC)
        self.db.commit()
        self.db.refresh(preference)
        return self._preference_read(preference)

    def record_job_interaction(
        self,
        *,
        job_id: str,
        payload: JobInteractionPayload,
    ) -> JobInteractionRead:
        if payload.action not in {"saved", "applied", "relevant", "not_relevant", "hidden"}:
            raise AppError(
                status_code=422,
                code="INVALID_JOB_INTERACTION",
                message="Unsupported job interaction action.",
            )

        job = self.db.get(JobPosting, job_id)
        if not job:
            raise AppError(status_code=404, code="JOB_NOT_FOUND", message="Job was not found.")

        interaction = JobInteraction(
            user_id=self.current_user.id,
            job_id=job_id,
            action=payload.action,
            note=payload.note,
        )
        self.db.add(interaction)
        self.db.commit()
        self.db.refresh(interaction)
        return self._interaction_read(interaction)

    def list_job_interactions(self) -> list[JobInteractionRead]:
        interactions = list(
            self.db.scalars(
                select(JobInteraction)
                .where(JobInteraction.user_id == self.current_user.id)
                .order_by(JobInteraction.created_at.desc())
            ).all()
        )
        return [self._interaction_read(interaction) for interaction in interactions]

    def record_consent(self, payload: ConsentPayload) -> ConsentRead:
        if payload.consent_type not in {"cv_processing", "interview_recording", "job_matching"}:
            raise AppError(
                status_code=422,
                code="INVALID_CONSENT_TYPE",
                message="Unsupported consent type.",
            )
        consent = ConsentRecord(
            user_id=self.current_user.id,
            consent_type=payload.consent_type,
            accepted=payload.accepted,
        )
        self.db.add(consent)
        self.db.commit()
        self.db.refresh(consent)
        return self._consent_read(consent)

    def list_consents(self) -> list[ConsentRead]:
        records = list(
            self.db.scalars(
                select(ConsentRecord)
                .where(ConsentRecord.user_id == self.current_user.id)
                .order_by(ConsentRecord.created_at.desc())
            ).all()
        )
        return [self._consent_read(record) for record in records]

    def delete_my_data(self) -> DeleteMyDataResult:
        user_id = self.current_user.id
        cv_ids = list(self.db.scalars(select(CVRecord.id).where(CVRecord.user_id == user_id)).all())
        interview_ids = list(
            self.db.scalars(select(InterviewSession.id).where(InterviewSession.user_id == user_id)).all()
        )

        deleted_matches = self._delete_count(delete(MatchRun).where(MatchRun.user_id == user_id))
        deleted_interactions = self._delete_count(
            delete(JobInteraction).where(JobInteraction.user_id == user_id)
        )
        self._delete_count(delete(ConsentRecord).where(ConsentRecord.user_id == user_id))
        self._delete_count(delete(UserJobPreference).where(UserJobPreference.user_id == user_id))

        if interview_ids:
            self._delete_count(delete(InterviewTurn).where(InterviewTurn.interview_id.in_(interview_ids)))
        deleted_interviews = self._delete_count(
            delete(InterviewSession).where(InterviewSession.user_id == user_id)
        )

        if cv_ids:
            self._delete_count(delete(CVVersion).where(CVVersion.cv_id.in_(cv_ids)))
        deleted_cvs = self._delete_count(delete(CVRecord).where(CVRecord.user_id == user_id))

        self._delete_count(delete(AuthToken).where(AuthToken.user_id == user_id))
        user = self.db.get(User, user_id)
        if user:
            user.is_active = False
            user.email = f"deleted-{user.id}@deleted.local"
            user.full_name = None
        self.db.commit()

        return DeleteMyDataResult(
            user_id=user_id,
            deleted_cvs=deleted_cvs,
            deleted_interviews=deleted_interviews,
            deleted_matches=deleted_matches,
            deleted_interactions=deleted_interactions,
            user_deactivated=True,
        )

    def _get_or_create_preferences(self) -> UserJobPreference:
        preference = self.db.scalar(
            select(UserJobPreference).where(UserJobPreference.user_id == self.current_user.id)
        )
        if preference:
            return preference
        preference = UserJobPreference(user_id=self.current_user.id)
        self.db.add(preference)
        self.db.commit()
        self.db.refresh(preference)
        return preference

    def _preference_read(self, preference: UserJobPreference) -> JobPreferenceRead:
        return JobPreferenceRead(
            target_roles=preference.target_roles or [],
            locations=preference.locations or [],
            working_models=preference.working_models or [],
            salary_expectation=preference.salary_expectation,
            preferred_skills=preference.preferred_skills or [],
            updated_at=preference.updated_at,
        )

    def _interaction_read(self, interaction: JobInteraction) -> JobInteractionRead:
        return JobInteractionRead(
            interaction_id=interaction.id,
            job_id=interaction.job_id,
            action=interaction.action,
            note=interaction.note,
            created_at=interaction.created_at,
        )

    def _consent_read(self, record: ConsentRecord) -> ConsentRead:
        return ConsentRead(
            consent_id=record.id,
            consent_type=record.consent_type,
            accepted=record.accepted,
            created_at=record.created_at,
        )

    def _delete_count(self, statement) -> int:
        result = self.db.execute(statement)
        return result.rowcount or 0
