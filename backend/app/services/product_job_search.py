from __future__ import annotations

import base64
import hashlib
import json
import math
import re
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlparse

from sqlalchemy import Text, cast, func, literal, or_, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.core.identity_security import ProductCurrentUser
from app.models.identity import UserProductProfile
from app.models.product_cv import ProductCV, ProductCvVersion
from app.models.product_interview import ProductInterview, ProductInterviewReport
from app.models.product_jobs import (
    CandidateProfile,
    JobEmbedding,
    JobCatalogMaintenanceRun,
    JobSearchEvent,
    JobSearchDispatch,
    JobSearchResult,
    JobSearchRun,
    JobSnapshot,
    JobSource,
    JobSourceRecord,
    ProductJob,
)
from app.schemas.product_jobs import (
    CreateJobSearchRequest,
    JobMatchPage,
    JobMatchView,
    JobPage,
    JobSearchRunView,
    JobSourceReferenceView,
    JobView,
    SalaryView,
)
from app.services.openai_jobs import OpenAIJobsAdapter
from app.services.object_storage import ObjectStorage
from app.services.safe_job_fetch import SafeJobFetcher
from app.services.identity import IdentityService
from app.services.provider_usage import ProviderUsageService


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _cursor(created_at: datetime, item_id: str) -> str:
    return base64.urlsafe_b64encode((created_at.isoformat() + "|" + item_id).encode()).decode().rstrip("=")


def _parse_cursor(value: str) -> tuple[datetime, str]:
    try:
        decoded = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4)).decode()
        timestamp, item_id = decoded.rsplit("|", 1)
        return datetime.fromisoformat(timestamp), item_id
    except (ValueError, UnicodeDecodeError) as exc:
        raise AppError(422, "INVALID_CURSOR", "Cursor is invalid") from exc


