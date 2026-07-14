from datetime import UTC, datetime

from sqlalchemy import select

from app.core.celery_app import celery_app
from app.core.db import SessionLocal
from app.core.errors import safe_error_payload
from app.models.db import BackgroundTask


@celery_app.task(name="tasks.noop")
def noop_task(background_task_id: str) -> dict:
    db = SessionLocal()
    try:
        task = db.get(BackgroundTask, background_task_id)
        if not task:
            return {"status": "missing", "task_id": background_task_id}
        task.status = "completed"
        task.started_at = task.started_at or datetime.now(UTC)
        task.completed_at = datetime.now(UTC)
        task.result_payload = {"message": "No-op task completed."}
        db.commit()
        return {"status": "completed", "task_id": background_task_id}
    finally:
        db.close()


@celery_app.task(bind=True, name="product.cv.extract", acks_late=True)
def extract_product_cv_task(self, scan_id: str) -> dict:
    from app.models.product_cv import CvDraft, CvScan, ProductFileAsset
    from app.schemas.product_cv import CvContent
    from app.services.object_storage import ObjectStorage
    from app.services.openai_cv import OpenAICvAdapter
    from app.services.product_cv import _checksum
    from app.services.provider_usage import ProviderUsageService
    from app.services.task_leases import ProductTaskLeaseService

    db = SessionLocal()
    lease_id = str(self.request.id)
    try:
        scan = db.scalar(select(CvScan).where(CvScan.id == scan_id).with_for_update())
        if scan is None:
            return {"status": "missing", "scan_id": scan_id}
        if scan.status in {"draft_ready", "confirmed"}:
            return {"status": scan.status, "scan_id": scan_id}
        if scan.status not in {"queued", "extraction_failed"}:
            return {"status": "ignored", "scan_id": scan_id}
        if not ProductTaskLeaseService.claim(scan, lease_id, "extracting"):
            return {"status": "in_progress", "scan_id": scan_id}
        scan.started_at = datetime.now(UTC)
        scan.error = None
        db.commit()

        asset = db.get(ProductFileAsset, scan.file_id)
        if asset is None or asset.upload_status != "uploaded" or asset.security_status != "clean":
            raise RuntimeError("source file is not available")
        file_content = ObjectStorage().read(asset.object_key, asset.declared_size_bytes)
        extraction, provider = OpenAICvAdapter().extract(file_content, asset.original_filename, scan.locale_hint)
        serialized = CvContent.model_validate(extraction.content).model_dump(mode="json")
        scan = db.scalar(
            select(CvScan).where(CvScan.id == scan_id).execution_options(populate_existing=True).with_for_update()
        )
        if scan is None or not ProductTaskLeaseService.owns(scan, lease_id):
            return {"status": "superseded", "scan_id": scan_id}
        ProviderUsageService(db).success(user_id=scan.user_id, provider="openai", purpose="cv_extraction", resource_type="cv_scan", resource_id=scan.id, metadata=provider)
        draft = db.scalar(select(CvDraft).where(CvDraft.scan_id == scan.id))
        if draft is None:
            draft = CvDraft(
                scan_id=scan.id,
                revision=1,
                schema_version=scan.schema_version,
                content=serialized,
                field_confidence=extraction.field_confidence,
                warnings=extraction.warnings,
                checksum=_checksum(serialized),
            )
            db.add(draft)
        scan.status = "draft_ready"
        scan.provider = "openai"
        scan.provider_run_id = provider.get("provider_run_id")
        scan.completed_at = datetime.now(UTC)
        ProductTaskLeaseService.clear(scan)
        db.commit()
        return {"status": "draft_ready", "scan_id": scan_id, "draft_id": draft.id}
    except Exception as exc:
        db.rollback()
        scan = db.scalar(select(CvScan).where(CvScan.id == scan_id).execution_options(populate_existing=True).with_for_update())
        if scan is not None and ProductTaskLeaseService.owns(scan, lease_id):
            ProviderUsageService(db).failure(user_id=scan.user_id, provider="openai", purpose="cv_extraction", resource_type="cv_scan", resource_id=scan.id, error=exc)
            scan.status = "extraction_failed"
            scan.error = safe_error_payload(
                exc,
                "CV_EXTRACTION_FAILED",
                "CV extraction failed. Retry after checking the source file.",
            )
            scan.completed_at = datetime.now(UTC)
            ProductTaskLeaseService.clear(scan)
            db.commit()
        elif scan is not None:
            return {"status": "superseded", "scan_id": scan_id}
        raise
    finally:
        db.close()


