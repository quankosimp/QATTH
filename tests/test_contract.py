from app.main import create_app


def test_openapi_includes_core_contract_paths():
    app = create_app()
    paths = app.openapi()["paths"]

    assert "/v1/files/upload-intents" in paths
    assert "/v1/cv-scans" in paths
    assert "/v1/cv-scans/{scan_id}/draft" in paths
    assert "/v1/cv-scans/{scan_id}/confirm" in paths
    assert "/v1/cvs/{cv_id}/versions" in paths
    assert "/v1/interviews" in paths
    assert "/v1/interviews/{interview_id}/end" in paths
    assert "/v1/job-search-runs" in paths
    assert "/v1/recommendation-runs" in paths
    assert "/v1/privacy/exports" in paths
    assert "/v1/admin/users/{user_id}/status" in paths
    assert "/health/ready" in paths
    assert "/health/live" in paths
    assert "/v1/cvs/scan" not in paths
