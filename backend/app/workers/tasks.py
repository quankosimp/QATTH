from datetime import UTC, datetime

from sqlalchemy import select

from app.core.celery_app import celery_app
from app.core.db import SessionLocal
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


@celery_app.task(name="product.cv.extract", acks_late=True)
def extract_product_cv_task(scan_id: str) -> dict:
    from app.models.product_cv import CvDraft, CvScan, ProductFileAsset
    from app.schemas.product_cv import CvContent
    from app.services.object_storage import ObjectStorage
    from app.services.openai_cv import OpenAICvAdapter
    from app.services.product_cv import _checksum
    from app.services.provider_usage import ProviderUsageService

    db = SessionLocal()
    try:
        scan = db.scalar(select(CvScan).where(CvScan.id == scan_id).with_for_update())
        if scan is None:
            return {"status": "missing", "scan_id": scan_id}
        if scan.status in {"draft_ready", "confirmed"}:
            return {"status": scan.status, "scan_id": scan_id}
        if scan.status not in {"queued", "extraction_failed"}:
            return {"status": "ignored", "scan_id": scan_id}
        scan.status = "extracting"
        scan.started_at = datetime.now(UTC)
        scan.error = None
        db.commit()

        asset = db.get(ProductFileAsset, scan.file_id)
        if asset is None or asset.upload_status != "uploaded" or asset.security_status != "clean":
            raise RuntimeError("source file is not available")
        file_content = ObjectStorage().read(asset.object_key, asset.declared_size_bytes)
        extraction, provider = OpenAICvAdapter().extract(file_content, asset.original_filename, scan.locale_hint)
        ProviderUsageService(db).success(
            user_id=scan.user_id,
            provider="openai",
            purpose="cv_extraction",
            resource_type="cv_scan",
            resource_id=scan.id,
            metadata=provider,
        )
        serialized = CvContent.model_validate(extraction.content).model_dump(mode="json")
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
        db.commit()
        return {"status": "draft_ready", "scan_id": scan_id, "draft_id": draft.id}
    except Exception as exc:
        db.rollback()
        scan = db.get(CvScan, scan_id)
        if scan is not None:
            ProviderUsageService(db).failure(user_id=scan.user_id, provider="openai", purpose="cv_extraction", resource_type="cv_scan", resource_id=scan.id, error=exc)
            scan.status = "extraction_failed"
            scan.error = {"code": "CV_EXTRACTION_FAILED", "message": str(exc)[:1000]}
            scan.completed_at = datetime.now(UTC)
            db.commit()
        raise
    finally:
        db.close()


@celery_app.task(name="product.cv.analyze", acks_late=True)
def analyze_product_cv_task(analysis_id: str) -> dict:
    from app.models.product_cv import CvAnalysis, ProductCvVersion
    from app.schemas.product_cv import CvContent
    from app.services.openai_cv import OpenAICvAdapter
    from app.services.provider_usage import ProviderUsageService

    db = SessionLocal()
    try:
        analysis = db.scalar(select(CvAnalysis).where(CvAnalysis.id == analysis_id).with_for_update())
        if analysis is None:
            return {"status": "missing", "analysis_id": analysis_id}
        if analysis.status == "completed":
            return {"status": "completed", "analysis_id": analysis_id}
        analysis.status = "processing"
        analysis.started_at = datetime.now(UTC)
        analysis.error = None
        db.commit()

        version = db.get(ProductCvVersion, analysis.cv_version_id)
        if version is None:
            raise RuntimeError("CV version was not found")
        output, provider = OpenAICvAdapter().analyze(CvContent.model_validate(version.content))
        ProviderUsageService(db).success(user_id=analysis.user_id, provider="openai", purpose="cv_analysis", resource_type="cv_analysis", resource_id=analysis.id, metadata=provider)
        analysis.scores = output.scores
        analysis.findings = output.findings
        analysis.provider = "openai"
        analysis.provider_run_id = provider.get("provider_run_id")
        analysis.model_name = provider.get("model")
        analysis.model_configuration_id = provider.get("model_configuration_id")
        analysis.prompt_version = provider.get("prompt_version")
        analysis.usage_json = provider.get("usage", {})
        analysis.disclaimer = "AI-generated guidance; verify recommendations before changing or submitting your CV."
        analysis.status = "completed"
        analysis.completed_at = datetime.now(UTC)
        from app.services.product_billing import ProductBillingService

        ProductBillingService(db).capture(analysis.credit_reservation_id)
        db.commit()
        return {"status": "completed", "analysis_id": analysis_id}
    except Exception as exc:
        db.rollback()
        analysis = db.get(CvAnalysis, analysis_id)
        if analysis is not None:
            ProviderUsageService(db).failure(user_id=analysis.user_id, provider="openai", purpose="cv_analysis", resource_type="cv_analysis", resource_id=analysis.id, error=exc)
            analysis.status = "failed"
            analysis.error = {"code": "CV_ANALYSIS_FAILED", "message": str(exc)[:1000]}
            analysis.completed_at = datetime.now(UTC)
            from app.services.product_billing import ProductBillingService

            ProductBillingService(db).release(analysis.credit_reservation_id, "cv_analysis_failed")
            db.commit()
        raise
    finally:
        db.close()


