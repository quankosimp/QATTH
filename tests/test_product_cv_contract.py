from app.main import app


def test_product_file_and_cv_routes_are_exposed() -> None:
    paths = app.openapi()["paths"]
    expected = {
        "/v1/files/upload-intents": {"post"},
        "/v1/files/{file_id}/complete": {"post"},
        "/v1/files/{file_id}/download-url": {"post"},
        "/v1/cv-scans": {"post"},
        "/v1/cv-scans/{scan_id}": {"get"},
        "/v1/cv-scans/{scan_id}/retry": {"post"},
        "/v1/cv-scans/{scan_id}/draft": {"get", "patch"},
        "/v1/cv-scans/{scan_id}/confirm": {"post"},
        "/v1/cvs": {"get"},
        "/v1/cvs/{cv_id}/versions": {"get"},
        "/v1/cvs/{cv_id}/active-version": {"put"},
        "/v1/cvs/{cv_id}/archive": {"post"},
        "/v1/cv-versions/{version_id}/analyses": {"post"},
        "/v1/cv-analyses/{analysis_id}": {"get"},
        "/v1/cv-analyses/{analysis_id}/retry": {"post"},
    }
    for path, methods in expected.items():
        assert path in paths
        assert methods.issubset(paths[path])


def test_draft_patch_requires_if_match() -> None:
    operation = app.openapi()["paths"]["/v1/cv-scans/{scan_id}/draft"]["patch"]
    header = next(item for item in operation["parameters"] if item["name"] == "If-Match")
    assert header["required"] is True


def test_cv_mutations_require_idempotency_key() -> None:
    schema = app.openapi()
    operations = [
        ("/v1/files/upload-intents", "post"),
        ("/v1/cv-scans", "post"),
        ("/v1/cv-scans/{scan_id}/confirm", "post"),
        ("/v1/cv-versions/{version_id}/analyses", "post"),
    ]
    for path, method in operations:
        header = next(item for item in schema["paths"][path][method]["parameters"] if item["name"] == "Idempotency-Key")
        assert header["required"] is True
