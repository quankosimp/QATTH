from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint

from app.models.db import Base


def _uuid() -> str:
    return str(uuid4())


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class AuthIdentity(Base):
    __tablename__ = "auth_identities"
    __table_args__ = (
        UniqueConstraint("issuer", "subject", name="uq_auth_identity_issuer_subject"),
        Index("ix_auth_identities_user_id", "user_id"),
    )

    id = Column(String(36), primary_key=True, default=_uuid)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    issuer = Column(String(512), nullable=False)
    subject = Column(String(512), nullable=False)
    email = Column(String(320), nullable=True)
    email_verified = Column(Boolean, nullable=False, default=False)
    claims_snapshot = Column(JSON, nullable=False, default=dict)
    last_login_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow)


class UserSession(Base):
    __tablename__ = "user_sessions"
    __table_args__ = (
        UniqueConstraint("token_fingerprint", name="uq_user_sessions_token_fingerprint"),
        Index("ix_user_sessions_user_active", "user_id", "revoked_at", "expires_at"),
    )

    id = Column(String(36), primary_key=True, default=_uuid)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    identity_id = Column(String(36), ForeignKey("auth_identities.id", ondelete="CASCADE"), nullable=False)
    token_fingerprint = Column(String(64), nullable=False)
    provider_session_id = Column(String(512), nullable=True)
    device = Column(JSON, nullable=False, default=dict)
    scopes = Column(JSON, nullable=False, default=list)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    last_seen_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
    revoked_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)


class UserProductProfile(Base):
    __tablename__ = "user_product_profiles"

    id = Column(String(36), primary_key=True, default=_uuid)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True)
    account_status = Column(String(32), nullable=False, default="active", index=True)
    display_name = Column(String(200), nullable=True)
    locale = Column(String(16), nullable=False, default="vi-VN")
    timezone = Column(String(64), nullable=False, default="Asia/Ho_Chi_Minh")
    headline = Column(String(240), nullable=True)
    summary = Column(Text, nullable=True)
    location = Column(String(200), nullable=True)
    years_of_experience = Column(Integer, nullable=True)
    skills = Column(JSON, nullable=False, default=list)
    profile_links = Column(JSON, nullable=False, default=list)
    job_preferences = Column(JSON, nullable=False, default=dict)
    preference_version = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow)


class UserConsent(Base):
    __tablename__ = "user_consents"
    __table_args__ = (
        UniqueConstraint("user_id", "purpose", "policy_version", name="uq_user_consent_policy"),
        Index("ix_user_consents_user_purpose", "user_id", "purpose"),
    )

    id = Column(String(36), primary_key=True, default=_uuid)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    purpose = Column(String(80), nullable=False)
    policy_version = Column(String(32), nullable=False)
    status = Column(String(16), nullable=False)
    evidence = Column(JSON, nullable=False, default=dict)
    granted_at = Column(DateTime(timezone=True), nullable=True)
    withdrawn_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow)


class AccountStatusEvent(Base):
    __tablename__ = "account_status_events"
    __table_args__ = (Index("ix_account_status_events_user_created", "user_id", "created_at"),)

    id = Column(String(36), primary_key=True, default=_uuid)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    previous_status = Column(String(32), nullable=True)
    new_status = Column(String(32), nullable=False)
    reason = Column(Text, nullable=True)
    actor_id = Column(String(36), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
