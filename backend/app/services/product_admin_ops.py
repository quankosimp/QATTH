from __future__ import annotations

import base64
import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Any

import redis
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.core.celery_app import celery_app
from app.core.config import get_settings
from app.core.errors import AppError
from app.core.identity_security import ProductCurrentUser
from app.models.db import AuthToken, User
from app.models.identity import AccountStatusEvent, UserProductProfile, UserSession
from app.models.product_cv import CvAnalysis, CvScan, ProductCV
from app.models.product_interview import ProductInterview, ProductInterviewReport
from app.models.product_admin_ops import AuditChainHead, ModelConfiguration, ModelEvaluationReport, OperationalJob, OperationalJobDispatch, PrivilegedAuditEvent, PrivilegedCommand
from app.models.product_jobs import JobSearchRun, JobSource, JobSourceRecord, ProductJob
from app.models.product_privacy import PrivacyRequest
from app.models.product_recommendations import JobApplication, JobModerationCase, RecommendationRun
from app.models.provider_ops import ProviderUsageEvent
from app.schemas.product_admin_ops import (
    AdminUserSummary,
    AdminResourceSummary,
    AccountStatusView,
    BackgroundJobPage,
    BackgroundJobView,
    CreateModelEvaluationReportRequest,
    CreateModelConfigurationRequest,
    JobSourceAdminView,
    ModelConfigurationView,
    ModelEvaluationReportView,
    ModerationCaseView,
    OpsDiagnosticsView,
    ProviderUsageSummaryView,
    ResolveModerationCaseRequest,
    RetryBackgroundJobRequest,
    UpdateJobSourceRequest,
    UpdateAccountStatusRequest,
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ProductAdminOpsService:
    purpose_providers = {
        "cv_extraction": "openai",
        "cv_analysis": "openai",
        "interview_evaluation": "openai",
        "interview_live": "gemini",
        "job_search": "openai",
        "job_embedding": "openai",
        "job_explanation": "openai",
    }
    retryable_tasks = {
        "product.cv.extract",
        "product.cv.analyze",
        "product.interview.evaluate",
        "product.jobs.search",
        "product.recommendations.generate",
        "product.privacy.execute",
    }

    def __init__(self, db: Session) -> None:
        self.db = db

    def list_model_configurations(self, current: ProductCurrentUser, context: dict[str, Any]) -> list[ModelConfigurationView]:
        records = list(self.db.scalars(select(ModelConfiguration).order_by(ModelConfiguration.purpose, ModelConfiguration.created_at.desc())))
        self._audit(current, "model_configuration.list", "model_configuration", None, None, context, {"result_count": len(records)})
        self.db.commit()
        return [self.model_view(item) for item in records]

    def create_model_configuration(self, current: ProductCurrentUser, payload: CreateModelConfigurationRequest, idempotency_key: str, context: dict[str, Any]) -> ModelConfiguration:
        expected_provider = self.purpose_providers.get(payload.purpose)
        if expected_provider is None:
            raise AppError(422, "MODEL_CONFIGURATION_PURPOSE_UNSUPPORTED", "Model configuration purpose is not supported by the runtime")
        if payload.provider != expected_provider:
            raise AppError(422, "MODEL_CONFIGURATION_PROVIDER_MISMATCH", "Provider does not match the implemented adapter for this purpose", details={"expected_provider": expected_provider})
        request_hash = self._hash(payload.model_dump(mode="json"))
        existing = self.db.scalar(select(ModelConfiguration).where(ModelConfiguration.created_by_user_id == current.id, ModelConfiguration.idempotency_key == idempotency_key))
        if existing is not None:
            if existing.request_hash != request_hash:
                raise AppError(409, "IDEMPOTENCY_KEY_REUSED", "Idempotency-Key was already used with a different request")
            return existing
        record = ModelConfiguration(purpose=payload.purpose, version=payload.version, provider=payload.provider, model=payload.model, configuration=payload.configuration, output_schema_version=payload.output_schema_version, idempotency_key=idempotency_key, request_hash=request_hash, created_by_user_id=current.id)
        self.db.add(record)
        self.db.flush()
        self._audit(current, "model_configuration.create", "model_configuration", record.id, None, context, {"purpose": record.purpose, "version": record.version})
        self.db.commit()
        self.db.refresh(record)
        return record

    def list_model_evaluation_reports(
        self,
        current: ProductCurrentUser,
        configuration_id: str,
        context: dict[str, Any],
    ) -> list[ModelEvaluationReportView]:
        configuration = self.db.get(ModelConfiguration, configuration_id)
        if configuration is None:
            raise AppError(404, "MODEL_CONFIGURATION_NOT_FOUND", "Model configuration was not found")
        records = list(
            self.db.scalars(
                select(ModelEvaluationReport)
                .where(ModelEvaluationReport.model_configuration_id == configuration.id)
                .order_by(ModelEvaluationReport.created_at.desc())
            )
        )
        self._audit(
            current,
            "model_evaluation_report.list",
            "model_configuration",
            configuration.id,
            None,
            context,
            {"result_count": len(records)},
        )
        self.db.commit()
        return [self.evaluation_report_view(item) for item in records]

    def create_model_evaluation_report(
        self,
        current: ProductCurrentUser,
        configuration_id: str,
        payload: CreateModelEvaluationReportRequest,
        idempotency_key: str,
        context: dict[str, Any],
    ) -> ModelEvaluationReport:
        configuration = self.db.get(ModelConfiguration, configuration_id)
        if configuration is None:
            raise AppError(404, "MODEL_CONFIGURATION_NOT_FOUND", "Model configuration was not found")
        request_hash = self._hash(payload.model_dump(mode="json"))
        existing = self.db.scalar(
            select(ModelEvaluationReport).where(
                ModelEvaluationReport.created_by_user_id == current.id,
                ModelEvaluationReport.idempotency_key == idempotency_key,
            )
        )
        if existing is not None:
            if existing.request_hash != request_hash or existing.model_configuration_id != configuration.id:
                raise AppError(409, "IDEMPOTENCY_KEY_REUSED", "Idempotency-Key was already used with a different request")
            return existing
        settings = get_settings()
        if payload.sample_count < settings.ai_eval_min_sample_count:
            raise AppError(
                422,
                "AI_EVAL_SAMPLE_TOO_SMALL",
                "Evaluation sample count is below the configured quality gate",
                details={"minimum_sample_count": settings.ai_eval_min_sample_count},
            )
        from app.services.model_quality import QUALITY_POLICY_VERSION, evaluate_model_metrics

        report_status, metrics, criteria = evaluate_model_metrics(configuration.purpose, payload.metrics)
        report = ModelEvaluationReport(
            model_configuration_id=configuration.id,
            dataset_key=payload.dataset_key,
            dataset_version=payload.dataset_version,
            dataset_sha256=payload.dataset_sha256.lower(),
            quality_policy_version=QUALITY_POLICY_VERSION,
            evaluator_version=payload.evaluator_version,
            sample_count=payload.sample_count,
            metrics=metrics,
            criteria=criteria,
            status=report_status,
            external_report_id=payload.external_report_id,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            created_by_user_id=current.id,
        )
        self.db.add(report)
        self.db.flush()
        self._audit(
            current,
            "model_evaluation_report.create",
            "model_evaluation_report",
            report.id,
            None,
            context,
            {
                "model_configuration_id": configuration.id,
                "dataset_key": report.dataset_key,
                "dataset_version": report.dataset_version,
                "status": report.status,
            },
        )
        self.db.commit()
        self.db.refresh(report)
        return report

    def activate_model_configuration(self, current: ProductCurrentUser, configuration_id: str, payload, idempotency_key: str, context: dict[str, Any]) -> ModelConfiguration:
        command, replay = self._command(current, "activate_model_configuration:" + configuration_id, idempotency_key, payload.model_dump(mode="json"))
        if replay:
            return self.db.get(ModelConfiguration, command.resource_id)
        record = self.db.scalar(select(ModelConfiguration).where(ModelConfiguration.id == configuration_id).with_for_update())
        if record is None:
            raise AppError(404, "MODEL_CONFIGURATION_NOT_FOUND", "Model configuration was not found")
        report = self.db.get(ModelEvaluationReport, payload.evaluation_report_id)
        if report is None or report.model_configuration_id != record.id:
            raise AppError(422, "AI_EVAL_REPORT_INVALID", "Evaluation report does not belong to this model configuration")
        if report.status != "passed":
            raise AppError(409, "AI_EVAL_GATE_FAILED", "Model configuration did not pass its quality gate")
        now = _utcnow()
        deployed = list(
            self.db.scalars(
                select(ModelConfiguration)
                .where(
                    ModelConfiguration.purpose == record.purpose,
                    ModelConfiguration.status.in_(["active", "canary"]),
                )
                .with_for_update()
            )
        )
        if payload.rollout_percentage < 100:
            baseline = next((item for item in deployed if item.status == "active" and item.id != record.id), None)
            if baseline is None:
                raise AppError(409, "MODEL_CANARY_BASELINE_REQUIRED", "A canary rollout requires an active baseline")
            for item in deployed:
                if item.status == "canary" and item.id != record.id:
                    item.status = "retired"
                    item.rollout_percentage = 0
                    item.retired_at = now
            record.status = "canary"
        else:
            for item in deployed:
                if item.id != record.id:
                    item.status = "retired"
                    item.rollout_percentage = 0
                    item.retired_at = now
            record.status = "active"
        record.activated_by_user_id = current.id
        record.evaluation_report_id = report.id
        record.rollout_percentage = payload.rollout_percentage
        record.activation_reason = payload.reason
        record.activated_at = now
        record.retired_at = None
        self._complete_command(command, "model_configuration", record.id, {"id": record.id})
        self._audit(current, "model_configuration.activate", "model_configuration", record.id, payload.reason, context, {"purpose": record.purpose, "version": record.version, "evaluation_report_id": report.id, "rollout_percentage": record.rollout_percentage})
        self.db.commit()
        self.db.refresh(record)
        return record

    @staticmethod
    def model_view(record: ModelConfiguration) -> ModelConfigurationView:
        return ModelConfigurationView(id=record.id, purpose=record.purpose, version=record.version, status=record.status, provider=record.provider, model=record.model, output_schema_version=record.output_schema_version, evaluation_report_id=record.evaluation_report_id, rollout_percentage=record.rollout_percentage, activated_at=record.activated_at, created_at=record.created_at)

    @staticmethod
    def evaluation_report_view(record: ModelEvaluationReport) -> ModelEvaluationReportView:
        return ModelEvaluationReportView(id=record.id, model_configuration_id=record.model_configuration_id, dataset_key=record.dataset_key, dataset_version=record.dataset_version, dataset_sha256=record.dataset_sha256, quality_policy_version=record.quality_policy_version, evaluator_version=record.evaluator_version, sample_count=record.sample_count, metrics=record.metrics, criteria=record.criteria, status=record.status, external_report_id=record.external_report_id, created_at=record.created_at)

    def job_sources(self, current: ProductCurrentUser, context: dict[str, Any], source_status: str | None = None, key: str | None = None, period_start: datetime | None = None, period_end: datetime | None = None) -> list[JobSourceAdminView]:
        start, end = self._period(period_start, period_end, 90)
        source_query = select(JobSource)
        if source_status:
            source_query = source_query.where(JobSource.status == source_status)
        if key:
            source_query = source_query.where(JobSource.key == key)
        sources = list(self.db.scalars(source_query.order_by(JobSource.key)))
        output = []
        for source in sources:
            record_filter = [JobSourceRecord.source_id == source.id, JobSourceRecord.last_checked_at >= start, JobSourceRecord.last_checked_at < end]
            total = self.db.scalar(select(func.count()).select_from(JobSourceRecord).where(*record_filter)) or 0
            stale = self.db.scalar(select(func.count()).select_from(JobSourceRecord).where(*record_filter, JobSourceRecord.status.in_(["stale", "unavailable"]))) or 0
            output.append(JobSourceAdminView(id=source.id, key=source.key, name=source.display_name, status=source.status, quality_score=source.quality_score, last_healthy_at=source.last_healthy_at, stale_rate=stale / total if total else None))
        self._audit(current, "job_source.list", "job_source", None, None, context, {"result_count": len(output), "status": source_status, "key": key, "period_start": start.isoformat(), "period_end": end.isoformat()})
        self.db.commit()
        return output

    def update_job_source(self, current: ProductCurrentUser, source_id: str, payload: UpdateJobSourceRequest, idempotency_key: str, context: dict[str, Any]) -> JobSource:
        command, replay = self._command(current, "update_job_source:" + source_id, idempotency_key, payload.model_dump(mode="json"))
        if replay:
            return self.db.get(JobSource, command.resource_id)
        source = self.db.scalar(select(JobSource).where(JobSource.id == source_id).with_for_update())
        if source is None:
            raise AppError(404, "JOB_SOURCE_NOT_FOUND", "Job source was not found")
        before = {"status": source.status, "quality_score": source.quality_score}
        if payload.status is not None:
            source.status = payload.status
        if payload.quality_score is not None:
            source.quality_score = payload.quality_score
        self._complete_command(command, "job_source", source.id, {"id": source.id})
        self._audit(current, "job_source.update", "job_source", source.id, payload.reason, context, {"before": before, "after": {"status": source.status, "quality_score": source.quality_score}})
        self.db.commit()
        self.db.refresh(source)
        return source

    def search_users(self, current: ProductCurrentUser, query: str, context: dict[str, Any]) -> list[AdminUserSummary]:
        normalized = query.strip().lower()
        statement = select(User, UserProductProfile).outerjoin(UserProductProfile, UserProductProfile.user_id == User.id)
        if len(normalized) == 36:
            statement = statement.where((User.id == normalized) | (func.lower(User.email) == normalized))
        else:
            statement = statement.where(func.lower(User.email) == normalized)
        rows = list(self.db.execute(statement.limit(20)))
        can_view_pii = "local:all" in current.scopes or "admin:users:pii" in current.scopes
        output = [AdminUserSummary(id=user.id, email=user.email if can_view_pii else self._mask_email(user.email), role=user.role, account_status=profile.account_status if profile else ("active" if user.is_active else "disabled"), created_at=user.created_at) for user, profile in rows]
        self._audit(current, "user.search", "user", None, None, context, {"query_hash": hashlib.sha256(normalized.encode()).hexdigest(), "result_count": len(output), "pii_unmasked": can_view_pii})
        self.db.commit()
        return output

    def resource(self, current: ProductCurrentUser, resource_type: str, resource_id: str, context: dict[str, Any]) -> AdminResourceSummary:
        models = {
            "cv": ProductCV,
            "cv_scan": CvScan,
            "cv_analysis": CvAnalysis,
            "interview": ProductInterview,
            "interview_report": ProductInterviewReport,
            "job": ProductJob,
            "job_search_run": JobSearchRun,
            "recommendation_run": RecommendationRun,
            "job_application": JobApplication,
            "privacy_request": PrivacyRequest,
            "provider_usage": ProviderUsageEvent,
        }
        model = models.get(resource_type)
        if model is None:
            raise AppError(422, "UNSUPPORTED_RESOURCE_TYPE", "Resource type is not searchable")
        record = self.db.get(model, resource_id)
        if record is None:
            raise AppError(404, "RESOURCE_NOT_FOUND", "Resource was not found")
        metadata: dict[str, Any] = {}
        if isinstance(record, ProductJob):
            metadata = {"title": record.title, "company_name": record.company_name}
        elif isinstance(record, ProviderUsageEvent):
            metadata = {"provider": record.provider, "purpose": record.purpose, "error_code": record.error_code}
        elif isinstance(record, ProductInterview):
            metadata = {"target_role": record.target_role, "interview_type": record.interview_type}
        summary = AdminResourceSummary(
            resource_type=resource_type,
            id=record.id,
            owner_user_id=getattr(record, "user_id", None),
            status=getattr(record, "status", None),
            created_at=getattr(record, "created_at", getattr(record, "occurred_at", None)),
            metadata=metadata,
        )
        self._audit(current, "resource.read", resource_type, record.id, None, context, {"owner_user_id": summary.owner_user_id})
        self.db.commit()
        return summary

    def update_account_status(
        self,
        current: ProductCurrentUser,
        user_id: str,
        payload: UpdateAccountStatusRequest,
        idempotency_key: str,
        context: dict[str, Any],
    ) -> AccountStatusView:
        command, replay = self._command(
            current,
            "update_account_status:" + user_id,
            idempotency_key,
            payload.model_dump(mode="json"),
        )
        if replay:
            return AccountStatusView.model_validate(command.response_snapshot)
        if user_id == current.id and payload.status != "active":
            raise AppError(409, "ADMIN_SELF_LOCK_FORBIDDEN", "Administrators cannot lock or disable their own account")
        user = self.db.scalar(select(User).where(User.id == user_id).with_for_update())
        if user is None:
            raise AppError(404, "USER_NOT_FOUND", "User was not found")
        profile = self.db.scalar(
            select(UserProductProfile)
            .where(UserProductProfile.user_id == user.id)
            .with_for_update()
        )
        if profile is None:
            profile = UserProductProfile(user_id=user.id, account_status="active")
            self.db.add(profile)
            self.db.flush()
        previous_status = profile.account_status
        now = _utcnow()
        profile.account_status = payload.status
        profile.updated_at = now
        user.is_active = payload.status != "disabled"
        sessions_revoked = 0
        tokens_revoked = 0
        if payload.status != "active":
            session_result = self.db.execute(
                update(UserSession)
                .where(UserSession.user_id == user.id, UserSession.revoked_at.is_(None))
                .values(revoked_at=now)
            )
            token_result = self.db.execute(
                update(AuthToken)
                .where(AuthToken.user_id == user.id, AuthToken.revoked_at.is_(None))
                .values(revoked_at=now)
            )
            sessions_revoked = int(session_result.rowcount or 0)
            tokens_revoked = int(token_result.rowcount or 0)
        event = AccountStatusEvent(
            user_id=user.id,
            previous_status=previous_status,
            new_status=payload.status,
            reason=payload.reason,
            actor_id=current.id,
            created_at=now,
        )
        self.db.add(event)
        self.db.flush()
        response = AccountStatusView(
            event_id=event.id,
            user_id=user.id,
            previous_status=previous_status,
            new_status=payload.status,
            reason=payload.reason,
            effective_at=now,
            sessions_revoked=sessions_revoked,
            tokens_revoked=tokens_revoked,
        )
        response_snapshot = response.model_dump(mode="json")
        self._complete_command(command, "account_status_event", event.id, response_snapshot)
        self._audit(
            current,
            "user.account_status.update",
            "user",
            user.id,
            payload.reason,
            context,
            {
                "previous_status": previous_status,
                "new_status": payload.status,
                "sessions_revoked": sessions_revoked,
                "tokens_revoked": tokens_revoked,
            },
        )
        self.db.commit()
        return response

    def moderation_cases(self, current: ProductCurrentUser, case_status: str | None, source_id: str | None, period_start: datetime | None, period_end: datetime | None, context: dict[str, Any]) -> list[ModerationCaseView]:
        start, end = self._period(period_start, period_end, 90)
        statement = select(JobModerationCase)
        if case_status:
            statement = statement.where(JobModerationCase.status == case_status)
        statement = statement.where(JobModerationCase.created_at >= start, JobModerationCase.created_at < end)
        if source_id:
            statement = statement.join(JobSourceRecord, JobSourceRecord.job_id == JobModerationCase.job_id).where(JobSourceRecord.source_id == source_id).distinct()
        records = list(self.db.scalars(statement.order_by(JobModerationCase.created_at.desc()).limit(200)))
        self._audit(current, "moderation_case.list", "moderation_case", None, None, context, {"status": case_status, "source_id": source_id, "period_start": start.isoformat(), "period_end": end.isoformat(), "result_count": len(records)})
        self.db.commit()
        return [self.moderation_view(item) for item in records]

    def resolve_moderation_case(self, current: ProductCurrentUser, case_id: str, payload: ResolveModerationCaseRequest, idempotency_key: str, context: dict[str, Any]) -> JobModerationCase:
        command, replay = self._command(current, "resolve_moderation_case:" + case_id, idempotency_key, payload.model_dump(mode="json"))
        if replay:
            return self.db.get(JobModerationCase, command.resource_id)
        case_record = self.db.scalar(select(JobModerationCase).where(JobModerationCase.id == case_id).with_for_update())
        if case_record is None:
            raise AppError(404, "MODERATION_CASE_NOT_FOUND", "Moderation case was not found")
        if case_record.status != "open":
            raise AppError(409, "MODERATION_CASE_CLOSED", "Moderation case is already closed")
        job = self.db.get(ProductJob, case_record.job_id)
        if payload.action == "invalidate_job" and job is not None:
            job.status = "unavailable"
        if payload.action == "disable_source" and job is not None:
            source_ids = list(self.db.scalars(select(JobSourceRecord.source_id).where(JobSourceRecord.job_id == job.id)))
            for source in self.db.scalars(select(JobSource).where(JobSource.id.in_(source_ids)).with_for_update()):
                source.status = "disabled"
        case_record.status = "resolved" if payload.action != "dismiss" else "dismissed"
        case_record.assigned_to_user_id = current.id
        case_record.resolution = {"action": payload.action, "reason": payload.reason}
        case_record.resolved_at = _utcnow()
        self._complete_command(command, "moderation_case", case_record.id, {"id": case_record.id})
        self._audit(current, "moderation_case.resolve", "moderation_case", case_record.id, payload.reason, context, {"action": payload.action, "job_id": case_record.job_id})
        self.db.commit()
        self.db.refresh(case_record)
        return case_record

    @staticmethod
    def moderation_view(item: JobModerationCase) -> ModerationCaseView:
        return ModerationCaseView(id=item.id, job_id=item.job_id, reporter_user_id=item.reporter_user_id, reason_code=item.reason_code, details=item.details, status=item.status, assigned_to_user_id=item.assigned_to_user_id, resolution=item.resolution, created_at=item.created_at, updated_at=item.updated_at)

    def background_jobs(self, current: ProductCurrentUser, context: dict[str, Any], job_status: str | None, cursor: str | None, limit: int) -> BackgroundJobPage:
        statement = select(OperationalJob)
        if job_status:
            statement = statement.where(OperationalJob.status == job_status)
        if cursor:
            created_at, item_id = self._decode_cursor(cursor)
            statement = statement.where((OperationalJob.created_at < created_at) | ((OperationalJob.created_at == created_at) & (OperationalJob.id < item_id)))
        records = list(self.db.scalars(statement.order_by(OperationalJob.created_at.desc(), OperationalJob.id.desc()).limit(limit + 1)))
        has_more = len(records) > limit
        records = records[:limit]
        self._audit(current, "background_job.list", "background_job", None, None, context, {"status": job_status, "result_count": len(records)})
        self.db.commit()
        return BackgroundJobPage(items=[self.job_view(item) for item in records], next_cursor=self._encode_cursor(records[-1].created_at, records[-1].id) if has_more and records else None)

    def retry_job(self, current: ProductCurrentUser, job_id: str, payload: RetryBackgroundJobRequest, idempotency_key: str, context: dict[str, Any]) -> OperationalJob:
        command, replay = self._command(current, "retry_background_job:" + job_id, idempotency_key, payload.model_dump(mode="json"))
        if replay:
            return self.db.get(OperationalJob, command.resource_id)
        job = self.db.scalar(select(OperationalJob).where(OperationalJob.id == job_id).with_for_update())
        if job is None:
            raise AppError(404, "BACKGROUND_JOB_NOT_FOUND", "Background job was not found")
        if job.status not in {"failed", "dead_letter"}:
            raise AppError(409, "BACKGROUND_JOB_NOT_RETRYABLE", "Only failed background jobs can be retried")
        if job.attempt >= job.max_attempts:
            raise AppError(409, "BACKGROUND_JOB_ATTEMPTS_EXHAUSTED", "Background job retry limit has been reached")
        if job.task_name not in self.retryable_tasks:
            raise AppError(409, "BACKGROUND_JOB_TASK_NOT_RETRYABLE", "This background job type is not manually retryable")
        args_payload = list(job.args_payload or [])
        if any(value == "<redacted>" for value in args_payload):
            raise AppError(409, "BACKGROUND_JOB_ARGUMENTS_REDACTED", "This job cannot be retried because its arguments are unavailable")
        from app.core.correlation import current_correlation_id

        correlation_id = str(context.get("request_id") or current_correlation_id())
        retried = OperationalJob(id=str(__import__("uuid").uuid4()), task_name=job.task_name, queue=job.queue, status="queued", attempt=job.attempt + 1, max_attempts=job.max_attempts, resource_type=job.resource_type, resource_id=job.resource_id, args_payload=args_payload, request_id=correlation_id, parent_job_id=job.id)
        self.db.add(retried)
        self.db.flush()
        self.db.add(OperationalJobDispatch(job_id=retried.id, task_name=retried.task_name, queue=retried.queue, args_payload=args_payload, correlation_id=correlation_id))
        self._complete_command(command, "background_job", retried.id, {"id": retried.id})
        self._audit(current, "background_job.retry", "background_job", job.id, payload.reason, context, {"new_job_id": retried.id, "attempt": retried.attempt})
        self.db.commit()
        self.db.refresh(retried)
        self.publish_retry(retried.id)
        return retried

    def publish_retry(self, job_id: str) -> bool:
        dispatch = self.db.scalar(select(OperationalJobDispatch).where(OperationalJobDispatch.job_id == job_id).with_for_update())
        if dispatch is None or dispatch.status == "published":
            return True
        dispatch.attempts += 1
        try:
            celery_app.send_task(
                dispatch.task_name,
                args=list(dispatch.args_payload or []),
                queue=dispatch.queue,
                task_id=dispatch.job_id,
                headers={"retry_of": self.db.get(OperationalJob, dispatch.job_id).parent_job_id, "request_id": dispatch.correlation_id},
            )
        except Exception as exc:
            from app.core.errors import safe_error_code

            dispatch.last_error = safe_error_code(exc, "BACKGROUND_JOB_DISPATCH_FAILED")
            dispatch.available_at = _utcnow() + timedelta(seconds=min(300, 2 ** min(dispatch.attempts, 8)))
            self.db.commit()
            return False
        dispatch.status = "published"
        dispatch.published_at = _utcnow()
        dispatch.last_error = None
        self.db.commit()
        return True

    def publish_pending_retries(self, limit: int = 100) -> int:
        dispatches = list(self.db.scalars(select(OperationalJobDispatch).where(OperationalJobDispatch.status == "pending", OperationalJobDispatch.available_at <= _utcnow()).order_by(OperationalJobDispatch.created_at).limit(limit)))
        return sum(1 for item in dispatches if self.publish_retry(item.job_id))

    @staticmethod
    def job_view(job: OperationalJob) -> BackgroundJobView:
        return BackgroundJobView(id=job.id, type=job.task_name, queue=job.queue, status=job.status, attempt=job.attempt, max_attempts=job.max_attempts, resource_type=job.resource_type, resource_id=job.resource_id, error_code=job.error_code, created_at=job.created_at, started_at=job.started_at, finished_at=job.finished_at)

    def diagnostics(self) -> OpsDiagnosticsView:
        database = "ok"
        redis_status = "ok"
        try:
            self.db.execute(select(1))
        except Exception:
            database = "unavailable"
        try:
            redis.Redis.from_url(get_settings().redis_url, socket_connect_timeout=1, socket_timeout=1).ping()
        except redis.RedisError:
            redis_status = "unavailable"
        since = _utcnow() - timedelta(hours=24)
        failed = self.db.scalar(select(func.count()).select_from(OperationalJob).where(OperationalJob.status.in_(["failed", "dead_letter"]), OperationalJob.created_at >= since)) or 0
        pending = self.db.scalar(select(func.count()).select_from(OperationalJob).where(OperationalJob.status.in_(["queued", "running"]))) or 0
        dispatch_tables = ["product_job_search_dispatches", "product_recommendation_dispatches", "product_privacy_dispatches", "product_operational_job_dispatches"]
        pending_dispatches = 0
        for table_name in dispatch_tables:
            table = OperationalJob.metadata.tables.get(table_name)
            if table is not None:
                pending_dispatches += self.db.scalar(select(func.count()).select_from(table).where(table.c.status == "pending")) or 0
        overall = "ok" if database == "ok" and redis_status == "ok" else "degraded"
        return OpsDiagnosticsView(status=overall, database=database, redis=redis_status, failed_jobs_24h=failed, pending_jobs=pending, pending_dispatches=pending_dispatches)

    def provider_usage_summary(
        self,
        provider: str | None,
        purpose: str | None,
        period_start: datetime | None,
        period_end: datetime | None,
    ) -> ProviderUsageSummaryView:
        end = period_end or _utcnow()
        start = period_start or end - timedelta(hours=24)
        if end <= start or end - start > timedelta(days=31):
            raise AppError(422, "INVALID_USAGE_PERIOD", "Provider usage period must be positive and no longer than 31 days")
        statement = select(ProviderUsageEvent).where(
            ProviderUsageEvent.occurred_at >= start,
            ProviderUsageEvent.occurred_at < end,
        )
        if provider:
            statement = statement.where(ProviderUsageEvent.provider == provider)
        if purpose:
            statement = statement.where(ProviderUsageEvent.purpose == purpose)
        records = list(self.db.scalars(statement))
        usage_rows = [item.usage_json or {} for item in records]
        latencies = [item.latency_ms for item in records if item.latency_ms is not None]
        return ProviderUsageSummaryView(
            period_start=start,
            period_end=end,
            provider=provider,
            purpose=purpose,
            calls=len(records),
            failures=sum(1 for item in records if item.status == "failed"),
            estimated_cost_minor=sum(item.estimated_cost_minor or 0 for item in records),
            input_tokens=sum(int(item.get("input_tokens") or 0) for item in usage_rows),
            output_tokens=sum(int(item.get("output_tokens") or 0) for item in usage_rows),
            average_latency_ms=(sum(latencies) / len(latencies)) if latencies else None,
        )

    def _command(self, current: ProductCurrentUser, command_type: str, idempotency_key: str, payload: dict[str, Any]) -> tuple[PrivilegedCommand, bool]:
        request_hash = self._hash(payload)
        self.db.scalar(select(User.id).where(User.id == current.id).with_for_update())
        existing = self.db.scalar(select(PrivilegedCommand).where(PrivilegedCommand.actor_user_id == current.id, PrivilegedCommand.command_type == command_type, PrivilegedCommand.idempotency_key == idempotency_key))
        if existing is not None:
            if existing.request_hash != request_hash:
                raise AppError(409, "IDEMPOTENCY_KEY_REUSED", "Idempotency-Key was already used with a different request")
            if existing.status != "completed":
                raise AppError(409, "PRIVILEGED_COMMAND_IN_PROGRESS", "Privileged command is still processing", retryable=True)
            return existing, True
        command = PrivilegedCommand(actor_user_id=current.id, command_type=command_type, idempotency_key=idempotency_key, request_hash=request_hash)
        self.db.add(command)
        self.db.flush()
        return command, False

    @staticmethod
    def _complete_command(command: PrivilegedCommand, resource_type: str, resource_id: str | None, response: dict[str, Any]) -> None:
        command.status = "completed"
        command.resource_type = resource_type
        command.resource_id = resource_id
        command.response_snapshot = response
        command.completed_at = _utcnow()

    def _audit(self, current: ProductCurrentUser, action: str, resource_type: str | None, resource_id: str | None, reason: str | None, context: dict[str, Any], metadata: dict[str, Any]) -> None:
        head = self.db.scalar(select(AuditChainHead).where(AuditChainHead.id == "privileged").with_for_update())
        if head is None:
            head = AuditChainHead(id="privileged", sequence=0)
            self.db.add(head)
            self.db.flush()
        previous_hash = head.last_hash
        sequence = head.sequence + 1
        created_at = _utcnow()
        body = {"sequence": sequence, "actor": current.id, "action": action, "resource_type": resource_type, "resource_id": resource_id, "reason": reason, "request_id": context.get("request_id"), "metadata": metadata, "previous_hash": previous_hash, "created_at": created_at.isoformat()}
        event_hash = hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()
        ip = str(context.get("ip") or "")
        self.db.add(PrivilegedAuditEvent(sequence=sequence, actor_user_id=current.id, action=action, resource_type=resource_type, resource_id=resource_id, reason=reason, request_id=context.get("request_id"), source_ip_hash=hashlib.sha256(ip.encode()).hexdigest() if ip else None, metadata_json=metadata, previous_hash=previous_hash, event_hash=event_hash, created_at=created_at))
        head.sequence = sequence
        head.last_hash = event_hash

    @staticmethod
    def _mask_email(email: str) -> str:
        local, _, domain = email.partition("@")
        return (local[:2] or "*") + "***@" + domain

    @staticmethod
    def _hash(payload: dict[str, Any]) -> str:
        return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()

    @staticmethod
    def _period(period_start: datetime | None, period_end: datetime | None, maximum_days: int) -> tuple[datetime, datetime]:
        end = period_end or _utcnow()
        start = period_start or end - timedelta(days=30)
        if end <= start or end - start > timedelta(days=maximum_days):
            raise AppError(422, "INVALID_TIME_RANGE", "Time range is invalid or exceeds the allowed window")
        return start, end

    @staticmethod
    def _encode_cursor(created_at: datetime, item_id: str) -> str:
        return base64.urlsafe_b64encode((created_at.isoformat() + "|" + item_id).encode()).decode().rstrip("=")

    @staticmethod
    def _decode_cursor(value: str) -> tuple[datetime, str]:
        try:
            decoded = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4)).decode()
            timestamp, item_id = decoded.rsplit("|", 1)
            return datetime.fromisoformat(timestamp), item_id
        except (ValueError, UnicodeDecodeError) as exc:
            raise AppError(422, "INVALID_CURSOR", "Cursor is invalid") from exc
