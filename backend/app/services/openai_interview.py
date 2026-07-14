from __future__ import annotations

import json
import os
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field

from backend.app.core.errors import AppError
from backend.app.schemas.product_interview import EvidenceFinding


class InterviewEvaluationOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    technical_depth: float = Field(ge=0, le=100)
    communication: float = Field(ge=0, le=100)
    problem_solving: float = Field(ge=0, le=100)
    evidence_quality: float = Field(ge=0, le=100)
    role_fit: float = Field(ge=0, le=100)
    strengths: list[EvidenceFinding]
    gaps: list[EvidenceFinding]
    actions: list[str]


class OpenAIInterviewEvaluator:
    def __init__(self) -> None:
        from backend.app.services.runtime_configuration import runtime_model_configuration

        self.api_key = os.getenv("OPENAI_API_KEY", "")
        fallback_model = os.getenv("OPENAI_INTERVIEW_MODEL", os.getenv("OPENAI_CV_MODEL", "gpt-4.1-mini"))
        self.runtime = runtime_model_configuration("interview_evaluation", "openai", fallback_model)
        self.model = self.runtime["model"]
        self.base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
        self.timeout = float(os.getenv("OPENAI_TIMEOUT_SECONDS", "120"))

    def evaluate(
        self,
        transcript: list[dict[str, Any]],
        cv_snapshot: dict[str, Any],
        plan_snapshot: dict[str, Any],
        rubric_version: str,
    ) -> tuple[InterviewEvaluationOutput, dict[str, Any]]:
        if not self.api_key:
            raise AppError(503, "AI_PROVIDER_NOT_CONFIGURED", "OpenAI API key is not configured")
        schema = InterviewEvaluationOutput.model_json_schema()
        self._make_strict(schema)
        instruction = (
            "Evaluate an IT student interview using only the supplied transcript and CV snapshot. "
            "Do not infer facts that are not present. Every strength or gap must reference one or more "
            "existing transcript event IDs. Score each dimension from 0 to 100. The result supports coaching, "
            "not hiring decisions. Rubric version: " + rubric_version + ". Input JSON: "
            + json.dumps(
                {"transcript": transcript, "cv_snapshot": cv_snapshot, "plan": plan_snapshot},
                ensure_ascii=False,
                separators=(",", ":"),
            )
        )
        if self.runtime["configuration"].get("instruction_prefix"):
            instruction = str(self.runtime["configuration"]["instruction_prefix"]) + "\n" + instruction
        body = {
            "model": self.model,
            "store": False,
            "input": [{"role": "user", "content": [{"type": "input_text", "text": instruction}]}],
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "interview_evaluation",
                    "strict": True,
                    "schema": schema,
                }
            },
        }
        try:
            response = httpx.post(
                self.base_url + "/responses",
                headers={"Authorization": "Bearer " + self.api_key, "Content-Type": "application/json"},
                json=body,
                timeout=self.timeout,
            )
            response.raise_for_status()
            raw = response.json()
        except httpx.TimeoutException as exc:
            raise AppError(504, "AI_PROVIDER_TIMEOUT", "Interview evaluator timed out", retryable=True) from exc
        except (httpx.HTTPError, ValueError) as exc:
            status_code = getattr(getattr(exc, "response", None), "status_code", None)
            raise AppError(
                502,
                "AI_PROVIDER_ERROR",
                "Interview evaluation request failed",
                details={"provider_status": status_code},
                retryable=status_code is None or status_code == 429 or status_code >= 500,
            ) from exc
        text = self._output_text(raw)
        try:
            output = InterviewEvaluationOutput.model_validate_json(text)
        except ValueError as exc:
            raise AppError(502, "AI_RESPONSE_INVALID", "Interview evaluator returned invalid output", retryable=True) from exc
        return output, {"provider_run_id": raw.get("id"), "usage": raw.get("usage", {})}

    @classmethod
    def _make_strict(cls, node: Any) -> None:
        if isinstance(node, dict):
            if node.get("type") == "object" or "properties" in node:
                node["additionalProperties"] = False
                if "properties" in node:
                    node["required"] = list(node["properties"])
            for value in node.values():
                cls._make_strict(value)
        elif isinstance(node, list):
            for value in node:
                cls._make_strict(value)

    @staticmethod
    def _output_text(raw: dict[str, Any]) -> str:
        if raw.get("status") != "completed":
            raise AppError(502, "AI_RESPONSE_INCOMPLETE", "Interview evaluation was incomplete", retryable=True)
        for item in raw.get("output", []):
            for part in item.get("content", []):
                if part.get("type") == "refusal":
                    raise AppError(422, "AI_RESPONSE_REFUSED", "Interview evaluation was refused")
                if part.get("type") == "output_text" and part.get("text"):
                    return str(part["text"])
        raise AppError(502, "AI_RESPONSE_INVALID", "Interview evaluator returned no output", retryable=True)
