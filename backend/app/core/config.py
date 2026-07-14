import base64
import binascii
from functools import lru_cache
from ipaddress import ip_network
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

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
    clamav_host: str | None = None
    clamav_port: int = 3310
    clamav_timeout_seconds: float = 10.0

    rate_limit_enabled: bool = True
    rate_limit_requests_per_minute: int = 120
    rate_limit_ai_requests_per_minute: int = 30
    trusted_proxy_cidrs: list[str] = Field(default_factory=list)
    idempotency_ttl_seconds: int = 86_400
    product_processing_policy_version: str = "2026-07-14"

    oidc_issuer: str | None = None
    oidc_audience: str | None = None
    oidc_jwks_url: str | None = None
    oidc_required_claims: list[str] = Field(default_factory=lambda: ["sub"])

    openai_api_key: str | None = None
    openai_project_id: str | None = None
    openai_cv_model: str = "gpt-5.6"
    openai_evaluation_model: str = "gpt-5.6"
    openai_embedding_model: str = "text-embedding-3-large"
    openai_search_model: str = "gpt-5.6"
    openai_timeout_seconds: int = 60
    openai_daily_budget_minor: int = 500_000
    openai_monthly_budget_minor: int = 10_000_000
    provider_retry_attempts: int = 3
    provider_retry_base_delay_seconds: float = 0.25
    provider_retry_max_delay_seconds: float = 4.0
    provider_circuit_failure_threshold: int = 5
    provider_circuit_open_seconds: int = 30
    provider_bulkhead_limit: int = 20
    provider_bulkhead_lease_seconds: int = 180

    gemini_api_key: str | None = None
    gemini_cv_model: str = "gemini-3.5-flash"
    gemini_evaluation_model: str = "gemini-3.5-flash"
    gemini_live_model: str = "gemini-3.1-flash-live-preview"
    gemini_live_session_limit: int = 20
    gemini_live_setup_timeout_seconds: int = 15
    gemini_live_idle_timeout_seconds: int = 60
    gemini_live_reconnect_window_seconds: int = 300
    gemini_live_lease_seconds: int = 90
    gemini_live_audio_chunk_max_bytes: int = 65_536

    payment_provider: str | None = None
    payment_api_key: str | None = None
    payment_webhook_secret: str | None = None
    payment_success_url_allowlist: list[str] = Field(default_factory=list)
    payment_paddle_api_base_url: str = "https://api.paddle.com"
    payment_paddle_price_ids: dict[str, str] = Field(default_factory=dict)
    payment_webhook_tolerance_seconds: int = 5
    payment_http_timeout_seconds: float = 10.0
    credit_adjustment_dual_control_enabled: bool = True
    credit_adjustment_dual_control_threshold: int = 500

    job_search_provider: str = "openai_web_search"
    serpapi_api_key: str | None = None
    job_search_default_location: str = "Vietnam"
    job_search_country_code: str = "VN"
    job_search_allowed_domains: list[str] = Field(default_factory=list)
    job_search_blocked_domains: list[str] = Field(default_factory=list)
    job_search_live_external_access: bool = True

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
        if self.rate_limit_requests_per_minute < 1 or self.rate_limit_ai_requests_per_minute < 1:
            raise ValueError("Rate limits must be positive.")
        try:
            for cidr in self.trusted_proxy_cidrs:
                ip_network(cidr, strict=False)
        except ValueError as exc:
            raise ValueError("TRUSTED_PROXY_CIDRS must contain valid IPv4/IPv6 networks.") from exc
        if self.signed_url_ttl_seconds < 30:
            raise ValueError("SIGNED_URL_TTL_SECONDS must be at least 30 seconds.")
        if not 1 <= self.clamav_port <= 65_535 or self.clamav_timeout_seconds <= 0:
            raise ValueError("ClamAV port and timeout must be positive and valid.")
        if self.legacy_api_prefix == self.api_v1_prefix:
            raise ValueError("LEGACY_API_PREFIX must not overlap API_V1_PREFIX.")
        if not self.product_processing_policy_version.strip():
            raise ValueError("PRODUCT_PROCESSING_POLICY_VERSION must not be empty.")
        if self.credit_adjustment_dual_control_threshold < 1:
            raise ValueError("CREDIT_ADJUSTMENT_DUAL_CONTROL_THRESHOLD must be positive.")
        if self.provider_retry_attempts < 1:
            raise ValueError("PROVIDER_RETRY_ATTEMPTS must be positive.")
        if self.provider_circuit_failure_threshold < 1 or self.provider_bulkhead_limit < 1:
            raise ValueError("Provider circuit and bulkhead limits must be positive.")
        if self.gemini_live_session_limit < 1:
            raise ValueError("GEMINI_LIVE_SESSION_LIMIT must be positive.")
        if not 5 <= self.gemini_live_setup_timeout_seconds <= 60:
            raise ValueError("GEMINI_LIVE_SETUP_TIMEOUT_SECONDS must be between 5 and 60.")
        if not 15 <= self.gemini_live_idle_timeout_seconds <= 300:
            raise ValueError("GEMINI_LIVE_IDLE_TIMEOUT_SECONDS must be between 15 and 300.")
        if not 30 <= self.gemini_live_reconnect_window_seconds <= 7200:
            raise ValueError("GEMINI_LIVE_RECONNECT_WINDOW_SECONDS must be between 30 and 7200.")
        if self.gemini_live_lease_seconds < 30:
            raise ValueError("GEMINI_LIVE_LEASE_SECONDS must be at least 30.")
        if not 3200 <= self.gemini_live_audio_chunk_max_bytes <= 65_536:
            raise ValueError("GEMINI_LIVE_AUDIO_CHUNK_MAX_BYTES must be between 3200 and 65536.")
        if self.openai_daily_budget_minor < 1 or self.openai_monthly_budget_minor < 1:
            raise ValueError("OpenAI provider budgets must be positive.")
        if not 1 <= self.payment_webhook_tolerance_seconds <= 300:
            raise ValueError("PAYMENT_WEBHOOK_TOLERANCE_SECONDS must be between 1 and 300.")
        if self.payment_http_timeout_seconds <= 0:
            raise ValueError("PAYMENT_HTTP_TIMEOUT_SECONDS must be positive.")
        if len(self.job_search_country_code) != 2 or not self.job_search_country_code.isalpha():
            raise ValueError("JOB_SEARCH_COUNTRY_CODE must be an ISO 3166-1 alpha-2 code.")
        allowed = {item.casefold() for item in self.job_search_allowed_domains}
        blocked = {item.casefold() for item in self.job_search_blocked_domains}
        if len(allowed) > 100 or len(blocked) > 100:
            raise ValueError("Job search domain lists may contain at most 100 entries.")
        if allowed & blocked:
            raise ValueError("A job search domain cannot be both allowed and blocked.")
        for domain in allowed | blocked:
            if not domain or "://" in domain or "/" in domain or ":" in domain:
                raise ValueError("Job search domains must be hostnames without scheme, path, or port.")

        if self.app_env != "production":
            return self

        errors: list[str] = []
        if not self.database_url.startswith(("postgresql://", "postgresql+psycopg://")):
            errors.append("DATABASE_URL must use PostgreSQL in production")
        if self.auto_create_tables:
            errors.append("AUTO_CREATE_TABLES must be false in production")
        if not self.rate_limit_enabled:
            errors.append("RATE_LIMIT_ENABLED must be true in production")
        if not self.redis_url.startswith("rediss://"):
            errors.append("REDIS_URL must use TLS (rediss://) in production")
        if not self.celery_broker_url.startswith("rediss://") or not self.celery_result_backend.startswith("rediss://"):
            errors.append("Celery Redis URLs must use TLS (rediss://) in production")
        if not self.trusted_proxy_cidrs:
            errors.append("TRUSTED_PROXY_CIDRS is required in production")
        if self.storage_backend != "r2":
            errors.append("STORAGE_BACKEND must be r2 in production")
        for name, value in (
            ("R2_ENDPOINT_URL", self.r2_endpoint_url),
            ("R2_BUCKET", self.r2_bucket),
            ("R2_ACCESS_KEY_ID", self.r2_access_key_id),
            ("R2_SECRET_ACCESS_KEY", self.r2_secret_access_key),
            ("PRIVACY_EXPORT_ENCRYPTION_KEY", self.privacy_export_encryption_key),
            ("CLAMAV_HOST", self.clamav_host),
            ("OIDC_ISSUER", self.oidc_issuer),
            ("OIDC_AUDIENCE", self.oidc_audience),
            ("OPENAI_API_KEY", self.openai_api_key),
            ("GEMINI_API_KEY", self.gemini_api_key),
        ):
            if not value:
                errors.append(f"{name} is required in production")
        if self.privacy_export_encryption_key:
            try:
                padding = "=" * (-len(self.privacy_export_encryption_key) % 4)
                decoded_key = base64.urlsafe_b64decode(self.privacy_export_encryption_key + padding)
                if len(decoded_key) != 32:
                    errors.append("PRIVACY_EXPORT_ENCRYPTION_KEY must encode exactly 32 bytes")
            except (ValueError, binascii.Error):
                errors.append("PRIVACY_EXPORT_ENCRYPTION_KEY must be URL-safe base64")
        if self.payment_provider != "paddle":
            errors.append("PAYMENT_PROVIDER must be paddle in production")
        for name, value in (
            ("PAYMENT_API_KEY", self.payment_api_key),
            ("PAYMENT_WEBHOOK_SECRET", self.payment_webhook_secret),
        ):
            if not value:
                errors.append(f"{name} is required in production")
        if self.payment_paddle_api_base_url != "https://api.paddle.com":
            errors.append("PAYMENT_PADDLE_API_BASE_URL must use the live Paddle API in production")
        if not self.payment_paddle_price_ids:
            errors.append("PAYMENT_PADDLE_PRICE_IDS is required in production")
        elif any(not code.strip() or not price_id.startswith("pri_") for code, price_id in self.payment_paddle_price_ids.items()):
            errors.append("PAYMENT_PADDLE_PRICE_IDS must map non-empty offer codes to Paddle pri_ IDs")
        if not self.payment_success_url_allowlist:
            errors.append("PAYMENT_SUCCESS_URL_ALLOWLIST is required in production")
        for redirect_url in self.payment_success_url_allowlist:
            parsed = urlsplit(redirect_url)
            if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
                errors.append("PAYMENT_SUCCESS_URL_ALLOWLIST entries must be credential-free HTTPS URLs")
                break
        for name, value in (
            ("PUBLIC_API_ORIGIN", self.public_api_origin),
            ("OIDC_ISSUER", self.oidc_issuer or ""),
            ("R2_ENDPOINT_URL", self.r2_endpoint_url or ""),
        ):
            if urlsplit(value).scheme != "https":
                errors.append(f"{name} must use HTTPS in production")
        if "*" in self.cors_origins:
            errors.append("Wildcard CORS is not allowed in production")
        if any(urlsplit(origin).scheme != "https" for origin in self.cors_origins):
            errors.append("CORS_ORIGINS must contain only HTTPS origins in production")
        if self.job_search_provider == "openai_web_search" and not self.job_search_allowed_domains:
            errors.append("JOB_SEARCH_ALLOWED_DOMAINS is required for OpenAI web search in production")
        if errors:
            raise ValueError("; ".join(errors))
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
