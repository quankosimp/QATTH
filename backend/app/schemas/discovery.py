from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.matching import JobMatchItem


class RoleFitRecommendation(BaseModel):
    role: str
    score: float = Field(default=0.0, ge=0.0, le=1.0)
    reason: str
    evidence: list[str] = Field(default_factory=list)
    search_keywords: list[str] = Field(default_factory=list)


class CandidateDiscoveryProfileData(BaseModel):
    headline: str
    current_level: str = "student"
    strongest_signals: list[str] = Field(default_factory=list)
    preferred_roles: list[str] = Field(default_factory=list)
    recommended_roles: list[RoleFitRecommendation] = Field(default_factory=list)
    not_recommended_roles: list[RoleFitRecommendation] = Field(default_factory=list)
    skill_gaps: list[str] = Field(default_factory=list)
    search_queries: list[str] = Field(default_factory=list)
    practice_plan: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class DiscoveryProfileCreateRequest(BaseModel):
    cv_id: str
    interview_id: str | None = None
    language: str = Field(default="vi")


class CandidateDiscoveryProfileRead(BaseModel):
    profile_id: str
    cv_id: str
    interview_id: str | None = None
    source: str
    profile: CandidateDiscoveryProfileData
    created_at: datetime | None = None
    updated_at: datetime | None = None


class CandidateDiscoveryProfileList(BaseModel):
    items: list[CandidateDiscoveryProfileRead]
    total: int


class JobRecommendationRequest(BaseModel):
    discovery_profile_id: str
    limit: int = Field(default=10, ge=1, le=50)
    location: str | None = None
    working_model: str | None = None
    allow_stored_fallback: bool = True


class JobRecommendationResult(BaseModel):
    discovery_profile: CandidateDiscoveryProfileRead
    match_id: str
    items: list[JobMatchItem]
    external_search_used: bool
    fallback_used: bool
    search_queries: list[str] = Field(default_factory=list)
