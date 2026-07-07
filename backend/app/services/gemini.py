import asyncio
import json
import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from app.core.config import Settings, get_settings
from app.core.errors import AppError


class GeminiService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    @property
    def is_configured(self) -> bool:
        return bool(self.settings.gemini_api_key)

    async def extract_cv_profile(
        self,
        *,
        file_path: Path,
        mime_type: str,
        response_schema: type[BaseModel],
        target_role: str | None,
        language: str,
    ) -> dict[str, Any]:
        if not self.is_configured:
            return self._demo_cv_profile(file_path=file_path, target_role=target_role, language=language)

        return await asyncio.to_thread(
            self._extract_cv_profile_sync,
            file_path,
            mime_type,
            response_schema,
            target_role,
            language,
        )

    async def evaluate_interview(
        self,
        *,
        profile: dict[str, Any],
        transcript: list[dict[str, Any]],
        target_role: str,
        language: str,
        response_schema: type[BaseModel],
    ) -> dict[str, Any]:
        if not self.is_configured:
            raise AppError(
                status_code=503,
                code="GEMINI_NOT_CONFIGURED",
                message="GEMINI_API_KEY is required for Gemini interview evaluation.",
            )

        return await asyncio.to_thread(
            self._evaluate_interview_sync,
            profile,
            transcript,
            target_role,
            language,
            response_schema,
        )

    def _extract_cv_profile_sync(
        self,
        file_path: Path,
        mime_type: str,
        response_schema: type[BaseModel],
        target_role: str | None,
        language: str,
    ) -> dict[str, Any]:
        try:
            from google import genai
            from google.genai import types
        except ImportError as exc:
            raise AppError(
                status_code=500,
                code="GEMINI_SDK_MISSING",
                message="google-genai is not installed.",
            ) from exc

        client = genai.Client(api_key=self.settings.gemini_api_key)
        uploaded_file = client.files.upload(
            file=str(file_path),
            config={"mime_type": mime_type},
        )

        prompt = self._cv_prompt(target_role=target_role, language=language)
        response = client.models.generate_content(
            model=self.settings.gemini_cv_model,
            contents=[uploaded_file, prompt],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=response_schema,
            ),
        )
        return self._coerce_json_response(response)

    def _evaluate_interview_sync(
        self,
        profile: dict[str, Any],
        transcript: list[dict[str, Any]],
        target_role: str,
        language: str,
        response_schema: type[BaseModel],
    ) -> dict[str, Any]:
        try:
            from google import genai
            from google.genai import types
        except ImportError as exc:
            raise AppError(
                status_code=500,
                code="GEMINI_SDK_MISSING",
                message="google-genai is not installed.",
            ) from exc

        prompt = (
            "You are a senior technical interviewer for entry-level IT hiring. "
            "Evaluate the candidate using the provided CV profile and interview transcript. "
            "Return JSON only in the requested schema. Be strict but fair. "
            f"Target role: {target_role}. Response language: {language}.\n\n"
            f"CV_PROFILE_JSON:\n{json.dumps(profile, ensure_ascii=False)}\n\n"
            f"TRANSCRIPT_JSON:\n{json.dumps(transcript, ensure_ascii=False)}"
        )
        client = genai.Client(api_key=self.settings.gemini_api_key)
        response = client.models.generate_content(
            model=self.settings.gemini_evaluation_model,
            contents=[prompt],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=response_schema,
            ),
        )
        return self._coerce_json_response(response)

    def _coerce_json_response(self, response: Any) -> dict[str, Any]:
        parsed = getattr(response, "parsed", None)
        if isinstance(parsed, BaseModel):
            return parsed.model_dump(mode="json")
        if isinstance(parsed, dict):
            return parsed

        text = getattr(response, "text", None) or getattr(response, "output_text", None)
        if not text:
            raise AppError(
                status_code=502,
                code="GEMINI_EMPTY_RESPONSE",
                message="Gemini returned an empty response.",
            )

        cleaned = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError as exc:
            raise AppError(
                status_code=502,
                code="GEMINI_INVALID_JSON",
                message="Gemini response was not valid JSON.",
                details={"preview": cleaned[:500]},
            ) from exc

    def _cv_prompt(self, *, target_role: str | None, language: str) -> str:
        return (
            "You are an expert technical recruiter for entry-level IT students. "
            "Extract the CV into the provided JSON schema only. "
            "Normalize technologies, infer target roles only from evidence, and add warnings for missing "
            "or low-confidence fields. "
            f"Preferred response language for free-text fields: {language}. "
            f"Target role context: {target_role or 'not provided'}."
        )

    def _demo_cv_profile(
        self,
        *,
        file_path: Path,
        target_role: str | None,
        language: str,
    ) -> dict[str, Any]:
        role = target_role or "Backend Developer Intern"
        warning = "Demo profile generated because GEMINI_API_KEY is not configured."
        return {
            "name": "Demo Student",
            "email": "demo.student@example.com",
            "phone": None,
            "location": "Vietnam",
            "summary": f"Student candidate interested in {role}.",
            "education": [
                {
                    "school": "Demo University",
                    "degree": "Bachelor",
                    "major": "Information Technology",
                    "start_year": None,
                    "end_year": None,
                    "gpa": None,
                }
            ],
            "skills": [
                {
                    "name": "Python",
                    "category": "programming_language",
                    "level": "intermediate",
                    "evidence": "Demo fallback.",
                },
                {
                    "name": "FastAPI",
                    "category": "framework",
                    "level": "beginner",
                    "evidence": "Demo fallback.",
                },
                {
                    "name": "SQL",
                    "category": "database",
                    "level": "beginner",
                    "evidence": "Demo fallback.",
                },
            ],
            "projects": [
                {
                    "name": file_path.stem,
                    "description": "Placeholder project inferred for local demo mode.",
                    "role": "Developer",
                    "technologies": ["Python", "FastAPI", "SQL"],
                    "outcomes": [],
                    "url": None,
                }
            ],
            "experience": [],
            "certifications": [],
            "languages": ["Vietnamese", "English"],
            "target_roles": [role],
            "seniority_estimate": "student",
            "raw_confidence": 0.35,
            "warnings": [warning],
        }
