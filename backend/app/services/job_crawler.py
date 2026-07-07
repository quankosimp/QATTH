import json
from pathlib import Path
from urllib.parse import urljoin
from urllib.robotparser import RobotFileParser

import httpx
from bs4 import BeautifulSoup
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.models.db import CrawlRun, JobPosting


class JobCrawlerService:
    user_agent = "QATTHBot/0.1 (+local MVP; contact: developer)"

    def __init__(self, *, db: Session) -> None:
        self.db = db

    async def run(self, *, source: str, query: str | None, max_pages: int) -> CrawlRun:
        crawl_run = CrawlRun(source=source, query=query, status="running")
        self.db.add(crawl_run)
        self.db.commit()
        self.db.refresh(crawl_run)

        try:
            if source == "seed":
                jobs = self._load_seed_jobs()
            elif source == "itviec":
                jobs = await self._crawl_itviec(query=query or "it", max_pages=max_pages)
            else:
                raise AppError(
                    status_code=422,
                    code="UNSUPPORTED_JOB_SOURCE",
                    message=f"Unsupported job source: {source}",
                    details={"supported_sources": ["seed", "itviec"]},
                )

            for payload in jobs:
                self._upsert_job(payload)

            crawl_run.status = "completed"
            crawl_run.jobs_found = len(jobs)
            self.db.commit()
            self.db.refresh(crawl_run)
            return crawl_run
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
                code="CRAWL_FAILED",
                message="Job crawl failed.",
                details={"source": source, "reason": str(exc)},
            ) from exc

    def _load_seed_jobs(self) -> list[dict]:
        path = Path(__file__).parents[1] / "data" / "seed_jobs.json"
        return json.loads(path.read_text(encoding="utf-8"))

    async def _crawl_itviec(self, *, query: str, max_pages: int) -> list[dict]:
        base_url = "https://itviec.com"
        path = "/it-jobs"
        if not self._robots_allowed(base_url=base_url, path=path):
            raise AppError(
                status_code=403,
                code="ROBOTS_DISALLOW",
                message="robots.txt does not allow crawling this path.",
                details={"source": "itviec", "path": path},
            )

        jobs: list[dict] = []
        headers = {"User-Agent": self.user_agent}
        async with httpx.AsyncClient(headers=headers, timeout=20.0, follow_redirects=True) as client:
            for page in range(1, max_pages + 1):
                response = await client.get(f"{base_url}{path}", params={"page": page, "q": query})
                response.raise_for_status()
                jobs.extend(self._parse_itviec_listing(response.text, base_url=base_url))

        return jobs

    def _parse_itviec_listing(self, html: str, *, base_url: str) -> list[dict]:
        soup = BeautifulSoup(html, "html.parser")
        jobs: list[dict] = []
        seen_urls: set[str] = set()

        for anchor in soup.select("a[href*='/it-jobs/']"):
            href = anchor.get("href")
            title = " ".join(anchor.get_text(" ", strip=True).split())
            if not href or not title or len(title) < 4:
                continue

            source_url = urljoin(base_url, href)
            if source_url in seen_urls:
                continue
            seen_urls.add(source_url)

            container = anchor.find_parent(["article", "div", "li"]) or anchor
            text = " ".join(container.get_text(" ", strip=True).split())
            skills = self._extract_skill_hints(text)
            external_id = source_url.rstrip("/").split("/")[-1]
            jobs.append(
                {
                    "source": "itviec",
                    "external_id": external_id,
                    "source_url": source_url,
                    "title": title[:255],
                    "company": "Unknown",
                    "location": self._find_location(text),
                    "working_model": self._find_working_model(text),
                    "level": self._find_level(text),
                    "salary_range": None,
                    "skills": skills,
                    "jd_text": text or title,
                    "posted_at": None,
                    "raw_payload": {"listing_text": text},
                }
            )

        return jobs

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

    def _robots_allowed(self, *, base_url: str, path: str) -> bool:
        parser = RobotFileParser()
        parser.set_url(urljoin(base_url, "/robots.txt"))
        try:
            parser.read()
        except Exception:
            return False
        return parser.can_fetch(self.user_agent, urljoin(base_url, path))

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
        ]
        lowered = text.lower()
        return [skill for skill in known if skill in lowered]

    def _find_location(self, text: str) -> str | None:
        for location in ["Ho Chi Minh", "Ha Noi", "Da Nang", "Remote"]:
            if location.lower() in text.lower():
                return location
        return None

    def _find_working_model(self, text: str) -> str | None:
        lowered = text.lower()
        if "remote" in lowered:
            return "remote"
        if "hybrid" in lowered:
            return "hybrid"
        if "at office" in lowered or "onsite" in lowered:
            return "at_office"
        return None

    def _find_level(self, text: str) -> str | None:
        lowered = text.lower()
        for level in ["internship", "fresher", "junior", "senior", "manager"]:
            if level in lowered:
                return level
        return None
