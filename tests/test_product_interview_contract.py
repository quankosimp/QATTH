from app.main import app


def test_product_interview_rest_contract_is_exposed() -> None:
    paths = app.openapi()["paths"]
    expected = {
        "/v1/interviews": {"get", "post"},
        "/v1/interviews/{interview_id}": {"get"},
        "/v1/interviews/{interview_id}/realtime-token": {"post"},
        "/v1/interviews/{interview_id}/end": {"post"},
        "/v1/interviews/{interview_id}/report": {"get"},
        "/v1/interviews/{interview_id}/report/retry": {"post"},
        "/v1/interviews/{interview_id}/cancel": {"post"},
        "/v1/interviews/{interview_id}/feedback": {"post"},
    }
    for path, methods in expected.items():
        assert path in paths
        assert methods.issubset(paths[path])


def test_interview_duration_is_bounded_by_product_credit_policy() -> None:
    schema = app.openapi()["components"]["schemas"]["CreateInterviewRequest"]
    duration = schema["properties"]["duration_minutes"]
    assert duration["minimum"] == 5
    assert duration["maximum"] == 30


def test_interview_mutations_require_idempotency_key() -> None:
    paths = app.openapi()["paths"]
    for path in (
        "/v1/interviews",
        "/v1/interviews/{interview_id}/end",
        "/v1/interviews/{interview_id}/cancel",
        "/v1/interviews/{interview_id}/report/retry",
    ):
        header = next(item for item in paths[path]["post"]["parameters"] if item["name"] == "Idempotency-Key")
        assert header["required"] is True


def test_interview_report_exposes_attempt_and_ai_lineage() -> None:
    schema = app.openapi()["components"]["schemas"]["InterviewReportView"]
    assert {"attempt_number", "model", "prompt_version", "usage", "estimated_cost_minor"}.issubset(schema["properties"])
