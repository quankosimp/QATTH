from __future__ import annotations

from app.core.errors import AppError
from app.schemas.product_admin_ops import ModelEvaluationMetricInput

QUALITY_POLICY_VERSION = "ai-quality-policy-v1"

QUALITY_POLICIES: dict[str, dict[str, tuple[str, float]]] = {
    "cv_extraction": {
        "field_precision": ("gte", 0.90),
        "field_recall": ("gte", 0.85),
    },
    "cv_analysis": {
        "schema_validity": ("gte", 0.99),
        "evidence_grounding": ("gte", 0.95),
    },
    "interview_evaluation": {
        "evidence_grounding": ("gte", 0.98),
        "rubric_agreement": ("gte", 0.80),
        "score_variance": ("lte", 0.15),
    },
    "interview_live": {
        "session_success_rate": ("gte", 0.95),
        "policy_compliance": ("gte", 0.99),
    },
    "job_search": {
        "citation_validity": ("gte", 0.95),
        "active_job_precision": ("gte", 0.90),
    },
    "job_embedding": {
        "retrieval_recall_at_10": ("gte", 0.80),
    },
    "job_explanation": {
        "evidence_grounding": ("gte", 0.98),
    },
}


def evaluate_model_metrics(
    purpose: str,
    metrics: list[ModelEvaluationMetricInput],
) -> tuple[str, dict[str, float], list[dict[str, object]]]:
    policy = QUALITY_POLICIES.get(purpose)
    if policy is None:
        raise AppError(422, "AI_EVAL_POLICY_NOT_FOUND", "No quality policy exists for this model purpose")
    metric_values = {metric.name: metric.value for metric in metrics}
    if len(metric_values) != len(metrics):
        raise AppError(422, "AI_EVAL_METRIC_DUPLICATED", "Evaluation metric names must be unique")
    if set(metric_values) != set(policy):
        raise AppError(
            422,
            "AI_EVAL_METRICS_INVALID",
            "Evaluation metrics do not match the quality policy",
            details={"required_metrics": sorted(policy)},
        )

    criteria: list[dict[str, object]] = []
    for name, (operator, threshold) in policy.items():
        value = metric_values[name]
        passed = value >= threshold if operator == "gte" else value <= threshold
        criteria.append(
            {
                "name": name,
                "value": value,
                "operator": operator,
                "threshold": threshold,
                "passed": passed,
            }
        )
    return (
        "passed" if all(bool(item["passed"]) for item in criteria) else "failed",
        metric_values,
        criteria,
    )
