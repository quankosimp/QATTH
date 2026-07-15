from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_recommendation_contract_exposes_product_routes() -> None:
    source = (ROOT / "backend/app/api/v1/recommendations.py").read_text()
    assert '"/jobs/{job_id}/interactions"' in source
    assert '"/job-applications"' in source
    assert '"/job-applications/{application_id}"' in source
    assert '"/recommendation-runs"' in source
    assert '"/recommendation-runs/{run_id}/results"' in source
    assert 'alias="Idempotency-Key"' in source


def test_recommendations_persist_versioned_evidence() -> None:
    source = (ROOT / "backend/app/models/product_recommendations.py").read_text()
    assert "candidate_profile_version" in source
    assert "ranking_version" in source
    assert "score_breakdown" in source
    assert "evidence" in source
    assert "product_job_application_events" in source
    assert "product_job_moderation_cases" in source


def test_recommendation_mutations_require_consent_and_idempotency() -> None:
    api = (ROOT / "backend/app/api/v1/recommendations.py").read_text()
    service = (ROOT / "backend/app/services/product_recommendations.py").read_text()
    assert api.count('alias="Idempotency-Key"') >= 4
    assert "require_consent" in service
    assert "IdempotencyService" in service


def test_recommendation_ranking_keeps_required_candidate_and_job_signals() -> None:
    service = (ROOT / "backend/app/services/product_recommendations.py").read_text()
    assert '"role_preference"' in service
    assert '"location_preference"' in service
    assert '"work_mode_preference"' in service
    assert '"interview_supported_fit"' in service
    assert '"freshness"' in service
    assert "No explicit candidate evidence found for:" in service
