from __future__ import annotations

import ipaddress
from datetime import datetime
from typing import Any, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator


class JobPreferences(BaseModel):
    roles: list[str] = Field(default_factory=list, max_length=30)
    preferred_skills: list[str] = Field(default_factory=list, max_length=100)
    seniority: Literal["intern", "entry", "junior", "mid", "senior"] | None = None
    locations: list[str] = Field(default_factory=list, max_length=30)
    employment_types: list[str] = Field(default_factory=list, max_length=10)
    remote_modes: list[str] = Field(default_factory=list, max_length=10)
    minimum_salary: int | None = Field(default=None, ge=0)
    salary_currency: str | None = Field(default=None, min_length=3, max_length=3)
    willing_to_relocate: bool = False


class ProfilePatch(BaseModel):
    display_name: str | None = Field(default=None, max_length=200)
    locale: str | None = Field(default=None, max_length=16)
    timezone: str | None = Field(default=None, max_length=64)
    headline: str | None = Field(default=None, max_length=240)
    summary: str | None = Field(default=None, max_length=5000)
    location: str | None = Field(default=None, max_length=200)
    years_of_experience: int | None = Field(default=None, ge=0, le=80)
    skills: list[str] | None = Field(default=None, max_length=200)
    profile_links: list[str] | None = Field(default=None, max_length=20)
    job_preferences: JobPreferences | None = None

    @field_validator("profile_links")
    @classmethod
    def validate_profile_links(cls, values: list[str] | None) -> list[str] | None:
        for value in values or []:
            parsed = urlsplit(value)
            hostname = (parsed.hostname or "").lower().rstrip(".")
            if parsed.scheme != "https" or not hostname or parsed.username or parsed.password:
                raise ValueError("profile links must be public HTTPS URLs without credentials")
            if hostname in {"localhost", "localhost.localdomain"} or hostname.endswith((".local", ".internal")):
                raise ValueError("profile links must not target local hosts")
            try:
                address = ipaddress.ip_address(hostname)
            except ValueError:
                continue
            if not address.is_global:
                raise ValueError("profile links must not target private or reserved addresses")
        return values


class ProductProfile(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    account_status: str
    display_name: str | None
    locale: str
    timezone: str
    headline: str | None
    summary: str | None
    location: str | None
    years_of_experience: int | None
    skills: list[str]
    profile_links: list[str]
    job_preferences: dict[str, Any]
    preference_version: int
    updated_at: datetime


class UserMe(BaseModel):
    id: str
    email: str
    role: str
    email_verified: bool
    profile: ProductProfile


class ConsentWrite(BaseModel):
    purpose: Literal["product_processing", "marketing", "model_training"]
    policy_version: str = Field(min_length=1, max_length=32)
    status: Literal["granted", "withdrawn"]
    evidence: dict[str, Any] = Field(default_factory=dict)


class ConsentView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    purpose: str
    policy_version: str
    status: str
    evidence: dict[str, Any]
    granted_at: datetime | None
    withdrawn_at: datetime | None
    updated_at: datetime


class SessionView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    provider_session_id: str | None
    device: dict[str, Any]
    scopes: list[str]
    expires_at: datetime
    last_seen_at: datetime
    revoked_at: datetime | None
    created_at: datetime
    current: bool = False


class SessionRevoked(BaseModel):
    id: str
    revoked: bool