@celery_app.task(bind=True, name="product.cv.analyze", acks_late=True)
def analyze_product_cv_task(self, analysis_id: str) -> dict:
    from app.models.product_cv import CvAnalysis, ProductCvVersion
    from app.schemas.product_cv import CvContent
    from app.services.openai_cv import OpenAICvAdapter
    from app.services.provider_usage import ProviderUsageService
    from app.services.task_leases import ProductTaskLeaseService

    db = SessionLocal()
    lease_id = str(self.request.id)
    try:
        analysis = db.scalar(select(CvAnalysis).where(CvAnalysis.id == analysis_id).with_for_update())
        if analysis is None:
            return {"status": "missing", "analysis_id": analysis_id}
        if analysis.status == "completed":
            return {"status": "completed", "analysis_id": analysis_id}
        if not ProductTaskLeaseService.claim(analysis, lease_id, "processing"):
            return {"status": "in_progress", "analysis_id": analysis_id}
        analysis.started_at = datetime.now(UTC)
        analysis.error = None
        db.commit()

        version = db.get(ProductCvVersion, analysis.cv_version_id)
        if version is None:
            raise RuntimeError("CV version was not found")
        output, provider = OpenAICvAdapter().analyze(CvContent.model_validate(version.content))
        analysis = db.scalar(
            select(CvAnalysis).where(CvAnalysis.id == analysis_id).execution_options(populate_existing=True).with_for_update()
        )
        if analysis is None or not ProductTaskLeaseService.owns(analysis, lease_id):
            return {"status": "superseded", "analysis_id": analysis_id}
        ProviderUsageService(db).success(user_id=analysis.user_id, provider="openai", purpose="cv_analysis", resource_type="cv_analysis", resource_id=analysis.id, metadata=provider)
        analysis.scores = output.scores
        analysis.findings = [item.model_dump(mode="json") for item in output.findings]
        analysis.provider = "openai"
        analysis.provider_run_id = provider.get("provider_run_id")
        analysis.model_name = provider.get("model")
        analysis.model_configuration_id = provider.get("model_configuration_id")
        analysis.prompt_version = provider.get("prompt_version")
        analysis.usage_json = provider.get("usage", {})
        analysis.disclaimer = "AI-generated guidance; verify recommendations before changing or submitting your CV."
        analysis.status = "completed"
        analysis.completed_at = datetime.now(UTC)
        ProductTaskLeaseService.clear(analysis)
        from app.services.product_billing import ProductBillingService

        ProductBillingService(db).capture(analysis.credit_reservation_id)
        db.commit()
        return {"status": "completed", "analysis_id": analysis_id}
    except Exception as exc:
        db.rollback()
        analysis = db.scalar(select(CvAnalysis).where(CvAnalysis.id == analysis_id).execution_options(populate_existing=True).with_for_update())
        if analysis is not None and ProductTaskLeaseService.owns(analysis, lease_id):
            ProviderUsageService(db).failure(user_id=analysis.user_id, provider="openai", purpose="cv_analysis", resource_type="cv_analysis", resource_id=analysis.id, error=exc)
            analysis.status = "failed"
            analysis.error = safe_error_payload(
                exc,
                "CV_ANALYSIS_FAILED",
                "CV analysis failed. Retry the analysis later.",
            )
            analysis.completed_at = datetime.now(UTC)
            ProductTaskLeaseService.clear(analysis)
            from app.services.product_billing import ProductBillingService

            ProductBillingService(db).release(analysis.credit_reservation_id, "cv_analysis_failed")
            db.commit()
        elif analysis is not None:
            return {"status": "superseded", "analysis_id": analysis_id}
        raise
    finally:
        db.close()