class ProductJobSearchService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def create_run(
        self,
        current: ProductCurrentUser,
        payload: CreateJobSearchRequest,
        idempotency_key: str,
    ) -> JobSearchRun:
        request_hash = hashlib.sha256(
            payload.model_dump_json(exclude_none=False).encode("utf-8")
        ).hexdigest()
        existing = self.db.scalar(
            select(JobSearchRun).where(
                JobSearchRun.user_id == current.id,
                JobSearchRun.idempotency_key == idempotency_key,
            )
        )
        if existing is not None:
            if existing.request_hash != request_hash:
                raise AppError(
                    409,
                    "IDEMPOTENCY_KEY_REUSED",
                    "Idempotency-Key was already used with a different request",
                )
            return existing
        IdentityService(self.db).require_consent(current.id)
        if payload.cv_version_id:
            version = self.db.scalar(
                select(ProductCvVersion)
                .join(ProductCV, ProductCV.id == ProductCvVersion.cv_id)
                .where(
                    ProductCvVersion.id == payload.cv_version_id,
                    ProductCvVersion.user_id == current.id,
                    ProductCV.status == "active",
                )
            )
            if version is None:
                raise AppError(404, "CV_VERSION_NOT_FOUND", "CV version was not found")
        run = JobSearchRun(
            user_id=current.id,
            status="queued",
            mode=payload.mode,
            query_text=payload.query,
            filters=payload.filters.model_dump(mode="json"),
            maximum_results=payload.maximum_results,
            cv_version_id=payload.cv_version_id,
            progress={"sources_completed": 0, "jobs_discovered": 0, "jobs_verified": 0, "results_ready": 0},
            degraded_reasons=[],
            idempotency_key=idempotency_key,
            request_hash=request_hash,
        )
        self.db.add(run)
        self.db.flush()
        self.db.add(
            JobSearchDispatch(
                run_id=run.id,
                payload={"run_id": run.id},
            )
        )
        self._append_event(run.id, "run.started", {"mode": run.mode, "query": run.query_text})
        self.db.commit()
        self.db.refresh(run)
        self.publish_dispatch_for_run(run.id)
        return run

    def publish_dispatch_for_run(self, run_id: str) -> bool:
        dispatch = self.db.scalar(
            select(JobSearchDispatch)
            .where(JobSearchDispatch.run_id == run_id)
            .with_for_update()
        )
        if dispatch is None or dispatch.status == "published":
            return True
        dispatch.attempts += 1
        try:
            from app.workers.tasks import execute_product_job_search_task

            execute_product_job_search_task.delay(run_id)
        except Exception as exc:
            dispatch.last_error = str(exc)[:1000]
            dispatch.available_at = _utcnow() + timedelta(
                seconds=min(300, 2 ** min(dispatch.attempts, 8))
            )
            self.db.commit()
            return False
        dispatch.status = "published"
        dispatch.published_at = _utcnow()
        dispatch.last_error = None
        self.db.commit()
        return True

    def publish_pending_dispatches(self, limit: int = 100) -> int:
        dispatches = list(
            self.db.scalars(
                select(JobSearchDispatch)
                .where(
                    JobSearchDispatch.status == "pending",
                    JobSearchDispatch.available_at <= _utcnow(),
                )
                .order_by(JobSearchDispatch.created_at)
                .limit(limit)
            )
        )
        return sum(1 for item in dispatches if self.publish_dispatch_for_run(item.run_id))

    def execute(self, run_id: str) -> None:
        run = self.db.scalar(select(JobSearchRun).where(JobSearchRun.id == run_id).with_for_update())
        if run is None or run.status == "completed":
            return
        run.status = "searching"
        run.started_at = run.started_at or _utcnow()
        self.db.commit()
        candidate = self._candidate_profile(run)
        scored: dict[str, dict[str, Any]] = {}
        if run.mode in {"indexed", "hybrid"}:
            for row in self._hybrid_candidates(run.query_text, run.filters, candidate):
                scored[row["job"].id] = row
            run.progress = {**run.progress, "sources_completed": run.progress.get("sources_completed", 0) + 1}
            self.db.commit()
            self.emit(run.id, "source.progress", {"source": "indexed", "candidates": len(scored)})
        if run.mode in {"live", "hybrid"}:
            try:
                jobs, provider = OpenAIJobsAdapter().live_search(run.query_text, run.filters, run.maximum_results)
                ProviderUsageService(self.db).success(
                    user_id=run.user_id,
                    provider="openai",
                    purpose="job_search",
                    resource_type="job_search_run",
                    resource_id=run.id,
                    metadata=provider,
                )
                run.provider = "openai_web_search"
                run.provider_run_id = provider.get("provider_run_id")
                run.provider_model = provider.get("model")
                run.provider_model_configuration_id = provider.get("model_configuration_id")
                run.provider_usage = provider.get("usage", {})
                run.provider_estimated_cost_minor = provider.get("estimated_cost_minor")
                run.progress = {**run.progress, "jobs_discovered": len(jobs)}
                self.db.commit()
                self.emit(run.id, "source.progress", {"source": "openai_web_search", "discovered": len(jobs), "provider_run_id": provider.get("provider_run_id")})
                run.status = "verifying"
                self.db.commit()
                for item in jobs:
                    self.emit(
                        run.id,
                        "job.discovered",
                        {
                            "title": str(item.get("title") or "")[:300],
                            "company_name": str(item.get("company_name") or "")[:300],
                            "source_url_fingerprint": hashlib.sha256(
                                str(item.get("source_url") or "").encode("utf-8")
                            ).hexdigest(),
                        },
                    )
                    try:
                        job = self._verify_and_upsert(item, provider)
                    except AppError as exc:
                        self._degrade(run, exc.code)
                        continue
                    if not self._job_matches_filters(job, run.filters):
                        self.emit(run.id, "job.filtered", {"job_id": job.id, "reason": "structured_filters"})
                        continue
                    self.emit(run.id, "job.verified", {"job_id": job.id})
                    row = self._score(job, run.query_text, candidate, lexical=0.0, vector=0.0)
                    current = scored.get(job.id)
                    if current is None or row["final"] > current["final"]:
                        scored[job.id] = row
                run.progress = {**run.progress, "sources_completed": run.progress.get("sources_completed", 0) + 1, "jobs_verified": len([row for row in scored.values() if row["job"].verified_at])}
                self.db.commit()
            except AppError as exc:
                ProviderUsageService(self.db).failure(
                    user_id=run.user_id,
                    provider="openai",
                    purpose="job_search",
                    resource_type="job_search_run",
                    resource_id=run.id,
                    error=exc,
                )
                if run.mode == "live":
                    raise
                self._degrade(run, exc.code)
        run.status = "ranking"
        self.db.commit()
        ranked = sorted(scored.values(), key=lambda item: (-item["final"], item["job"].id))[: run.maximum_results]
        self._persist_results(run, ranked, candidate)
        run.status = "completed"
        run.completed_at = _utcnow()
        run.progress = {**run.progress, "results_ready": len(ranked)}
        self.db.commit()
        self.emit(run.id, "results.updated", {"count": len(ranked)})
        self.emit(run.id, "run.completed", {"count": len(ranked), "degraded_reasons": run.degraded_reasons})

    def get_run(self, current: ProductCurrentUser, run_id: str) -> JobSearchRun:
        run = self.db.get(JobSearchRun, run_id)
        if run is None or (current.role != "admin" and run.user_id != current.id):
            raise AppError(404, "JOB_SEARCH_RUN_NOT_FOUND", "Job search run was not found")
        return run

    def events_after(self, current: ProductCurrentUser, run_id: str, sequence: int) -> list[JobSearchEvent]:
        run = self.get_run(current, run_id)
        return list(self.db.scalars(select(JobSearchEvent).where(JobSearchEvent.run_id == run.id, JobSearchEvent.sequence > sequence).order_by(JobSearchEvent.sequence).limit(200)))

    def emit(self, run_id: str, event_type: str, payload: dict[str, Any]) -> JobSearchEvent:
        self.db.scalar(select(JobSearchRun).where(JobSearchRun.id == run_id).with_for_update())
        event = self._append_event(run_id, event_type, payload)
        self.db.commit()
        self.db.refresh(event)
        return event

    def _append_event(
        self,
        run_id: str,
        event_type: str,
        payload: dict[str, Any],
    ) -> JobSearchEvent:
        sequence = self.db.scalar(select(func.max(JobSearchEvent.sequence)).where(JobSearchEvent.run_id == run_id)) or 0
        event = JobSearchEvent(run_id=run_id, sequence=sequence + 1, event_type=event_type, payload=payload)
        self.db.add(event)
        return event

    def indexed_jobs(
        self,
        current: ProductCurrentUser,
        q: str | None,
        location: str | None,
        remote_mode: str | None,
        skills: list[str],
        salary_min_minor: int | None,
        salary_max_minor: int | None,
        salary_currency: str | None,
        salary_period: str | None,
        cursor: str | None,
        limit: int,
    ) -> JobPage:
        IdentityService(self.db).require_consent(current.id)
        if (salary_min_minor is not None or salary_max_minor is not None) and not salary_currency:
            raise AppError(422, "SALARY_CURRENCY_REQUIRED", "salary_currency is required for salary filters")
        if salary_min_minor is not None and salary_max_minor is not None and salary_min_minor > salary_max_minor:
            raise AppError(422, "INVALID_SALARY_RANGE", "salary_min_minor must not exceed salary_max_minor")
        filters = {
            "locations": [location] if location else [],
            "remote_modes": [remote_mode] if remote_mode else [],
            "skills": skills,
            "verified_only": True,
            "employment_types": [],
            "salary_min_minor": salary_min_minor,
            "salary_max_minor": salary_max_minor,
            "salary_currency": salary_currency.upper() if salary_currency else None,
            "salary_period": salary_period,
        }
        candidate_rows = self._hybrid_candidates(q or "IT", filters, None)
        jobs = [row["job"] for row in candidate_rows]
        if cursor:
            created_at, item_id = _parse_cursor(cursor)
            jobs = [job for job in jobs if (job.created_at, job.id) < (created_at, item_id)]
        has_more = len(jobs) > limit
        jobs = jobs[:limit]
        return JobPage(items=[self.job_view(job) for job in jobs], next_cursor=_cursor(jobs[-1].created_at, jobs[-1].id) if has_more and jobs else None)

    def get_job(self, job_id: str) -> ProductJob:
        job = self.db.get(ProductJob, job_id)
        if job is None:
            raise AppError(404, "JOB_NOT_FOUND", "Job was not found")
        return job

    def results(self, current: ProductCurrentUser, run_id: str, cursor: str | None, limit: int) -> JobMatchPage:
        run = self.get_run(current, run_id)
        statement = select(JobSearchResult).where(JobSearchResult.run_id == run.id)
        if cursor:
            try:
                rank = int(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)).decode())
            except (ValueError, UnicodeDecodeError) as exc:
                raise AppError(422, "INVALID_CURSOR", "Cursor is invalid") from exc
            statement = statement.where(JobSearchResult.rank > rank)
        records = list(self.db.scalars(statement.order_by(JobSearchResult.rank).limit(limit + 1)))
        has_more = len(records) > limit
        records = records[:limit]
        return JobMatchPage(
            items=[JobMatchView(job=self.job_view(self.db.get(ProductJob, item.job_id)), rank=item.rank, score=item.final_score, reasons=item.reasons or [], gaps=item.gaps or [], explanation_status=item.explanation_status) for item in records],
            next_cursor=base64.urlsafe_b64encode(str(records[-1].rank).encode()).decode().rstrip("=") if has_more and records else None,
        )

    def run_view(self, run: JobSearchRun) -> JobSearchRunView:
        return JobSearchRunView(
            id=run.id,
            status=run.status,
            mode=run.mode,
            query=run.query_text,
            progress=run.progress or {},
            degraded_reasons=run.degraded_reasons or [],
            provider=run.provider,
            provider_run_id=run.provider_run_id,
            provider_model=run.provider_model,
            provider_model_configuration_id=run.provider_model_configuration_id,
            provider_usage=run.provider_usage,
            provider_estimated_cost_minor=run.provider_estimated_cost_minor,
            events_url="/v1/job-search-runs/" + run.id + "/events",
            results_url="/v1/job-search-runs/" + run.id + "/results",
            created_at=run.created_at,
            completed_at=run.completed_at,
        )

    def job_view(self, job: ProductJob) -> JobView:
        records = list(self.db.scalars(select(JobSourceRecord).where(JobSourceRecord.job_id == job.id).order_by(JobSourceRecord.last_checked_at.desc())))
        sources = []
        for record in records:
            source = self.db.get(JobSource, record.source_id)
            sources.append(JobSourceReferenceView(source=source.display_name if source else "Unknown", source_job_id=record.source_job_id, url=record.source_url, last_checked_at=record.last_checked_at, verification_status=record.status))
        salary = None
        if job.salary_currency:
            salary = SalaryView(minimum_minor=job.salary_min_minor, maximum_minor=job.salary_max_minor, currency=job.salary_currency, period=job.salary_period or "unknown")
        return JobView(
            id=job.id,
            title=job.title,
            company_name=job.company_name,
            location=job.location_text,
            remote_mode=job.remote_mode,
            employment_type=job.employment_type,
            seniority=job.seniority,
            salary=salary,
            description=job.description_text,
            description_completeness=job.description_completeness,
            skills=job.skills or [],
            status=job.status,
            sources=sources,
            first_seen_at=job.first_seen_at,
            last_seen_at=job.last_seen_at,
            verified_at=job.verified_at,
        )

    def mark_stale_jobs(self) -> int:
        now = _utcnow()
        maintenance = JobCatalogMaintenanceRun(operation="mark_stale", status="running", started_at=now)
        self.db.add(maintenance)
        self.db.flush()
        records = list(self.db.scalars(select(ProductJob).where(ProductJob.status == "active", ProductJob.expires_at.is_not(None), ProductJob.expires_at < now)))
        maintenance.scanned_count = len(records)
        for job in records:
            job.status = "stale"
        maintenance.affected_count = len(records)
        maintenance.status = "completed"
        maintenance.completed_at = _utcnow()
        self.db.commit()
        return len(records)

    def _hybrid_candidates(self, query: str, filters: dict[str, Any], candidate: CandidateProfile | None) -> list[dict[str, Any]]:
        eligible_ids = self._eligible_job_ids(filters).subquery()
        base = select(ProductJob).join(eligible_ids, eligible_ids.c.id == ProductJob.id)
        dialect = self.db.bind.dialect.name if self.db.bind else "unknown"
        lexical_jobs: list[ProductJob]
        if dialect == "postgresql":
            tsquery = func.websearch_to_tsquery("simple", query)
            lexical_jobs = list(self.db.scalars(base.where(ProductJob.search_document.op("@@")(tsquery)).order_by(func.ts_rank_cd(ProductJob.search_document, tsquery).desc()).limit(100)))
        else:
            tokens = [token for token in re.split(r"\W+", query) if len(token) > 1]
            condition = or_(*[ProductJob.title.ilike("%" + token + "%") for token in tokens], *[ProductJob.description_text.ilike("%" + token + "%") for token in tokens]) if tokens else None
            lexical_jobs = list(self.db.scalars((base.where(condition) if condition is not None else base).limit(100)))
        vector_jobs: list[ProductJob] = []
        query_vector = None
        if candidate is not None and candidate.embedding is not None:
            query_vector = [float(value) for value in candidate.embedding]
            if len(query_vector) != 1536:
                query_vector = None
        if query_vector is None:
            try:
                query_vector = OpenAIJobsAdapter().embed([query])[0]
            except AppError:
                query_vector = None
        if dialect == "postgresql" and query_vector and len(query_vector) == 1536:
            vector_ids: list[str] = []
            rows = self.db.execute(
                select(JobEmbedding.job_id)
                .join(eligible_ids, eligible_ids.c.id == JobEmbedding.job_id)
                .order_by(JobEmbedding.embedding.cosine_distance(query_vector))
                .limit(300)
            ).scalars()
            for job_id in rows:
                if job_id not in vector_ids:
                    vector_ids.append(job_id)
                if len(vector_ids) == 100:
                    break
            if vector_ids:
                by_id = {
                    job.id: job
                    for job in self.db.scalars(
                        select(ProductJob).where(ProductJob.id.in_(vector_ids))
                    )
                }
                vector_jobs = [by_id[job_id] for job_id in vector_ids if job_id in by_id]
        lexical_rank = {job.id: index + 1 for index, job in enumerate(lexical_jobs)}
        vector_rank = {job.id: index + 1 for index, job in enumerate(vector_jobs)}
        jobs = {job.id: job for job in [*lexical_jobs, *vector_jobs]}
        rows = []
        for job in jobs.values():
            lexical = 1 / (60 + lexical_rank[job.id]) if job.id in lexical_rank else 0
            vector = 1 / (60 + vector_rank[job.id]) if job.id in vector_rank else 0
            rows.append(self._score(job, query, candidate, lexical, vector))
        return sorted(rows, key=lambda item: (-item["final"], item["job"].id))

    def _eligible_job_ids(self, filters: dict[str, Any]):
        base = select(ProductJob.id).where(ProductJob.status == "active")
        if filters.get("verified_only", True):
            base = base.where(ProductJob.verified_at.is_not(None), or_(ProductJob.expires_at.is_(None), ProductJob.expires_at > _utcnow()))
        locations = filters.get("locations") or []
        if locations:
            base = base.where(or_(*[ProductJob.location_text.ilike("%" + value + "%") for value in locations]))
        remote_modes = filters.get("remote_modes") or []
        if remote_modes:
            base = base.where(ProductJob.remote_mode.in_(remote_modes))
        employment = filters.get("employment_types") or []
        if employment:
            base = base.where(ProductJob.employment_type.in_(employment))
        salary_currency = filters.get("salary_currency")
        salary_period = filters.get("salary_period")
        salary_min = filters.get("salary_min_minor")
        salary_max = filters.get("salary_max_minor")
        if salary_currency:
            base = base.where(ProductJob.salary_currency == str(salary_currency).upper())
        if salary_period:
            base = base.where(ProductJob.salary_period == salary_period)
        if salary_min is not None:
            base = base.where(func.coalesce(ProductJob.salary_max_minor, ProductJob.salary_min_minor) >= int(salary_min))
        if salary_max is not None:
            base = base.where(func.coalesce(ProductJob.salary_min_minor, ProductJob.salary_max_minor) <= int(salary_max))
        dialect = self.db.bind.dialect.name if self.db.bind else "unknown"
        normalized_skills = self._normalize_skills(filters.get("skills") or [])
        for skill in normalized_skills:
            if dialect == "postgresql":
                base = base.where(
                    ProductJob.skills.op("@>")(
                        cast(literal(json.dumps([skill])), JSONB)
                    )
                )
            else:
                base = base.where(
                    func.lower(cast(ProductJob.skills, Text)).like(
                        '%"' + skill.replace("%", "") + '"%'
                    )
                )
        return base

    def _score(self, job: ProductJob, query: str, candidate: CandidateProfile | None, lexical: float, vector: float) -> dict[str, Any]:
        now = _utcnow()
        age_days = max(0.0, (now - job.last_seen_at).total_seconds() / 86400)
        freshness = math.exp(-age_days / 30)
        source_scores = self.db.scalars(select(JobSource.quality_score).join(JobSourceRecord, JobSourceRecord.source_id == JobSource.id).where(JobSourceRecord.job_id == job.id)).all()
        source_score = max(source_scores) if source_scores else 0.3
        query_tokens = set(re.findall(r"[a-z0-9+#.]+", query.lower()))
        job_tokens = set(re.findall(r"[a-z0-9+#.]+", (job.title + " " + " ".join(job.skills or [])).lower()))
        query_overlap = len(query_tokens & job_tokens) / max(len(query_tokens), 1)
        candidate_skills = set((candidate.profile_json.get("skills") or [])) if candidate else set()
        skill_overlap = len({value.lower() for value in (job.skills or [])} & {value.lower() for value in candidate_skills}) / max(len(job.skills or []), 1)
        rerank = 0.6 * query_overlap + 0.4 * skill_overlap
        rrf_scaled = min(1.0, 30 * (lexical + vector))
        final = max(0.0, min(1.0, 0.35 * rrf_scaled + 0.30 * rerank + 0.20 * freshness + 0.15 * source_score))
        reasons = ["Role/query alignment: " + format(query_overlap, ".2f"), "Freshness: " + format(freshness, ".2f")]
        gaps = []
        if candidate:
            missing = [skill for skill in (job.skills or []) if skill.lower() not in {value.lower() for value in candidate_skills}]
            gaps = ["Missing explicit CV evidence: " + skill for skill in missing[:5]]
        return {"job": job, "lexical": lexical, "vector": vector, "freshness": freshness, "source": source_score, "rerank": rerank, "final": final, "reasons": reasons, "gaps": gaps}

    def _verify_and_upsert(self, item: dict[str, Any], provider: dict[str, Any]) -> ProductJob:
        page = SafeJobFetcher().fetch(item["source_url"])
        parsed = urlparse(page.final_url)
        domain = parsed.hostname.lower() if parsed.hostname else "unknown"
        source = self.db.scalar(select(JobSource).where(JobSource.base_domain == domain))
        if source is None:
            source = JobSource(key="web-" + hashlib.sha256(domain.encode()).hexdigest()[:16], display_name=domain, source_type="web_search", base_domain=domain, access_policy={"discovery": "openai_citation", "fetch": "public_only"}, quality_score=0.5)
            self.db.add(source)
            self.db.flush()
        fingerprint = self._fingerprint(item)
        job = self.db.scalar(select(ProductJob).where(ProductJob.canonical_fingerprint == fingerprint))
        now = _utcnow()
        description = page.description or item.get("description")
        if job is None:
            job = ProductJob(canonical_fingerprint=fingerprint, title=item["title"][:500], company_name=item["company_name"][:500], first_seen_at=now, normalization_version="job-v1")
            self.db.add(job)
            self.db.flush()
        job.title = item["title"][:500]
        job.company_name = item["company_name"][:500]
        job.location_text = item.get("location")
        job.remote_mode = item.get("remote_mode") or "unknown"
        job.employment_type = item.get("employment_type")
        job.seniority = item.get("seniority")
        job.salary_min_minor = self._minor_value(item.get("salary_min_minor"))
        job.salary_max_minor = self._minor_value(item.get("salary_max_minor"))
        currency = str(item.get("salary_currency") or "").upper()
        job.salary_currency = currency if len(currency) == 3 else None
        job.salary_period = str(item.get("salary_period") or "")[:20] or None
        job.description_text = description
        job.description_completeness = "full" if page.description and len(page.description) > 1000 else ("partial" if description else "unavailable")
        job.skills = self._normalize_skills(item.get("skills", []))
        job.status = "active" if page.outcome == "verified" else "invalid"
        job.last_seen_at = now
        job.verified_at = now if page.outcome == "verified" else None
        job.expires_at = now + timedelta(days=1)
        normalized_url = page.final_url.rstrip("/")
        url_hash = hashlib.sha256(normalized_url.encode()).hexdigest()
        record = self.db.scalar(select(JobSourceRecord).where(JobSourceRecord.source_id == source.id, JobSourceRecord.url_fingerprint == url_hash))
        if record is None:
            record = JobSourceRecord(job_id=job.id, source_id=source.id, source_job_id=item.get("source_job_id"), source_url=normalized_url, url_fingerprint=url_hash, first_seen_at=now)
            self.db.add(record)
            self.db.flush()
        record.job_id = job.id
        record.status = "verified" if page.outcome == "verified" else "unavailable"
        record.last_seen_at = now
        record.last_checked_at = now
        record.http_status = page.http_status
        record.fetch_outcome = page.outcome
        record.metadata_json = {"citation_title": item.get("citation_title"), "posted_at": item.get("posted_at"), "provider_run_id": provider.get("provider_run_id")}
        payload = {key: value for key, value in item.items() if key != "citation_title"}
        payload.update({"final_url": normalized_url, "verification": page.outcome})
        content_hash = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        snapshot = self.db.scalar(select(JobSnapshot).where(JobSnapshot.source_record_id == record.id, JobSnapshot.content_hash == content_hash))
        if snapshot is None:
            raw_payload = {
                "provider_item": item,
                "provider_evidence": provider,
                "fetch": {
                    "final_url": page.final_url,
                    "http_status": page.http_status,
                    "outcome": page.outcome,
                    "title": page.title,
                    "text": page.content_hash_input,
                },
            }
            raw_bytes = json.dumps(raw_payload, ensure_ascii=False).encode("utf-8")
            raw_object_key = "job-snapshots/" + content_hash + ".json"
            ObjectStorage().put_system(raw_object_key, raw_bytes, "application/json")
            snapshot = JobSnapshot(
                job_id=job.id,
                source_record_id=record.id,
                content_hash=content_hash,
                normalized_payload=payload,
                raw_object_key=raw_object_key,
                raw_content_type="application/json",
                parser_version="job-web-v1",
            )
            self.db.add(snapshot)
            self.db.flush()
        source.last_healthy_at = now if page.outcome == "verified" else source.last_healthy_at
        self.db.commit()
        self._ensure_embedding(job, snapshot)
        return job

    def _ensure_embedding(self, job: ProductJob, snapshot: JobSnapshot) -> None:
        existing = self.db.scalar(select(JobEmbedding).where(JobEmbedding.job_snapshot_id == snapshot.id, JobEmbedding.model == OpenAIJobsAdapter().embedding_model))
        if existing is not None:
            return
        text = " ".join([job.title, job.company_name, job.location_text or "", " ".join(job.skills or []), job.description_text or ""])
        try:
            vector = OpenAIJobsAdapter().embed([text])[0]
        except AppError:
            return
        self.db.add(JobEmbedding(job_id=job.id, job_snapshot_id=snapshot.id, model=OpenAIJobsAdapter().embedding_model, model_version="1", dimensions=len(vector), embedding=vector, content_hash=snapshot.content_hash))
        self.db.commit()

    def _candidate_profile(self, run: JobSearchRun) -> CandidateProfile | None:
        if not run.cv_version_id:
            return None
        version = self.db.get(ProductCvVersion, run.cv_version_id)
        if version is None:
            return None
        product_profile = self.db.scalar(select(UserProductProfile).where(UserProductProfile.user_id == run.user_id))
        preference_version = product_profile.preference_version if product_profile else 1
        existing = self.db.scalar(select(CandidateProfile).where(CandidateProfile.user_id == run.user_id, CandidateProfile.cv_version_id == version.id, CandidateProfile.preference_version == preference_version, CandidateProfile.status == "fresh").order_by(CandidateProfile.version.desc()))
        if existing:
            run.candidate_profile_id = existing.id
            self.db.commit()
            return existing
        reports = list(self.db.scalars(select(ProductInterviewReport).join(ProductInterview, ProductInterview.id == ProductInterviewReport.interview_id).where(ProductInterview.user_id == run.user_id, ProductInterview.cv_version_id == version.id, ProductInterviewReport.status == "ready")))
        content = version.content or {}
        skills = [item.get("name") for item in content.get("skills", []) if item.get("name")]
        basics = content.get("basics", {})
        profile_json = {"skills": skills, "summary": basics.get("summary"), "target_roles": (product_profile.job_preferences or {}).get("roles", []) if product_profile else [], "interview_scores": [report.scores for report in reports]}
        text = " ".join([basics.get("summary") or "", " ".join(skills), " ".join(profile_json["target_roles"])])
        try:
            embedding = OpenAIJobsAdapter().embed([text])[0]
        except AppError:
            embedding = None
        next_version = (self.db.scalar(select(func.max(CandidateProfile.version)).where(CandidateProfile.user_id == run.user_id)) or 0) + 1
        candidate = CandidateProfile(user_id=run.user_id, version=next_version, cv_version_id=version.id, preference_version=preference_version, preference_snapshot=product_profile.job_preferences if product_profile else {}, interview_report_ids=[report.id for report in reports], profile_json=profile_json, embedding=embedding, embedding_model=OpenAIJobsAdapter().embedding_model if embedding else None, generation_version="candidate-v1", status="fresh")
        self.db.add(candidate)
        self.db.flush()
        run.candidate_profile_id = candidate.id
        self.db.commit()
        return candidate

    def _persist_results(self, run: JobSearchRun, ranked: list[dict[str, Any]], candidate: CandidateProfile | None) -> None:
        self.db.query(JobSearchResult).filter(JobSearchResult.run_id == run.id).delete()
        for index, row in enumerate(ranked, 1):
            job = row["job"]
            snapshot = self.db.scalar(select(JobSnapshot).where(JobSnapshot.job_id == job.id).order_by(JobSnapshot.captured_at.desc()))
            result = JobSearchResult(run_id=run.id, job_id=job.id, job_snapshot_id=snapshot.id if snapshot else None, rank=index, lexical_score=row["lexical"], vector_score=row["vector"], freshness_score=row["freshness"], source_score=row["source"], rerank_score=row["rerank"], final_score=row["final"], reasons=row["reasons"], gaps=row["gaps"], explanation_status="processing" if index <= 3 else "not_requested", result_snapshot=self.job_view(job).model_dump(mode="json"))
            self.db.add(result)
            self.db.flush()
            if index <= 3:
                try:
                    explanation, provider = OpenAIJobsAdapter().explain(candidate.profile_json if candidate else {"query": run.query_text}, result.result_snapshot)
                    ProviderUsageService(self.db).success(
                        user_id=run.user_id,
                        provider="openai",
                        purpose="job_explanation",
                        resource_type="job_search_result",
                        resource_id=result.id,
                        metadata=provider,
                    )
                    result.explanation = explanation
                    result.reasons = explanation.get("reasons", result.reasons)
                    result.gaps = explanation.get("gaps", result.gaps)
                    result.explanation_status = "ready"
                    result.explanation_provider = "openai"
                    result.explanation_model = provider.get("model")
                    result.explanation_model_configuration_id = provider.get("model_configuration_id")
                    result.explanation_prompt_version = provider.get("prompt_version")
                    result.explanation_provider_run_id = provider.get("provider_run_id")
                    result.explanation_usage = provider.get("usage", {})
                    result.explanation_estimated_cost_minor = provider.get("estimated_cost_minor")
                except AppError as exc:
                    ProviderUsageService(self.db).failure(
                        user_id=run.user_id,
                        provider="openai",
                        purpose="job_explanation",
                        resource_type="job_search_result",
                        resource_id=result.id,
                        error=exc,
                    )
                    result.explanation_status = "failed"
                    self._degrade(run, "EXPLANATION_FAILED")
        self.db.commit()

    def _degrade(self, run: JobSearchRun, reason: str) -> None:
        reasons = list(run.degraded_reasons or [])
        if reason not in reasons:
            reasons.append(reason)
            run.degraded_reasons = reasons
            self.db.commit()

    def _job_matches_filters(self, job: ProductJob, filters: dict[str, Any]) -> bool:
        if filters.get("verified_only", True):
            if job.verified_at is None or (job.expires_at is not None and job.expires_at <= _utcnow()):
                return False
        if filters.get("locations") and not any(
            value.lower() in (job.location_text or "").lower() for value in filters["locations"]
        ):
            return False
        if filters.get("remote_modes") and job.remote_mode not in filters["remote_modes"]:
            return False
        if filters.get("employment_types") and job.employment_type not in filters["employment_types"]:
            return False
        expected_skills = set(self._normalize_skills(filters.get("skills") or []))
        if expected_skills and not expected_skills.issubset(set(self._normalize_skills(job.skills or []))):
            return False
        currency = filters.get("salary_currency")
        if currency and job.salary_currency != str(currency).upper():
            return False
        if filters.get("salary_period") and job.salary_period != filters["salary_period"]:
            return False
        lower = filters.get("salary_min_minor")
        upper = filters.get("salary_max_minor")
        job_upper = job.salary_max_minor if job.salary_max_minor is not None else job.salary_min_minor
        job_lower = job.salary_min_minor if job.salary_min_minor is not None else job.salary_max_minor
        if lower is not None and (job_upper is None or job_upper < int(lower)):
            return False
        if upper is not None and (job_lower is None or job_lower > int(upper)):
            return False
        return True

    @staticmethod
    def _minor_value(value: Any) -> int | None:
        if value is None:
            return None
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return None
        return parsed if parsed >= 0 else None

    @staticmethod
    def _fingerprint(item: dict[str, Any]) -> str:
        normalized = "|".join([str(item.get("title") or "").lower().strip(), str(item.get("company_name") or "").lower().strip(), str(item.get("location") or "").lower().strip()])
        return hashlib.sha256(normalized.encode()).hexdigest()

    @staticmethod
    def _normalize_skills(values: list[Any]) -> list[str]:
        normalized = {
            " ".join(str(value).strip().casefold().split())
            for value in values
            if str(value).strip()
        }
        return sorted(normalized)