@celery_app.task(name="product.interview.evaluate", acks_late=True)
def evaluate_product_interview_task(report_id: str) -> dict:
    from app.models.product_interview import ProductInterview, ProductInterviewEvent, ProductInterviewReport
    from app.services.openai_interview import OpenAIInterviewEvaluator
    from app.services.provider_usage import ProviderUsageService

    db = SessionLocal()
    try:
        report = db.scalar(
            select(ProductInterviewReport).where(ProductInterviewReport.id == report_id).with_for_update()
        )
        if report is None:
            return {"status": "missing", "report_id": report_id}
        if report.status == "ready":
            return {"status": "ready", "report_id": report_id}
        report.status = "processing"
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
        ProviderUsageService(db).success(user_id=report.user_id, provider="openai", purpose="interview_evaluation", resource_type="interview_report", resource_id=report.id, metadata=provider)
        known_event_ids = {event.id for event in events}
        for finding in [*output.strengths, *output.gaps]:
            if not finding.evidence_event_ids or not set(finding.evidence_event_ids).issubset(known_event_ids):
                raise RuntimeError("Evaluation references unknown transcript evidence")
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
        interview.status = "completed"
        interview.ended_at = interview.ended_at or datetime.now(UTC)
        from app.services.candidate_profiles import invalidate_candidate_profiles

        invalidate_candidate_profiles(db, report.user_id)
        db.commit()
        return {"status": "ready", "report_id": report_id}
    except Exception as exc:
        db.rollback()
        report = db.get(ProductInterviewReport, report_id)
        if report is not None:
            ProviderUsageService(db).failure(user_id=report.user_id, provider="openai", purpose="interview_evaluation", resource_type="interview_report", resource_id=report.id, error=exc)
            report.status = "failed"
            report.error = {"code": "INTERVIEW_EVALUATION_FAILED", "message": str(exc)[:1000]}
            interview = db.get(ProductInterview, report.interview_id)
            if interview is not None:
                interview.status = "evaluation_failed"
                interview.failure = report.error
            db.commit()
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
            from app.core.errors import AppError

            code = exc.code if isinstance(exc, AppError) else "JOB_SEARCH_FAILED"
            message = exc.message if isinstance(exc, AppError) else "Job search execution failed"
            run.status = "failed"
            run.error = {"code": code, "message": message}
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
            run.error = {"code": "RECOMMENDATION_FAILED", "message": str(exc)[:1000]}
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
            privacy_request.error = {"code": "PRIVACY_REQUEST_FAILED", "message": str(exc)[:1000]}
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


@celery_app.task(name="product.privacy.cleanup_artifacts")
def cleanup_product_privacy_artifacts_task() -> dict:
    from app.services.product_privacy import ProductPrivacyService

    db = SessionLocal()
    try:
        deleted = ProductPrivacyService(db).cleanup_expired_artifacts()
        return {"status": "completed", "artifacts_deleted": deleted}
    finally:
        db.close()
