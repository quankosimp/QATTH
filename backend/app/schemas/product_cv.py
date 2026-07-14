from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class CvBasics(BaseModel):
    model_config = ConfigDict(extra="forbid")

    full_name: str | None = None
    email: str | None = None
    phone: str | None = None
    location: str | None = None
    summary: str | None = None
    links: list[str] = Field(default_factory=list, max_length=20)


class CvSkill(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    level: str | None = Field(default=None, max_length=80)
    evidence: list[str] = Field(default_factory=list, max_length=20)


class CvSectionEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, max_length=300)
    organization: str | None = Field(default=None, max_length=300)
    location: str | None = Field(default=None, max_length=200)
    start_date: str | None = Field(default=None, max_length=40)
    end_date: str | None = Field(default=None, max_length=40)
    description: str | None = Field(default=None, max_length=5000)
    highlights: list[str] = Field(default_factory=list, max_length=50)
    technologies: list[str] = Field(default_factory=list, max_length=100)
    url: str | None = Field(default=None, max_length=2000)


class CvLanguage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=100)
    proficiency: str | None = Field(default=None, max_length=100)


class CvContent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    basics: CvBasics = Field(default_factory=CvBasics)
    skills: list[CvSkill] = Field(default_factory=list, max_length=300)
    education: list[CvSectionEntry] = Field(default_factory=list, max_length=50)
    experience: list[CvSectionEntry] = Field(default_factory=list, max_length=100)
    projects: list[CvSectionEntry] = Field(default_factory=list, max_length=100)
    certifications: list[CvSectionEntry] = Field(default_factory=list, max_length=100)
    languages: list[CvLanguage] = Field(default_factory=list, max_length=30)


class CreateUploadIntentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    purpose: Literal["cv_source"]
    filename: str = Field(min_length=1, max_length=255)
    content_type: Literal["application/pdf"]
    size_bytes: int = Field(ge=1, le=20 * 1024 * 1024)
    sha256: str = Field(pattern=r"^[a-fA-F0-9]{64}$")

    @field_validator("filename")
    @classmethod
    def require_pdf_filename(cls, value: str) -> str:
        if not value.lower().endswith(".pdf"):
            raise ValueError("filename must end with .pdf")
        return value


class CompleteUploadRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sha256: str = Field(pattern=r"^[a-fA-F0-9]{64}$")
    provider_etag: str | None = Field(default=None, max_length=255)


class FileAssetView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    purpose: str
    content_type: str
    declared_size_bytes: int
    actual_size_bytes: int | None
    declared_sha256: str
    verified_sha256: str | None
    upload_status: str
    security_status: str
    rejection_reason: str | None
    created_at: datetime


class UploadIntentView(BaseModel):
    file: FileAssetView
    method: Literal["PUT"] = "PUT"
    upload_url: str
    required_headers: dict[str, str]
    expires_at: datetime


class SignedUrlView(BaseModel):
    url: str
    expires_at: datetime


class CreateCvScanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    file_id: str
    cv_id: str | None = None
    extraction_schema_version: Literal["cv-1"] = "cv-1"
    locale_hint: str | None = Field(default=None, max_length=16)


class CvScanView(BaseModel):
    id: str
    file_id: str
    cv_id: str | None
    parent_scan_id: str | None
    attempt_number: int
    status: str
    schema_version: str
    draft_id: str | None
    error: dict[str, Any] | None
    created_at: datetime
    completed_at: datetime | None


class CvDraftPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: dict[str, Any]


class CvDraftView(BaseModel):
    id: str
    scan_id: str
    revision: int
    schema_version: str
    content: CvContent
    field_confidence: dict[str, float]
    warnings: list[str]
    checksum: str
    updated_at: datetime


class ConfirmCvDraftRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    revision: int = Field(ge=1)
    checksum: str = Field(pattern=r"^[a-fA-F0-9]{64}$")
    title: str | None = Field(default=None, min_length=1, max_length=255)


class SetActiveVersionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version_id: str


class CvVersionView(BaseModel):
    id: str
    cv_id: str
    version: int
    schema_version: str
    content: CvContent
    checksum: str
    active: bool
    created_at: datetime


class CvView(BaseModel):
    id: str
    title: str
    status: str
    active_version: CvVersionView | None
    created_at: datetime
    updated_at: datetime


class CvPage(BaseModel):
    items: list[CvView]
    next_cursor: str | None


class CvAnalysisView(BaseModel):
    id: str
    cv_version_id: str
    parent_analysis_id: str | None
    attempt_number: int
    status: str
    scores: dict[str, float] | None
    findings: list[dict[str, Any]] | None
    provider: str | None
    model: str | None
    model_configuration_id: str | None
    prompt_version: str | None
    usage: dict[str, Any] | None
    disclaimer: str | None
    error: dict[str, Any] | None
    created_at: datetime
    completed_at: datetime | None
