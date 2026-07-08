from app.services.job_search import ExternalJobSearchService


def test_serpapi_jobs_payload_normalizes_to_job_posting_payload():
    service = ExternalJobSearchService(db=None)  # type: ignore[arg-type]
    payload = {
        "jobs_results": [
            {
                "job_id": "abc123",
                "title": "Junior Python Backend Developer",
                "company_name": "Demo Co",
                "location": "Ho Chi Minh City",
                "description": "Build APIs with Python, FastAPI, PostgreSQL and Docker. Hybrid role.",
                "apply_options": [{"title": "Apply", "link": "https://example.com/apply"}],
                "detected_extensions": {"posted_at": "2 days ago"},
            }
        ]
    }

    jobs = service._normalize_jobs(payload=payload, query="python backend jobs")

    assert jobs[0]["source"] == "serpapi_google_jobs"
    assert jobs[0]["external_id"] == "abc123"
    assert jobs[0]["source_url"] == "https://example.com/apply"
    assert jobs[0]["working_model"] == "hybrid"
    assert jobs[0]["level"] == "junior"
    assert {"python", "fastapi", "postgresql", "docker"}.issubset(set(jobs[0]["skills"]))
