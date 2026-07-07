from app.main import create_app


def test_openapi_includes_core_contract_paths():
    app = create_app()
    paths = app.openapi()["paths"]

    assert "/v1/cvs/scan" in paths
    assert "/v1/cvs/{cv_id}/profile" in paths
    assert "/v1/cvs/{cv_id}/versions" in paths
    assert "/v1/interviews" in paths
    assert "/v1/interviews/{interview_id}/end" in paths
    assert "/v1/jobs/crawl-runs" in paths
    assert "/v1/matches" in paths
    assert "/v1/admin/overview" in paths
    assert "/v1/preferences/jobs" in paths
    assert "/v1/privacy/me/data" in paths
    assert "/v1/privacy/me/export" in paths
    assert "/v1/auth/logout" in paths
    assert "/v1/auth/password-reset/request" in paths
    assert "/v1/ops/readiness" in paths
