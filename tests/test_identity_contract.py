from backend.app.main import app


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
