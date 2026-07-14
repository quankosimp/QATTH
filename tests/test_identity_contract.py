from app.main import app
from app.schemas.identity import ConsentWrite, ProfilePatch
from pydantic import ValidationError
import pytest


def test_identity_routes_are_exposed() -> None:
    schema = app.openapi()
    expected = {
        "/v1/me": {"get"},
        "/v1/me/profile": {"patch"},
        "/v1/me/consents": {"get", "put"},
        "/v1/me/sessions": {"get"},
        "/v1/me/sessions/{session_id}": {"delete"},
    }
    for path, methods in expected.items():
        assert path in schema["paths"]
        assert methods.issubset(schema["paths"][path])


def test_consent_write_accepts_idempotency_key() -> None:
    operation = app.openapi()["paths"]["/v1/me/consents"]["put"]
    headers = {item["name"] for item in operation["parameters"] if item["in"] == "header"}
    assert "Idempotency-Key" in headers


def test_consent_purposes_match_product_contract() -> None:
    assert ConsentWrite(purpose="product_processing", policy_version="v1", status="granted").purpose == "product_processing"
    with pytest.raises(ValidationError):
        ConsentWrite(purpose="cv_processing", policy_version="v1", status="granted")


def test_profile_links_reject_private_hosts() -> None:
    with pytest.raises(ValidationError):
        ProfilePatch(profile_links=["https://127.0.0.1/profile"])
