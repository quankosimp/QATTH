import json

import pytest

from app.core.config import Settings
from app.core.errors import AppError
from app.services.openai_jobs import OpenAIJobsAdapter
from app.services.safe_job_fetch import SafeJobFetcher


def _adapter(monkeypatch, response):
    adapter = OpenAIJobsAdapter.__new__(OpenAIJobsAdapter)
    adapter.settings = Settings(app_env="test", openai_api_key="test-key")
    adapter.search_model = "gpt-5.6"
    adapter.search_configuration = {}
    adapter.search_runtime = {"id": None, "version": "test"}
    captured = {}

    def respond(body):
        captured.update(body)
        return response

    monkeypatch.setattr(adapter, "_responses", respond)
    return adapter, captured


def _response(job, citation_url="https://jobs.example.com/role?utm_source=openai"):
    return {
        "id": "resp-1",
        "status": "completed",
        "usage": {"input_tokens": 10, "output_tokens": 5},
        "output": [
            {
                "type": "web_search_call",
                "id": "ws-1",
                "status": "completed",
                "action": {
                    "type": "search",
                    "queries": ["backend intern vietnam"],
                    "sources": [{"url": citation_url, "title": "Backend Intern"}],
                },
            },
            {
                "type": "message",
                "content": [
                    {
                        "type": "output_text",
                        "text": json.dumps({"jobs": [job]}),
                        "annotations": [
                            {"type": "url_citation", "url": citation_url, "title": "Backend Intern"}
                        ],
                    }
                ],
            },
        ],
    }


def _job(**overrides):
    value = {
        "title": "Backend Intern",
        "company_name": "Example Co",
        "location": "Ho Chi Minh City",
        "remote_mode": "hybrid",
        "employment_type": "internship",
        "seniority": "intern",
        "salary_min_minor": None,
        "salary_max_minor": None,
        "salary_currency": None,
        "salary_period": None,
        "description": "Build APIs",
        "skills": ["Python"],
        "source_url": "https://jobs.example.com/role",
        "source_job_id": "job-1",
        "posted_at": "2026-07-15",
    }
    value.update(overrides)
    return value


def test_live_search_requires_live_tool_and_preserves_complete_sources(monkeypatch) -> None:
    adapter, request = _adapter(monkeypatch, _response(_job()))

    jobs, metadata = adapter.live_search("backend intern", {}, 20)

    assert jobs[0]["source_url"].startswith("https://jobs.example.com/role")
    assert request["tools"][0]["type"] == "web_search"
    assert request["tools"][0]["external_web_access"] is True
    assert request["include"] == ["web_search_call.action.sources"]
    assert metadata["search_calls"][0]["id"] == "ws-1"
    assert metadata["sources"][0]["title"] == "Backend Intern"


def test_live_search_rejects_unvalidated_provider_payload(monkeypatch) -> None:
    adapter, _ = _adapter(
        monkeypatch,
        _response(_job(salary_min_minor=1_000_000, salary_currency=None)),
    )

    with pytest.raises(AppError) as raised:
        adapter.live_search("backend intern", {}, 20)

    assert raised.value.code == "WEB_SEARCH_RESPONSE_INVALID"


def test_live_search_rejects_output_without_search_call(monkeypatch) -> None:
    response = _response(_job())
    response["output"] = [item for item in response["output"] if item["type"] != "web_search_call"]
    adapter, _ = _adapter(monkeypatch, response)

    with pytest.raises(AppError) as raised:
        adapter.live_search("backend intern", {}, 20)

    assert raised.value.code == "WEB_SEARCH_NOT_EXECUTED"


def test_provider_evidence_drops_credentialed_or_malformed_urls() -> None:
    assert OpenAIJobsAdapter._sanitize_links(
        [
            {"url": "https://user:secret@jobs.example.com/role"},
            {"url": "https://jobs.example.com:invalid/role"},
            {"url": "https://jobs.example.com/valid", "title": "Valid"},
        ]
    ) == [
        {
            "url": "https://jobs.example.com/valid",
            "title": "Valid",
            "type": "web_source",
        }
    ]


def test_job_page_verification_requires_active_matching_html() -> None:
    assert SafeJobFetcher._classify(
        200,
        "text/html; charset=utf-8",
        "Backend Intern at Example Co",
        "Apply for Backend Intern with Example Co",
        "Backend Intern",
        "Example Co",
    ) == "verified"
    assert SafeJobFetcher._classify(
        200,
        "text/html",
        "Backend Intern at Example Co",
        "This job is no longer available",
        "Backend Intern",
        "Example Co",
    ) == "expired"
    assert SafeJobFetcher._classify(
        200,
        "text/html",
        "Frontend Lead at Other Corp",
        "React position",
        "Backend Intern",
        "Example Co",
    ) == "title_mismatch"


def test_safe_fetch_blocks_non_web_ports_before_dns() -> None:
    with pytest.raises(AppError) as raised:
        SafeJobFetcher._resolve_public_url("https://jobs.example.com:8443/role")

    assert raised.value.code == "JOB_SOURCE_PORT_BLOCKED"