@celery_app.task(bind=True, name="product.interview.evaluate", acks_late=True)
def evaluate_product_interview_task(self, report_id: str) -> dict:
    from app.models.product_interview import ProductInterview, ProductInterviewEvent, ProductInterviewReport
    from app.services.openai_interview import OpenAIInterviewEvaluator
    from app.services.provider_usage import ProviderUsageService
    from app.services.task_leases import ProductTaskLeaseService

    db = SessionLocal()
    lease_id = str(self.request.id)
    try:
        report = db.scalar(
            select(ProductInterviewReport).where(ProductInterviewReport.id == report_id).with_for_update()
        )
        if report is None:
            return {"status": "missing", "report_id": report_id}
        if report.status == "ready":
            return {"status": "ready", "report_id": report_id}
        if not ProductTaskLeaseService.claim(report, lease_id, "processing"):
            return {"status": "in_progress", "report_id": report_id}
        report.error = None
        db.commit()
        interview = db.get(ProductInterview, report.interview_id)
        if interview is None:
            raise RuntimeError("Interview was not found")
        events = list(
            db.scalars(
                select(ProductInterviewEvent)
                .where(
                    ProductInterviewEvent.interview_id == interview.id,
                    ProductInterviewEvent.sequence <= report.transcript_version,
                    ProductInterviewEvent.text.is_not(None),
                )
                .order_by(ProductInterviewEvent.sequence)
            )
        )
        transcript = [
            {
                "event_id": event.id,
                "sequence": event.sequence,
                "speaker": event.speaker,
                "text": event.text,
            }
            for event in events
        ]
        output, provider = OpenAIInterviewEvaluator().evaluate(
            transcript,
            interview.cv_snapshot,
            interview.plan_snapshot,
            report.rubric_version,
        )
        known_event_ids = {event.id for event in events}
        for finding in [*output.strengths, *output.gaps]:
            if not finding.evidence_event_ids or not set(finding.evidence_event_ids).issubset(known_event_ids):
                raise RuntimeError("Evaluation references unknown transcript evidence")
        report = db.scalar(
            select(ProductInterviewReport).where(ProductInterviewReport.id == report_id).execution_options(populate_existing=True).with_for_update()
        )
        if report is None or not ProductTaskLeaseService.owns(report, lease_id):
            return {"status": "superseded", "report_id": report_id}
        ProviderUsageService(db).success(user_id=report.user_id, provider="openai", purpose="interview_evaluation", resource_type="interview_report", resource_id=report.id, metadata=provider)
        report.scores = {
            "technical_depth": output.technical_depth,
            "communication": output.communication,
            "problem_solving": output.problem_solving,
            "evidence_quality": output.evidence_quality,
            "role_fit": output.role_fit,
        }
        report.strengths = [item.model_dump(mode="json") for item in output.strengths]
        report.gaps = [item.model_dump(mode="json") for item in output.gaps]
        report.actions = output.actions
        report.disclaimer = "AI-generated coaching feedback. It is not a hiring decision or guarantee of job fit."
        report.provider_run_id = provider.get("provider_run_id")
        report.model = provider.get("model") or report.model
        report.model_configuration_id = provider.get("model_configuration_id") or report.model_configuration_id
        report.prompt_version = provider.get("prompt_version") or report.prompt_version
        report.usage_json = provider.get("usage", {})
        report.estimated_cost_minor = provider.get("estimated_cost_minor")
        report.status = "ready"
        report.completed_at = datetime.now(UTC)
        ProductTaskLeaseService.clear(report)
        interview.status = "completed"
        interview.ended_at = interview.ended_at or datetime.now(UTC)
        from app.services.candidate_profiles import invalidate_candidate_profiles

        invalidate_candidate_profiles(db, report.user_id)
        db.commit()
        return {"status": "ready", "report_id": report_id}
    except Exception as exc:
        db.rollback()
        report = db.scalar(select(ProductInterviewReport).where(ProductInterviewReport.id == report_id).execution_options(populate_existing=True).with_for_update())
        if report is not None and ProductTaskLeaseService.owns(report, lease_id):
            ProviderUsageService(db).failure(user_id=report.user_id, provider="openai", purpose="interview_evaluation", resource_type="interview_report", resource_id=report.id, error=exc)
            report.status = "failed"
            report.error = safe_error_payload(
                exc,
                "INTERVIEW_EVALUATION_FAILED",
                "Interview evaluation failed. Retry the evaluation later.",
            )
            ProductTaskLeaseService.clear(report)
            interview = db.get(ProductInterview, report.interview_id)
            if interview is not None:
                interview.status = "evaluation_failed"
                interview.failure = report.error
            db.commit()
        elif report is not None:
            return {"status": "superseded", "report_id": report_id}
        raise
    finally:
        db.close()


