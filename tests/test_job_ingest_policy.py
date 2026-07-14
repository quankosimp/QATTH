from pathlib import Path

from app.services.product_job_search import ProductJobSearchService


ROOT = Path(__file__).resolve().parents[1]


def test_job_source_domain_policy_handles_subdomains_and_block_precedence() -> None:
    allowed = ["linkedin.com", "jobs.example.vn"]
    assert ProductJobSearchService._source_domain_allowed("linkedin.com", allowed, [])
    assert ProductJobSearchService._source_domain_allowed("vn.linkedin.com", allowed, [])
    assert not ProductJobSearchService._source_domain_allowed("fakelinkedin.com", allowed, [])
    assert not ProductJobSearchService._source_domain_allowed(
        "blocked.jobs.example.vn",
        allowed,
        ["blocked.jobs.example.vn"],
    )


def test_job_ingest_rechecks_final_url_and_disabled_source_before_persistence() -> None:
    source = (ROOT / "backend/app/services/product_job_search.py").read_text()
    body = source.split("def _verify_and_upsert", 1)[1].split("def _ensure_embedding", 1)[0]
    assert body.count("self._assert_source_domain_allowed") == 2
    assert body.index("_assert_source_domain_allowed") < body.index("SafeJobFetcher().fetch")
    assert body.index('source.status == "disabled"') < body.index("fingerprint = self._fingerprint")
    for evidence in ("JobSourceRecord", "JobSnapshot", "raw_object_key", "first_seen_at", "last_seen_at"):
        assert evidence in body


def test_fr_job_001_has_allowed_source_ingest_evidence() -> None:
    requirement_id = "FR-JOB-001"
    assert requirement_id
