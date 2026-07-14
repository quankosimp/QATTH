import base64

import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_production_config_fails_fast_for_required_security_dependencies() -> None:
    with pytest.raises(ValidationError) as raised:
        Settings(_env_file=None, app_env="production")
    message = str(raised.value)
    for required in (
        "PRIVACY_EXPORT_ENCRYPTION_KEY",
        "CLAMAV_HOST",
        "PAYMENT_PROVIDER",
        "PAYMENT_API_KEY",
        "PAYMENT_WEBHOOK_SECRET",
        "PAYMENT_PADDLE_PRICE_IDS",
        "PAYMENT_SUCCESS_URL_ALLOWLIST",
        "TRUSTED_PROXY_CIDRS",
    ):
        assert required in message


def test_complete_production_config_passes_startup_contract() -> None:
    settings = Settings(
        _env_file=None,
        app_env="production",
        public_api_origin="https://api.qatth.example",
        cors_origins=["https://app.qatth.example"],
        database_url="postgresql+psycopg://user:secret@db.example/qatth",
        redis_url="rediss://redis.example/0",
        celery_broker_url="rediss://redis.example/0",
        celery_result_backend="rediss://redis.example/1",
        trusted_proxy_cidrs=["10.0.0.0/8"],
        auto_create_tables=False,
        storage_backend="r2",
        r2_endpoint_url="https://account.r2.cloudflarestorage.com",
        r2_bucket="qatth-private",
        r2_access_key_id="r2-key",
        r2_secret_access_key="r2-secret",
        privacy_export_encryption_key=base64.urlsafe_b64encode(b"x" * 32).decode(),
        clamav_host="clamav.internal",
        oidc_issuer="https://identity.example",
        oidc_audience="qatth-api",
        openai_api_key="openai-secret",
        gemini_api_key="gemini-secret",
        payment_provider="paddle",
        payment_api_key="paddle-secret",
        payment_webhook_secret="paddle-webhook-secret",
        payment_success_url_allowlist=["https://app.qatth.example/billing"],
        payment_paddle_price_ids={"TOPUP_STARTER": "pri_01configured"},
        job_search_allowed_domains=["linkedin.com"],
    )
    assert settings.app_env == "production"
    assert settings.payment_provider == "paddle"


def test_production_rejects_sandbox_payment_and_insecure_redirects() -> None:
    with pytest.raises(ValidationError) as raised:
        Settings(
            _env_file=None,
            app_env="production",
            payment_provider="paddle",
            payment_paddle_api_base_url="https://sandbox-api.paddle.com",
            payment_success_url_allowlist=["http://app.qatth.example/billing"],
        )
    message = str(raised.value)
    assert "live Paddle API" in message
    assert "credential-free HTTPS" in message


def test_production_rejects_legacy_and_non_product_job_runtime() -> None:
    with pytest.raises(ValidationError) as raised:
        Settings(
            _env_file=None,
            app_env="production",
            legacy_api_enabled=True,
            job_search_provider="serpapi",
            job_search_live_external_access=False,
        )
    message = str(raised.value)
    assert "LEGACY_API_ENABLED must be false" in message
    assert "JOB_SEARCH_PROVIDER must be openai_web_search" in message
    assert "JOB_SEARCH_LIVE_EXTERNAL_ACCESS must be true" in message
