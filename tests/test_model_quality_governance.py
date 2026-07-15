from pathlib import Path

import pytest

from app.core.errors import AppError
from app.main import app
from app.schemas.product_admin_ops import ModelEvaluationMetricInput
from app.services.model_quality import QUALITY_POLICY_VERSION, evaluate_model_metrics
from app.services.runtime_configuration import _rollout_bucket


ROOT = Path(__file__).resolve().parents[1]


def test_cv_and_interview_quality_policies_compute_server_side_gates() -> None:
    status, metrics, criteria = evaluate_model_metrics(
        "cv_extraction",
        [
            ModelEvaluationMetricInput(name="field_precision", value=0.93),
            ModelEvaluationMetricInput(name="field_recall", value=0.88),
        ],
    )
    assert QUALITY_POLICY_VERSION == "ai-quality-policy-v1"
    assert status == "passed"
    assert metrics == {"field_precision": 0.93, "field_recall": 0.88}
    assert all(item["passed"] for item in criteria)

    failed, _, variance_criteria = evaluate_model_metrics(
        "interview_evaluation",
        [
            ModelEvaluationMetricInput(name="evidence_grounding", value=0.99),
            ModelEvaluationMetricInput(name="rubric_agreement", value=0.85),
            ModelEvaluationMetricInput(name="score_variance", value=0.20),
        ],
    )
    assert failed == "failed"
    assert next(item for item in variance_criteria if item["name"] == "score_variance")["operator"] == "lte"


def test_quality_policy_rejects_missing_or_user_defined_metrics() -> None:
    with pytest.raises(AppError) as raised:
        evaluate_model_metrics(
            "cv_extraction",
            [ModelEvaluationMetricInput(name="quality_score", value=1.0)],
        )
    assert raised.value.code == "AI_EVAL_METRICS_INVALID"


def test_rollout_assignment_is_stable_and_bounded() -> None:
    first = _rollout_bucket("cv_extraction", "configuration-1", "request-1")
    assert first == _rollout_bucket("cv_extraction", "configuration-1", "request-1")
    assert 0 <= first < 100
    assert len({_rollout_bucket("cv_extraction", "configuration-1", f"request-{i}") for i in range(100)}) > 20


def test_admin_api_exposes_eval_evidence_and_staged_activation_contract() -> None:
    path = "/v1/admin/model-configurations/{configuration_id}/evaluation-reports"
    schema = app.openapi()
    assert {"get", "post"}.issubset(schema["paths"][path])
    activation = schema["components"]["schemas"]["ActivateModelConfigurationRequest"]
    assert {"reason", "evaluation_report_id", "rollout_percentage"}.issubset(activation["required"])
    assert activation["properties"]["rollout_percentage"]["maximum"] == 100


def test_activation_and_database_contract_enforce_quality_governance() -> None:
    service = (ROOT / "backend/app/services/product_admin_ops.py").read_text()
    runtime = (ROOT / "backend/app/services/runtime_configuration.py").read_text()
    migration = (ROOT / "migrations/versions/20260715_0034_model_quality_governance.py").read_text()

    assert "AI_EVAL_GATE_FAILED" in service
    assert "MODEL_CANARY_BASELINE_REQUIRED" in service
    assert "_rollout_bucket" in runtime
    assert "uq_product_model_configuration_active_purpose" in migration
    assert "trg_product_model_evaluation_report_immutable" in migration
    assert "trg_product_model_configuration_version_immutable" in migration
