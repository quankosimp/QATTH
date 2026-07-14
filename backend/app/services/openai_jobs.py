from __future__ import annotations

import json
import os
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx

from app.core.errors import AppError


class OpenAIJobsAdapter:
    def __init__(self) -> None:
        from app.services.runtime_configuration import runtime_model_configuration

        self.api_key = os.getenv("OPENAI_API_KEY", "")
        self.base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
        search_runtime = runtime_model_configuration("job_search", "openai", os.getenv("OPENAI_JOB_SEARCH_MODEL", "gpt-4.1-mini"))
        embedding_runtime = runtime_model_configuration("job_embedding", "openai", os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small"))
        self.search_model = search_runtime["model"]
        self.search_configuration = search_runtime["configuration"]
        self.embedding_model = embedding_runtime["model"]
        self.timeout = float(os.getenv("OPENAI_TIMEOUT_SECONDS", "120"))

    def live_search(self, query: str, filters: dict[str, Any], maximum_results: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        schema = {
            "type": "object",
            "additionalProperties": False,
            "required": ["jobs"],
            "properties": {
                "jobs": {
                    "type": "array",
                    "maxItems": min(maximum_results, 30),
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["title", "company_name", "location", "remote_mode", "employment_type", "seniority", "description", "skills", "source_url", "source_job_id", "posted_at"],
                        "properties": {
                            "title": {"type": "string"},
                            "company_name": {"type": "string"},
                            "location": {"type": ["string", "null"]},
                            "remote_mode": {"type": "string", "enum": ["onsite", "hybrid", "remote", "unknown"]},
                            "employment_type": {"type": ["string", "null"]},
                            "seniority": {"type": ["string", "null"]},
                            "description": {"type": ["string", "null"]},
                            "skills": {"type": "array", "items": {"type": "string"}},
                            "source_url": {"type": "string"},
                            "source_job_id": {"type": ["string", "null"]},
                            "posted_at": {"type": ["string", "null"]},
                        },
                    },
                }
            },
        }
        prompt = (
            "Find currently open jobs matching this query. Prefer direct employer or reputable job-board detail pages, "
            "not search result pages. Do not invent salary, requirements, or URLs. Return only jobs supported by cited web sources. "
            "Query: " + query + ". Filters: " + json.dumps(filters, ensure_ascii=False)
        )
        if self.search_configuration.get("instruction_prefix"):
            prompt = str(self.search_configuration["instruction_prefix"]) + "\n" + prompt
        raw = self._responses(
            {
                "model": self.search_model,
                "store": False,
                "input": prompt,
                "tools": [
                    {
                        "type": "web_search",
                        "search_context_size": "medium",
                        "user_location": {"type": "approximate", "country": "VN"},
                    }
                ],
                "tool_choice": "required",
                "text": {"format": {"type": "json_schema", "name": "live_jobs", "strict": True, "schema": schema}},
            }
        )
        output_text, citations = self._text_and_citations(raw)
        try:
            jobs = json.loads(output_text).get("jobs", [])
        except (json.JSONDecodeError, AttributeError) as exc:
            raise AppError(502, "WEB_SEARCH_RESPONSE_INVALID", "Web search returned invalid job data", retryable=True) from exc
        cited = {self._normalize_url(item["url"]): item for item in citations if item.get("url")}
        accepted = []
        for job in jobs:
            normalized = self._normalize_url(str(job.get("source_url") or ""))
            citation = cited.get(normalized)
            if citation is None:
                continue
            job["source_url"] = citation["url"]
            job["citation_title"] = citation.get("title")
            accepted.append(job)
        return accepted, {"provider_run_id": raw.get("id"), "citations": citations, "usage": raw.get("usage", {})}

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        self._require_key()
        try:
            response = httpx.post(
                self.base_url + "/embeddings",
                headers=self._headers(),
                json={"model": self.embedding_model, "input": texts, "dimensions": 1536},
                timeout=self.timeout,
            )
            response.raise_for_status()
            rows = sorted(response.json().get("data", []), key=lambda item: item["index"])
            return [row["embedding"] for row in rows]
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            raise AppError(502, "EMBEDDING_PROVIDER_ERROR", "Embedding request failed", retryable=True) from exc

    def explain(self, candidate: dict[str, Any], job: dict[str, Any]) -> dict[str, Any]:
        schema = {
            "type": "object",
            "additionalProperties": False,
            "required": ["reasons", "gaps"],
            "properties": {
                "reasons": {"type": "array", "items": {"type": "string"}, "maxItems": 5},
                "gaps": {"type": "array", "items": {"type": "string"}, "maxItems": 5},
            },
        }
        prompt = (
            "Explain this already-ranked job match. Use only supplied candidate and job evidence. Do not change rank or invent salary/skills. "
            + json.dumps({"candidate": candidate, "job": job}, ensure_ascii=False)
        )
        raw = self._responses(
            {
                "model": self.search_model,
                "store": False,
                "input": prompt,
                "text": {"format": {"type": "json_schema", "name": "job_match_explanation", "strict": True, "schema": schema}},
            }
        )
        text, _ = self._text_and_citations(raw)
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise AppError(502, "EXPLANATION_RESPONSE_INVALID", "Match explanation was invalid", retryable=True) from exc

    def _responses(self, body: dict[str, Any]) -> dict[str, Any]:
        self._require_key()
        try:
            response = httpx.post(self.base_url + "/responses", headers=self._headers(), json=body, timeout=self.timeout)
            response.raise_for_status()
            raw = response.json()
        except httpx.TimeoutException as exc:
            raise AppError(504, "OPENAI_TIMEOUT", "OpenAI request timed out", retryable=True) from exc
        except (httpx.HTTPError, ValueError) as exc:
            status_code = getattr(getattr(exc, "response", None), "status_code", None)
            raise AppError(502, "OPENAI_REQUEST_FAILED", "OpenAI request failed", details={"provider_status": status_code}, retryable=status_code is None or status_code == 429 or status_code >= 500) from exc
        if raw.get("status") != "completed":
            raise AppError(502, "OPENAI_RESPONSE_INCOMPLETE", "OpenAI response was incomplete", retryable=True)
        return raw

    @staticmethod
    def _text_and_citations(raw: dict[str, Any]) -> tuple[str, list[dict[str, Any]]]:
        for item in raw.get("output", []):
            if item.get("type") != "message":
                continue
            for part in item.get("content", []):
                if part.get("type") == "output_text":
                    citations = [entry for entry in part.get("annotations", []) if entry.get("type") == "url_citation"]
                    return str(part.get("text") or ""), citations
        raise AppError(502, "OPENAI_RESPONSE_INVALID", "OpenAI returned no output text", retryable=True)

    def _require_key(self) -> None:
        if not self.api_key:
            raise AppError(503, "OPENAI_NOT_CONFIGURED", "OpenAI API key is not configured")

    def _headers(self) -> dict[str, str]:
        return {"Authorization": "Bearer " + self.api_key, "Content-Type": "application/json"}

    @staticmethod
    def _normalize_url(url: str) -> str:
        parts = urlsplit(url)
        return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/"), parts.query, ""))
