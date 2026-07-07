from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "QATTH Career API"
    app_env: str = "local"
    api_v1_prefix: str = "/v1"

    database_url: str = "sqlite:///./data/qatth.db"

    gemini_api_key: str | None = None
    gemini_cv_model: str = "gemini-3.5-flash"
    gemini_evaluation_model: str = "gemini-3.5-flash"
    gemini_live_model: str = "gemini-live-2.5-flash-preview"

    upload_dir: Path = Path("data/uploads")
    generated_dir: Path = Path("data/generated")
    cors_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:3000", "http://localhost:8501"]
    )

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
