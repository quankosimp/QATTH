from datetime import datetime

from pydantic import BaseModel, Field


class JobPreferencePayload(BaseModel):
    target_roles: list[str] = Field(default_factory=list)
    locations: list[str] = Field(default_factory=list)
    working_models: list[str] = Field(default_factory=list)
    salary_expectation: str | None = None
    preferred_skills: list[str] = Field(default_factory=list)


class JobPreferenceRead(JobPreferencePayload):
    updated_at: datetime | None = None


class JobInteractionPayload(BaseModel):
    action: str = Field(description="saved, applied, relevant, not_relevant, hidden")
    note: str | None = None


class JobInteractionRead(BaseModel):
    interaction_id: str
    job_id: str
    action: str
    note: str | None = None
    created_at: datetime | None = None


class ConsentPayload(BaseModel):
    consent_type: str = Field(description="cv_processing, interview_recording, job_matching")
    accepted: bool


class ConsentRead(BaseModel):
    consent_id: str
    consent_type: str
    accepted: bool
    created_at: datetime | None = None


class DeleteMyDataResult(BaseModel):
    user_id: str
    deleted_cvs: int
    deleted_interviews: int
    deleted_matches: int
    deleted_interactions: int
    user_deactivated: bool


class ExportMyDataResult(BaseModel):
    user_id: str
    cvs: list[dict] = Field(default_factory=list)
    interviews: list[dict] = Field(default_factory=list)
    matches: list[dict] = Field(default_factory=list)
    job_interactions: list[dict] = Field(default_factory=list)
    consents: list[dict] = Field(default_factory=list)
