from backend.app.main import app


def test_product_job_search_contract_is_exposed() -> None:
    paths = app.openapi()["paths"]
    expected = {
        "/v1/jobs": {"get"},
        "/v1/jobs/{job_id}": {"get"},
        "/v1/job-search-runs": {"post"},
        "/v1/job-search-runs/{run_id}": {"get"},
        "/v1/job-search-runs/{run_id}/events": {"get"},
        "/v1/job-search-runs/{run_id}/results": {"get"},
    }
    for path, methods in expected.items():
        assert path in paths
        assert methods.issubset(paths[path])


def test_job_search_modes_and_limits_match_contract() -> None:
    schema = app.openapi()["components"]["schemas"]["CreateJobSearchRequest"]
    assert set(schema["properties"]["mode"]["enum"]) == {"indexed", "live", "hybrid"}
    assert schema["properties"]["maximum_results"]["maximum"] == 100


def test_job_search_accepts_idempotency_key_and_sse_replay_header() -> None:
    paths = app.openapi()["paths"]
    create_headers = {
        item["name"]
        for item in paths["/v1/job-search-runs"]["post"]["parameters"]
        if item["in"] == "header"
    }
    event_headers = {
        item["name"]
        for item in paths["/v1/job-search-runs/{run_id}/events"]["get"]["parameters"]
        if item["in"] == "header"
    }
    assert "Idempotency-Key" in create_headers
    assert "Last-Event-ID" in event_headers
