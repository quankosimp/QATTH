from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_recommendation_feedback_has_dedicated_append_only_contract() -> None:
    api = (ROOT / "backend/app/api/v1/recommendations.py").read_text()
    model = (ROOT / "backend/app/models/product_recommendations.py").read_text()
    migration = (ROOT / "migrations/versions/20260715_0022_recommendation_feedback.py").read_text()
    assert '"/recommendation-runs/{run_id}/feedback"' in api
    assert "class RecommendationFeedback" in model
    assert "product_recommendation_feedback" in migration
    assert "uq_product_recommendation_feedback_idempotency" in migration


def test_feedback_attribution_and_training_eligibility_are_server_derived() -> None:
    schema = (ROOT / "backend/app/schemas/product_recommendations.py").read_text()
    service = (ROOT / "backend/app/services/product_recommendations.py").read_text()
    request_body = schema.split("class CreateRecommendationFeedbackRequest", 1)[1].split(
        "class RecommendationFeedbackView", 1
    )[0]
    assert "experiment_assignment" not in request_body
    assert "training_eligible" not in request_body
    for evidence in (
        "RecommendationMatch.run_id == run.id",
        "run.experiment_assignment",
        "run.ranking_version",
        'UserConsent.purpose == "model_training"',
        'training_consent.status == "granted"',
        '"rank": match.rank',
        '"score_breakdown": match.score_breakdown',
    ):
        assert evidence in service
