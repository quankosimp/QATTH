from pydantic import BaseModel, Field


class EducationItem(BaseModel):
    school: str | None = None
    degree: str | None = None
    major: str | None = None
    start_year: int | None = None
    end_year: int | None = None
    gpa: str | None = None


class SkillItem(BaseModel):
    name: str
    category: str | None = Field(
        default=None,
        description="Example: programming_language, framework, database, cloud, tool, soft_skill.",
    )
    level: str | None = Field(default=None, description="beginner, intermediate, advanced, unknown.")
    evidence: str | None = None


class ProjectItem(BaseModel):
    name: str
    description: str | None = None
    role: str | None = None
    technologies: list[str] = Field(default_factory=list)
    outcomes: list[str] = Field(default_factory=list)
    url: str | None = None


class ExperienceItem(BaseModel):
    company: str | None = None
    title: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    description: str | None = None
    technologies: list[str] = Field(default_factory=list)


class CertificationItem(BaseModel):
    name: str
    issuer: str | None = None
    issued_at: str | None = None


class CVProfile(BaseModel):
    name: str | None = None
    email: str | None = None
    phone: str | None = None
    location: str | None = None
    summary: str | None = None
    education: list[EducationItem] = Field(default_factory=list)
    skills: list[SkillItem] = Field(default_factory=list)
    projects: list[ProjectItem] = Field(default_factory=list)
    experience: list[ExperienceItem] = Field(default_factory=list)
    certifications: list[CertificationItem] = Field(default_factory=list)
    languages: list[str] = Field(default_factory=list)
    target_roles: list[str] = Field(default_factory=list)
    seniority_estimate: str = Field(default="student")
    raw_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    warnings: list[str] = Field(default_factory=list)


class CVScanResult(BaseModel):
    cv_id: str
    status: str
    profile: CVProfile
    warnings: list[str] = Field(default_factory=list)


class CVReadResult(BaseModel):
    cv_id: str
    status: str
    original_file_name: str
    profile: CVProfile | None = None
    warnings: list[str] = Field(default_factory=list)
