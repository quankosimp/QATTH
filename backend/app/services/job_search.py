from __future__ import annotations

import hashlib

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.errors import AppError
from app.models.db import CrawlRun, JobPosting


class ExternalJobSearchService:
    serpapi_endpoint = "https://serpapi.com/search.json"

    def __init__(self, *, db: Session, settings: Settings | None = None) -> None:
        self.db = db
        self.settings = settings or get_settings()

    @property
    def is_configured(self) -> bool:
        return (
            self.settings.job_search_provider == "serpapi_google_jobs"
            and bool(self.settings.serpapi_api_key)
        )

    async def search_and_store(
        self, *, query: str, location: str | None, limit: int
    ) -> list[JobPosting]:
        if self.settings.job_search_provider != "serpapi_google_jobs":
            raise AppError(
                status_code=503,
                code="EXTERNAL_JOB_SEARCH_NOT_CONFIGURED",
                message="Unsupported external job search provider.",
                details={"provider": self.settings.job_search_provider},
            )
        if not self.settings.serpapi_api_key:
            raise AppError(
                status_code=503,
                code="EXTERNAL_JOB_SEARCH_NOT_CONFIGURED",
                message="SERPAPI_API_KEY is required for external live job search.",
            )

        crawl_run = CrawlRun(source="serpapi_google_jobs", query=query, status="running")
        self.db.add(crawl_run)
        self.db.commit()
        self.db.refresh(crawl_run)

        try:
            payload = await self._fetch(query=query, location=location)
            jobs = [
                self._upsert_job(item)
                for item in self._normalize_jobs(payload=payload, query=query)[:limit]
            ]
            crawl_run.status = "completed"
            crawl_run.jobs_found = len(jobs)
            self.db.commit()
            return jobs
        except AppError as exc:
            crawl_run.status = "failed"
            crawl_run.failure_reason = exc.message
            self.db.commit()
            raise
        except Exception as exc:
            crawl_run.status = "failed"
            crawl_run.failure_reason = str(exc)
            self.db.commit()
            raise AppError(
                status_code=502,
                code="EXTERNAL_JOB_SEARCH_FAILED",
                message="External job search failed.",
                details={"query": query, "reason": str(exc)},
            ) from exc

    async def _fetch(self, *, query: str, location: str | None) -> dict:
        params = {
            "engine": "google_jobs",
            "q": query,
            "location": location or self.settings.job_search_default_location,
            "api_key": self.settings.serpapi_api_key,
        }
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.get(self.serpapi_endpoint, params=params)
            response.raise_for_status()
            return response.json()

    def _normalize_jobs(self, *, payload: dict, query: str) -> list[dict]:
        results = payload.get("jobs_results") or []
        normalized: list[dict] = []
        for item in results:
            title = item.get("title") or "Untitled job"
            company = item.get("company_name") or "Unknown"
            apply_options = item.get("apply_options") or []
            first_apply = apply_options[0] if apply_options else {}
            source_url = first_apply.get("link") or item.get("share_link") or item.get("via") or ""
            external_id = item.get("job_id") or self._stable_external_id(
                title=title, company=company, source_url=source_url, query=query
            )
            description = item.get("description") or title
            normalized.append(
                {
                    "source": "serpapi_google_jobs",
                    "external_id": external_id,
                    "source_url": source_url or f"https://www.google.com/search?q={query}",
                    "title": title[:255],
                    "company": company[:255],
                    "location": item.get("location"),
                    "working_model": self._find_working_model(description),
                    "level": self._find_level(" ".join([title, description])),
                    "salary_range": None,
                    "skills": self._extract_skill_hints(" ".join([title, description])),
                    "jd_text": description,
                    "posted_at": self._posted_at(item),
                    "raw_payload": item,
                }
            )
        return normalized

    def _upsert_job(self, payload: dict) -> JobPosting:
        existing = self.db.scalar(
            select(JobPosting).where(
                JobPosting.source == payload["source"],
                JobPosting.external_id == payload["external_id"],
            )
        )
        if existing:
            job = existing
        else:
            job = JobPosting(
                source=payload["source"],
                external_id=payload["external_id"],
                source_url=payload["source_url"],
                title=payload["title"],
                company=payload["company"],
                jd_text=payload["jd_text"],
            )
            self.db.add(job)

        job.source_url = payload["source_url"]
        job.title = payload["title"]
        job.company = payload["company"]
        job.location = payload.get("location")
        job.working_model = payload.get("working_model")
        job.level = payload.get("level")
        job.salary_range = payload.get("salary_range")
        job.skills = payload.get("skills") or []
        job.jd_text = payload.get("jd_text") or payload["title"]
        job.posted_at = payload.get("posted_at")
        job.raw_payload = payload.get("raw_payload") or payload
        return job

    def _stable_external_id(self, *, title: str, company: str, source_url: str, query: str) -> str:
        raw = "|".join([title, company, source_url, query])
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]

    def _posted_at(self, item: dict) -> str | None:
        detected = item.get("detected_extensions") or {}
        return detected.get("posted_at") or item.get("via")

    def _extract_skill_hints(self, text: str) -> list[str]:
        known = [
            "python",
            "java",
            "javascript",
            "typescript",
            "react",
            "nodejs",
            "golang",
            "sql",
            "postgresql",
            "docker",
            "aws",
            "linux",
            "fastapi",
            "spring",
            ".net",
            "selenium",
            "postman",
            "excel",
            "power bi",
        ]
        lowered = text.lower()
        return [skill for skill in known if skill in lowered]

    def _find_working_model(self, text: str) -> str | None:
        lowered = text.lower()
        if "remote" in lowered:
            return "remote"
        if "hybrid" in lowered:
            return "hybrid"
        if "onsite" in lowered or "at office" in lowered:
            return "at_office"
        return None

    def _find_level(self, text: str) -> str | None:
        lowered = text.lower()
        for level in ["internship", "fresher", "junior", "senior", "manager"]:
            if level in lowered:
                return level
        if "intern" in lowered:
            return "internship"
        return None
