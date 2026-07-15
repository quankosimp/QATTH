from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import AppError
from app.core.idempotency import IdempotencyService
from app.core.identity_security import ProductCurrentUser
from app.models.db import User
from app.models.identity import UserConsent, UserProductProfile, UserSession
from app.schemas.identity import ConsentWrite, ProfilePatch


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class IdentityService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_user(self, current: ProductCurrentUser) -> tuple[User, UserProductProfile]:
        user = self.db.get(User, current.id)
        if user is None:
            raise AppError(404, "USER_NOT_FOUND", "User was not found")
        return user, self._profile(current.id)

    def update_profile(self, user_id: str, payload: ProfilePatch) -> UserProductProfile:
        profile = self._profile(user_id)
        values = payload.model_dump(exclude_unset=True)
        preferences = values.pop("job_preferences", None)
        for field, value in values.items():
            setattr(profile, field, value)
        if preferences is not None:
            profile.job_preferences = preferences
            profile.preference_version += 1
            from app.services.candidate_profiles import invalidate_candidate_profiles

            invalidate_candidate_profiles(self.db, user_id)
        profile.updated_at = _utcnow()
        self.db.commit()
        self.db.refresh(profile)
        return profile

    def list_consents(self, user_id: str) -> list[UserConsent]:
        return list(
            self.db.scalars(
                select(UserConsent)
                .where(UserConsent.user_id == user_id)
                .order_by(UserConsent.purpose, UserConsent.updated_at.desc())
            )
        )

    def require_consent(
        self,
        user_id: str,
        purpose: str = "product_processing",
        policy_version: str | None = None,
    ) -> UserConsent:
        version = policy_version or get_settings().product_processing_policy_version
        consent = self.db.scalar(
            select(UserConsent).where(
                UserConsent.user_id == user_id,
                UserConsent.purpose == purpose,
                UserConsent.policy_version == version,
                UserConsent.status == "granted",
            )
        )
        if consent is None:
            raise AppError(
                403,
                "CONSENT_REQUIRED",
                "Active consent is required before product data can be processed",
                details={"purpose": purpose, "policy_version": version},
            )
        return consent

    def write_consent(
        self,
        user_id: str,
        payload: ConsentWrite,
        evidence_context: dict[str, Any],
        idempotency_key: str,
    ) -> UserConsent:
        idempotency = IdempotencyService(self.db)
        result = idempotency.begin(
            scope="user:" + user_id,
            operation="identity.consent:" + payload.purpose + ":" + payload.policy_version,
            key=idempotency_key,
            request_hash=idempotency.request_hash(payload.model_dump(mode="json")),
        )
        if result.replayed:
            if result.record.status != "completed" or not result.record.resource_id:
                raise AppError(409, "IDEMPOTENCY_REQUEST_IN_PROGRESS", "The original consent request has not completed", retryable=True)
            consent = self.db.get(UserConsent, result.record.resource_id)
            if consent is None or consent.user_id != user_id:
                raise AppError(404, "CONSENT_NOT_FOUND", "Consent record was not found")
            return consent
        consent = self.db.scalar(
            select(UserConsent).where(
                UserConsent.user_id == user_id,
                UserConsent.purpose == payload.purpose,
                UserConsent.policy_version == payload.policy_version,
            )
        )
        now = _utcnow()
        evidence = {**payload.evidence, **evidence_context}
        if consent is None:
            consent = UserConsent(
                user_id=user_id,
                purpose=payload.purpose,
                policy_version=payload.policy_version,
                status=payload.status,
                evidence=evidence,
            )
            self.db.add(consent)
        else:
            consent.status = payload.status
            consent.evidence = evidence
        if payload.status == "granted":
            consent.granted_at = consent.granted_at or now
            consent.withdrawn_at = None
        else:
            consent.withdrawn_at = now
        consent.updated_at = now
        self.db.flush()
        idempotency.complete(result.record, resource_type="user_consent", resource_id=consent.id, response_status=200)
        self.db.commit()
        self.db.refresh(consent)
        return consent

    def list_sessions(self, user_id: str) -> list[UserSession]:
        return list(
            self.db.scalars(
                select(UserSession)
                .where(UserSession.user_id == user_id)
                .order_by(UserSession.last_seen_at.desc())
            )
        )

    def revoke_session(self, user_id: str, session_id: str) -> UserSession:
        session = self.db.scalar(
            select(UserSession).where(UserSession.id == session_id, UserSession.user_id == user_id)
        )
        if session is None:
            raise AppError(404, "SESSION_NOT_FOUND", "Session was not found")
        session.revoked_at = session.revoked_at or _utcnow()
        self.db.commit()
        self.db.refresh(session)
        return session

    def _profile(self, user_id: str) -> UserProductProfile:
        profile = self.db.scalar(select(UserProductProfile).where(UserProductProfile.user_id == user_id))
        if profile is None:
            profile = UserProductProfile(user_id=user_id)
            self.db.add(profile)
            self.db.commit()
            self.db.refresh(profile)
        return profile