@celery_app.task(name="product.interview.expire_timed_out")
def expire_timed_out_product_interviews_task() -> dict:
    from app.services.product_interview import ProductInterviewService

    db = SessionLocal()
    try:
        return {"status": "completed", **ProductInterviewService(db).expire_timed_out()}
    finally:
        db.close()


@celery_app.task(name="product.tasks.publish_dispatches")
def publish_product_task_dispatches_task() -> dict:
    from app.services.task_dispatch import ProductTaskDispatchService

    db = SessionLocal()
    try:
        published = ProductTaskDispatchService(db).publish_pending()
        return {"status": "completed", "dispatches_published": published}
    finally:
        db.close()


@celery_app.task(name="product.tasks.recover_stalled")
def recover_stalled_product_tasks_task() -> dict:
    from app.services.task_leases import ProductTaskLeaseService

    db = SessionLocal()
    try:
        return {"status": "completed", **ProductTaskLeaseService(db).recover_stalled()}
    finally:
        db.close()


@celery_app.task(name="product.jobs.search", acks_late=True)
def execute_product_job_search_task(run_id: str) -> dict:
    from app.models.product_jobs import JobSearchRun
    from app.services.product_job_search import ProductJobSearchService

    db = SessionLocal()
    try:
        ProductJobSearchService(db).execute(run_id)
        run = db.get(JobSearchRun, run_id)
        return {"status": run.status if run else "missing", "run_id": run_id}
    except Exception as exc:
        db.rollback()
        run = db.get(JobSearchRun, run_id)
        if run is not None:
            run.status = "failed"
            run.error = safe_error_payload(exc, "JOB_SEARCH_FAILED", "Job search execution failed.")
            run.completed_at = datetime.now(UTC)
            db.commit()
            ProductJobSearchService(db).emit(run_id, "run.failed", run.error)
        return {"status": "failed", "run_id": run_id}
    finally:
        db.close()


@celery_app.task(name="product.jobs.mark_stale")
def mark_stale_product_jobs_task() -> dict:
    from app.services.product_job_search import ProductJobSearchService

    db = SessionLocal()
    try:
        return {"status": "completed", "jobs_marked_stale": ProductJobSearchService(db).mark_stale_jobs()}
    finally:
        db.close()


@celery_app.task(name="product.jobs.publish_dispatches")
def publish_product_job_search_dispatches_task() -> dict:
    from app.services.product_job_search import ProductJobSearchService

    db = SessionLocal()
    try:
        published = ProductJobSearchService(db).publish_pending_dispatches()
        return {"status": "completed", "dispatches_published": published}
    finally:
        db.close()


