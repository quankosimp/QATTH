from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "QATTH Career API"
    app_env: str = "local"
    api_v1_prefix: str = "/v1"

    database_url: str = "sqlite:///./data/qatth.db"
    auto_create_tables: bool = False
    redis_url: str = "redis://redis:6379/0"
    celery_broker_url: str = "redis://redis:6379/0"
    celery_result_backend: str = "redis://redis:6379/1"

    storage_backend: str = "local"
    minio_endpoint: str = "minio:9000"
    minio_access_key: str = "qatthminio"
    minio_secret_key: str = "qatthminiosecret"
    minio_bucket: str = "qatth-assets"
    minio_secure: bool = False
    rate_limit_enabled: bool = True
    rate_limit_requests_per_minute: int = 120
    otel_enabled: bool = False
    prometheus_enabled: bool = True

    gemini_api_key: str | None = None
    gemini_cv_model: str = "gemini-3.5-flash"
    gemini_evaluation_model: str = "gemini-3.5-flash"
    gemini_live_model: str = "gemini-live-2.5-flash-preview"

    job_search_provider: str = "serpapi_google_jobs"
    serpapi_api_key: str | None = None
    job_search_default_location: str = "Vietnam"

    upload_dir: Path = Path("data/uploads")
    generated_dir: Path = Path("data/generated")
    cors_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:3000", "http://localhost:8501"]
    )

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
