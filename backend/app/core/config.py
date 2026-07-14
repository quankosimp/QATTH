from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "QATTH Career API"
    app_env: Literal["local", "test", "staging", "production"] = "local"
    app_version: str = "1.0.0-draft"
    log_level: str = "INFO"
    api_v1_prefix: str = "/v1"
    legacy_api_enabled: bool = False
    legacy_api_prefix: str = "/legacy/v1"
    public_api_origin: str = "http://localhost:8000"
    request_timeout_seconds: int = 30

    database_url: str = "postgresql+psycopg://qatth:qatth@localhost:5432/qatth"
    database_pool_size: int = 10
    database_pool_overflow: int = 10
    auto_create_tables: bool = False

    redis_url: str = "redis://localhost:6379/0"
    redis_key_prefix: str = "qatth:local"
    celery_broker_url: str = "redis://localhost:6379/0"
    celery_result_backend: str = "redis://localhost:6379/1"

    storage_backend: Literal["local", "minio", "r2"] = "local"
    minio_endpoint: str = "localhost:9000"
    minio_access_key: str = "qatthminio"
    minio_secret_key: str = "qatthminiosecret"
    minio_bucket: str = "qatth-assets"
    minio_secure: bool = False
    r2_endpoint_url: str | None = None
    r2_bucket: str | None = None
    r2_access_key_id: str | None = None
    r2_secret_access_key: str | None = None
    signed_url_ttl_seconds: int = 300
    privacy_export_ttl_hours: int = 24
    privacy_export_max_bytes: int = 200_000_000
    privacy_export_encryption_key: str | None = None

    rate_limit_enabled: bool = True
    rate_limit_requests_per_minute: int = 120
    idempotency_ttl_seconds: int = 86_400
    product_processing_policy_version: str = "2026-07-14"

    oidc_issuer: str | None = None
    oidc_audience: str | None = None
    oidc_jwks_url: str | None = None
    oidc_required_claims: list[str] = Field(default_factory=lambda: ["sub"])

    openai_api_key: str | None = None
    openai_project_id: str | None = None
    openai_cv_model: str = "gpt-5.6-luna"
    openai_evaluation_model: str = "gpt-5.6-luna"
    openai_embedding_model: str = "text-embedding-3-large"
    openai_search_model: str = "gpt-5.6-luna"
    openai_timeout_seconds: int = 60
    openai_daily_budget_minor: int = 500_000

    gemini_api_key: str | None = None
    gemini_cv_model: str = "gemini-3.5-flash"
    gemini_evaluation_model: str = "gemini-3.5-flash"
    gemini_live_model: str = "gemini-3.1-flash-live-preview"
    gemini_live_session_limit: int = 20

    payment_provider: str | None = None
    payment_api_key: str | None = None
    payment_webhook_secret: str | None = None
    payment_success_url_allowlist: list[str] = Field(default_factory=list)
    credit_adjustment_dual_control_enabled: bool = True
    credit_adjustment_dual_control_threshold: int = 500

    job_search_provider: str = "openai_web_search"
    serpapi_api_key: str | None = None
    job_search_default_location: str = "Vietnam"

    otel_enabled: bool = False
    otel_service_name: str = "qatth-api"
    otel_exporter_otlp_endpoint: str | None = None
    prometheus_enabled: bool = True

    upload_dir: Path = Path("data/uploads")
    generated_dir: Path = Path("data/generated")
    cors_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:3000", "http://localhost:8501"]
    )

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @model_validator(mode="after")
    def validate_environment_contract(self) -> "Settings":
        if self.database_pool_size < 1 or self.database_pool_overflow < 0:
            raise ValueError("Database pool limits must be non-negative.")
        if self.rate_limit_requests_per_minute < 1:
            raise ValueError("RATE_LIMIT_REQUESTS_PER_MINUTE must be positive.")
        if self.signed_url_ttl_seconds < 30:
            raise ValueError("SIGNED_URL_TTL_SECONDS must be at least 30 seconds.")
        if self.legacy_api_prefix == self.api_v1_prefix:
            raise ValueError("LEGACY_API_PREFIX must not overlap API_V1_PREFIX.")
        if not self.product_processing_policy_version.strip():
            raise ValueError("PRODUCT_PROCESSING_POLICY_VERSION must not be empty.")
        if self.credit_adjustment_dual_control_threshold < 1:
            raise ValueError("CREDIT_ADJUSTMENT_DUAL_CONTROL_THRESHOLD must be positive.")

        if self.app_env != "production":
            return self

        errors: list[str] = []
        if not self.database_url.startswith(("postgresql://", "postgresql+psycopg://")):
            errors.append("DATABASE_URL must use PostgreSQL in production")
        if self.auto_create_tables:
            errors.append("AUTO_CREATE_TABLES must be false in production")
        if self.storage_backend != "r2":
            errors.append("STORAGE_BACKEND must be r2 in production")
        for name, value in (
            ("R2_ENDPOINT_URL", self.r2_endpoint_url),
            ("R2_BUCKET", self.r2_bucket),
            ("R2_ACCESS_KEY_ID", self.r2_access_key_id),
            ("R2_SECRET_ACCESS_KEY", self.r2_secret_access_key),
            ("OIDC_ISSUER", self.oidc_issuer),
            ("OIDC_AUDIENCE", self.oidc_audience),
            ("OPENAI_API_KEY", self.openai_api_key),
            ("GEMINI_API_KEY", self.gemini_api_key),
        ):
            if not value:
                errors.append(f"{name} is required in production")
        if "*" in self.cors_origins:
            errors.append("Wildcard CORS is not allowed in production")
        if errors:
            raise ValueError("; ".join(errors))
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