@celery_app.task(name="product.recommendations.generate", acks_late=True)
def execute_product_recommendation_task(run_id: str) -> dict:
    from app.models.product_recommendations import RecommendationRun
    from app.services.product_recommendations import ProductRecommendationService

    db = SessionLocal()
    try:
        ProductRecommendationService(db).execute(run_id)
        run = db.get(RecommendationRun, run_id)
        return {"status": run.status if run else "missing", "run_id": run_id}
    except Exception as exc:
        db.rollback()
        run = db.get(RecommendationRun, run_id)
        if run is not None:
            run.status = "failed"
            run.error = safe_error_payload(
                exc,
                "RECOMMENDATION_FAILED",
                "Recommendation generation failed. Retry the run later.",
            )
            run.completed_at = datetime.now(UTC)
            db.commit()
        raise
    finally:
        db.close()


@celery_app.task(name="product.recommendations.publish_dispatches")
def publish_product_recommendation_dispatches_task() -> dict:
    from app.services.product_recommendations import ProductRecommendationService

    db = SessionLocal()
    try:
        published = ProductRecommendationService(db).publish_pending_dispatches()
        return {"status": "completed", "dispatches_published": published}
    finally:
        db.close()


@celery_app.task(name="product.billing.reconcile_reservations")
def reconcile_product_credit_reservations_task() -> dict:
    from app.services.product_billing import ProductBillingService

    db = SessionLocal()
    try:
        reconciled = ProductBillingService(db).reconcile_expired_reservations()
        return {"status": "completed", "reservations_reconciled": reconciled}
    finally:
        db.close()


@celery_app.task(name="product.billing.reconcile_payments")
def reconcile_product_payments_task() -> dict:
    from app.services.product_billing import ProductBillingService

    db = SessionLocal()
    try:
        return {"status": "completed", **ProductBillingService(db).reconcile_payment_provider()}
    finally:
        db.close()


@celery_app.task(name="product.billing.cleanup_payment_payloads")
def cleanup_product_payment_payloads_task() -> dict:
    from app.services.product_billing import ProductBillingService

    db = SessionLocal()
    try:
        purged = ProductBillingService(db).cleanup_expired_payment_payloads()
        return {"status": "completed", "payment_payloads_purged": purged}
    finally:
        db.close()


@celery_app.task(name="product.privacy.execute", acks_late=True)
def execute_product_privacy_request_task(request_id: str) -> dict:
    from app.models.product_privacy import PrivacyRequest
    from app.services.product_privacy import ProductPrivacyService

    db = SessionLocal()
    try:
        ProductPrivacyService(db).execute(request_id)
        privacy_request = db.get(PrivacyRequest, request_id)
        return {"status": privacy_request.status if privacy_request else "missing", "request_id": request_id}
    except Exception as exc:
        db.rollback()
        privacy_request = db.get(PrivacyRequest, request_id)
        if privacy_request is not None:
            privacy_request.status = "failed"
            privacy_request.error = safe_error_payload(
                exc,
                "PRIVACY_REQUEST_FAILED",
                "Privacy request processing failed. Retry the request later.",
            )
            privacy_request.lease_expires_at = None
            db.commit()
        raise
    finally:
        db.close()


@celery_app.task(name="product.privacy.publish_dispatches")
def publish_product_privacy_dispatches_task() -> dict:
    from app.services.product_privacy import ProductPrivacyService

    db = SessionLocal()
    try:
        published = ProductPrivacyService(db).publish_pending_dispatches()
        return {"status": "completed", "dispatches_published": published}
    finally:
        db.close()


@celery_app.task(name="product.ops.publish_retries")
def publish_product_operational_job_retries_task() -> dict:
    from app.services.product_admin_ops import ProductAdminOpsService

    db = SessionLocal()
    try:
        published = ProductAdminOpsService(db).publish_pending_retries()
        return {"status": "completed", "dispatches_published": published}
    finally:
        db.close()


@celery_app.task(name="product.privacy.cleanup_artifacts")
def cleanup_product_privacy_artifacts_task() -> dict:
    from app.services.product_privacy import ProductPrivacyService

    db = SessionLocal()
    try:
        result = ProductPrivacyService(db).cleanup_expired_artifacts()
        return {"status": "completed", **result}
    finally:
        db.close()
