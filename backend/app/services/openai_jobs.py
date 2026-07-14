from __future__ import annotations

import json
import math
from typing import Any, Literal
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx
from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from app.core.config import Settings, get_settings
from app.core.errors import AppError
from app.core.provider_resilience import get_provider_executor


class LiveJobCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=500)
    company_name: str = Field(min_length=1, max_length=500)
    location: str | None = Field(default=None, max_length=500)
    remote_mode: Literal["onsite", "hybrid", "remote", "unknown"]
    employment_type: str | None = Field(default=None, max_length=100)
    seniority: str | None = Field(default=None, max_length=100)
    salary_min_minor: int | None = Field(default=None, ge=0)
    salary_max_minor: int | None = Field(default=None, ge=0)
    salary_currency: str | None = Field(default=None, min_length=3, max_length=3)
    salary_period: str | None = Field(default=None, max_length=20)
    description: str | None = Field(default=None, max_length=20_000)
    skills: list[str] = Field(default_factory=list, max_length=50)
    source_url: AnyHttpUrl
    source_job_id: str | None = Field(default=None, max_length=255)
    posted_at: str | None = Field(default=None, max_length=100)

    @field_validator("skills")
    @classmethod
    def validate_skills(cls, values: list[str]) -> list[str]:
        if any(not value.strip() or len(value) > 100 for value in values):
            raise ValueError("skills must contain non-empty values up to 100 characters")
        return values

    @field_validator("salary_currency")
    @classmethod
    def normalize_currency(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.upper()
        if not value.isalpha():
            raise ValueError("salary_currency must be an ISO 4217 code")
        return value

    @model_validator(mode="after")
    def validate_salary(self) -> "LiveJobCandidate":
        if self.salary_min_minor is not None and self.salary_max_minor is not None:
            if self.salary_min_minor > self.salary_max_minor:
                raise ValueError("salary_min_minor must not exceed salary_max_minor")
        if (self.salary_min_minor is not None or self.salary_max_minor is not None) and not self.salary_currency:
            raise ValueError("salary_currency is required when salary is present")
        return self


class LiveJobsPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    jobs: list[LiveJobCandidate] = Field(max_length=30)


class OpenAIJobsAdapter:
    tracking_query_keys = {
        "fbclid",
        "gclid",
        "mc_cid",
        "mc_eid",
        "ref_src",
        "ref_url",
    }

    def __init__(self, settings: Settings | None = None) -> None:
        from app.services.runtime_configuration import runtime_model_configuration

        self.settings = settings or get_settings()
        self.api_key = self.settings.openai_api_key or ""
        self.base_url = "https://api.openai.com/v1"
        search_runtime = runtime_model_configuration("job_search", "openai", self.settings.openai_search_model)
        embedding_runtime = runtime_model_configuration("job_embedding", "openai", self.settings.openai_embedding_model)
        self.search_model = search_runtime["model"]
        self.search_configuration = search_runtime["configuration"]
        self.search_runtime = search_runtime
        self.embedding_model = embedding_runtime["model"]
        self.timeout = float(self.settings.openai_timeout_seconds)

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
                        "required": ["title", "company_name", "location", "remote_mode", "employment_type", "seniority", "salary_min_minor", "salary_max_minor", "salary_currency", "salary_period", "description", "skills", "source_url", "source_job_id", "posted_at"],
                        "properties": {
                            "title": {"type": "string"},
                            "company_name": {"type": "string"},
                            "location": {"type": ["string", "null"]},
                            "remote_mode": {"type": "string", "enum": ["onsite", "hybrid", "remote", "unknown"]},
                            "employment_type": {"type": ["string", "null"]},
                            "seniority": {"type": ["string", "null"]},
                            "salary_min_minor": {"type": ["integer", "null"], "minimum": 0},
                            "salary_max_minor": {"type": ["integer", "null"], "minimum": 0},
                            "salary_currency": {"type": ["string", "null"]},
                            "salary_period": {"type": ["string", "null"]},
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
        web_search_tool: dict[str, Any] = {
            "type": "web_search",
            "search_context_size": "medium",
            "external_web_access": self.settings.job_search_live_external_access,
            "user_location": {
                "type": "approximate",
                "country": self.settings.job_search_country_code.upper(),
            },
        }
        if self.settings.job_search_allowed_domains or self.settings.job_search_blocked_domains:
            web_search_tool["filters"] = {
                "allowed_domains": self.settings.job_search_allowed_domains,
                "blocked_domains": self.settings.job_search_blocked_domains,
            }
        raw = self._responses(
            {
                "model": self.search_model,
                "store": False,
                "input": prompt,
                "tools": [web_search_tool],
                "tool_choice": "required",
                "include": ["web_search_call.action.sources"],
                "text": {"format": {"type": "json_schema", "name": "live_jobs", "strict": True, "schema": schema}},
            }
        )
        output_text, citations = self._text_and_citations(raw)
        try:
            jobs = LiveJobsPayload.model_validate_json(output_text).jobs
        except ValidationError as exc:
            raise AppError(502, "WEB_SEARCH_RESPONSE_INVALID", "Web search returned invalid job data", retryable=True) from exc
        search_calls, sources = self._search_evidence(raw)
        evidence = self._sanitize_links([*citations, *sources])
        cited = {self._normalize_url(item["url"]): item for item in evidence if item.get("url")}
        accepted = []
        for job in jobs:
            item = job.model_dump(mode="json")
            normalized = self._normalize_url(str(item.get("source_url") or ""))
            citation = cited.get(normalized)
            if citation is None:
                continue
            item["source_url"] = citation["url"]
            item["citation_title"] = citation.get("title")
            accepted.append(item)
        if jobs and not accepted:
            raise AppError(
                502,
                "WEB_SEARCH_PROVENANCE_MISSING",
                "Web search jobs were not backed by provider source evidence",
                retryable=True,
            )
        return accepted, {
            **self._metadata(raw, "job-search-v1"),
            "citations": self._sanitize_links(citations),
            "sources": self._sanitize_links(sources),
            "search_calls": search_calls,
        }

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        self._require_key()
        def invoke() -> list[list[float]]:
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

        return get_provider_executor().execute("openai", "job_embedding", invoke).value

    def explain(self, candidate: dict[str, Any], job: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
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
            return json.loads(text), self._metadata(raw, "job-explanation-v1")
        except json.JSONDecodeError as exc:
            raise AppError(502, "EXPLANATION_RESPONSE_INVALID", "Match explanation was invalid", retryable=True) from exc

    def _metadata(self, raw: dict[str, Any], fallback_prompt_version: str) -> dict[str, Any]:
        usage = raw.get("usage", {})
        execution = raw.get("_qatth_execution", {})
        return {
            "provider_run_id": raw.get("id"),
            "model": self.search_model,
            "model_configuration_id": self.search_runtime.get("id"),
            "prompt_version": str(
                self.search_configuration.get("prompt_version")
                or self.search_runtime.get("version")
                or fallback_prompt_version
            ),
            "usage": usage,
            "estimated_cost_minor": self._estimate_cost(usage),
            "correlation_id": execution.get("correlation_id"),
            "attempts": execution.get("attempts", 1),
            "latency_ms": execution.get("latency_ms"),
        }

    def _estimate_cost(self, usage: dict[str, Any]) -> int | None:
        input_rate = self.search_configuration.get("input_cost_minor_per_million")
        output_rate = self.search_configuration.get("output_cost_minor_per_million")
        if input_rate is None or output_rate is None:
            return None
        input_tokens = int(usage.get("input_tokens") or 0)
        output_tokens = int(usage.get("output_tokens") or 0)
        return math.ceil((input_tokens * int(input_rate) + output_tokens * int(output_rate)) / 1_000_000)

    def _responses(self, body: dict[str, Any]) -> dict[str, Any]:
        self._require_key()
        def invoke() -> dict[str, Any]:
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

        result = get_provider_executor().execute("openai", "job_search", invoke)
        raw = result.value
        raw["_qatth_execution"] = {
            "correlation_id": result.correlation_id,
            "attempts": result.attempts,
            "latency_ms": result.latency_ms,
        }
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

    @staticmethod
    def _search_evidence(raw: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        calls: list[dict[str, Any]] = []
        sources: list[dict[str, Any]] = []
        for item in raw.get("output", []):
            if item.get("type") != "web_search_call":
                continue
            if item.get("status") != "completed":
                raise AppError(502, "WEB_SEARCH_CALL_INCOMPLETE", "OpenAI web search call was incomplete", retryable=True)
            action = item.get("action") or {}
            calls.append(
                {
                    "id": str(item.get("id") or "")[:255],
                    "type": str(action.get("type") or "search")[:40],
                    "queries": [str(value)[:500] for value in (action.get("queries") or [])[:20]],
                }
            )
            sources.extend(action.get("sources") or item.get("sources") or [])
        if not calls:
            raise AppError(502, "WEB_SEARCH_NOT_EXECUTED", "OpenAI did not execute web search", retryable=True)
        return calls, sources

    @staticmethod
    def _sanitize_links(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        output: list[dict[str, Any]] = []
        seen: set[str] = set()
        for item in items[:200]:
            url = str(item.get("url") or "")[:2048]
            parsed = urlsplit(url)
            if (
                parsed.scheme not in {"http", "https"}
                or not parsed.hostname
                or parsed.username
                or parsed.password
            ):
                continue
            try:
                normalized = OpenAIJobsAdapter._normalize_url(url)
            except ValueError:
                continue
            if normalized in seen:
                continue
            seen.add(normalized)
            output.append(
                {
                    "url": url,
                    "title": str(item.get("title") or "")[:500] or None,
                    "type": str(item.get("type") or "web_source")[:80],
                }
            )
        return output

    def _require_key(self) -> None:
        if not self.api_key:
            raise AppError(503, "OPENAI_NOT_CONFIGURED", "OpenAI API key is not configured")

    def _headers(self) -> dict[str, str]:
        return {"Authorization": "Bearer " + self.api_key, "Content-Type": "application/json"}

    @staticmethod
    def _normalize_url(url: str) -> str:
        parts = urlsplit(url)
        if parts.scheme.lower() not in {"http", "https"} or not parts.hostname:
            return ""
        hostname = (parts.hostname or "").casefold().rstrip(".")
        port = parts.port
        netloc = hostname
        if port and not ((parts.scheme.lower() == "https" and port == 443) or (parts.scheme.lower() == "http" and port == 80)):
            netloc += ":" + str(port)
        query = urlencode(
            sorted(
                (key, value)
                for key, value in parse_qsl(parts.query, keep_blank_values=True)
                if not key.casefold().startswith("utm_")
                and key.casefold() not in OpenAIJobsAdapter.tracking_query_keys
            ),
            doseq=True,
        )
        return urlunsplit((parts.scheme.lower(), netloc, parts.path.rstrip("/") or "/", query, ""))
