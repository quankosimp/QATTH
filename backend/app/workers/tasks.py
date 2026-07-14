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
        content, provider = OpenAICvAdapter().extract(file_content, asset.original_filename, scan.locale_hint)
        serialized = CvContent.model_validate(content).model_dump(mode="json")
        draft = db.scalar(select(CvDraft).where(CvDraft.scan_id == scan.id))
        if draft is None:
            draft = CvDraft(
                scan_id=scan.id,
                revision=1,
                schema_version=scan.schema_version,
                content=serialized,
                field_confidence={},
                warnings=[],
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
        analysis.scores = output.scores
        analysis.findings = output.findings
        analysis.provider = "openai"
        analysis.provider_run_id = provider.get("provider_run_id")
        analysis.status = "completed"
        analysis.completed_at = datetime.now(UTC)
        db.commit()
        return {"status": "completed", "analysis_id": analysis_id}
    except Exception as exc:
        db.rollback()
        analysis = db.get(CvAnalysis, analysis_id)
        if analysis is not None:
            analysis.status = "failed"
            analysis.error = {"code": "CV_ANALYSIS_FAILED", "message": str(exc)[:1000]}
            analysis.completed_at = datetime.now(UTC)
            db.commit()
        raise
    finally:
        db.close()
