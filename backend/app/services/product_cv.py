from __future__ import annotations

import base64
import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.core.idempotency import IdempotencyService
from app.core.identity_security import ProductCurrentUser
from app.models.product_cv import CvAnalysis, CvDraft, CvScan, ProductCV, ProductCvVersion
from app.schemas.product_cv import (
    ConfirmCvDraftRequest,
    CreateCvScanRequest,
    CvAnalysisView,
    CvContent,
    CvDraftPatch,
    CvDraftView,
    CvPage,
    CvScanView,
    CvVersionView,
    CvView,
)
from app.services.product_files import ProductFileService
from app.services.identity import IdentityService
from app.services.task_dispatch import ProductTaskDispatchService


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _checksum(content: dict[str, Any]) -> str:
    canonical = json.dumps(content, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _encode_cursor(created_at: datetime, item_id: str) -> str:
    return base64.urlsafe_b64encode((created_at.isoformat() + "|" + item_id).encode()).decode().rstrip("=")


def _decode_cursor(value: str) -> tuple[datetime, str]:
    try:
        decoded = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4)).decode()
        timestamp, item_id = decoded.rsplit("|", 1)
        return datetime.fromisoformat(timestamp), item_id
    except (ValueError, UnicodeDecodeError) as exc:
        raise AppError(422, "INVALID_CURSOR", "Cursor is invalid") from exc


class ProductCvService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def create_scan(self, current: ProductCurrentUser, payload: CreateCvScanRequest, idempotency_key: str) -> CvScan:
        idempotency = IdempotencyService(self.db)
        result = idempotency.begin(
            scope="user:" + current.id,
            operation="cv.create_scan",
            key=idempotency_key,
            request_hash=idempotency.request_hash(payload.model_dump(mode="json")),
        )
        replay = self._replayed_resource(current, result, CvScan, "CV_SCAN_NOT_FOUND")
        if replay is not None:
            return replay
        IdentityService(self.db).require_consent(current.id)
        file_asset, _ = ProductFileService(self.db).read_owned(current, payload.file_id)
        if payload.cv_id:
            self._cv(current, payload.cv_id)
        existing = self.db.scalar(
            select(CvScan).where(
                CvScan.file_id == payload.file_id,
                CvScan.schema_version == payload.extraction_schema_version,
                CvScan.attempt_number == 1,
            )
        )
        if existing is not None:
            idempotency.complete(result.record, resource_type="cv_scan", resource_id=existing.id, response_status=202)
            self.db.commit()
            return existing
        scan = CvScan(
            user_id=current.id,
            file_id=file_asset.id,
            cv_id=payload.cv_id,
            status="queued",
            schema_version=payload.extraction_schema_version,
            locale_hint=payload.locale_hint,
            attempt_number=1,
        )
        self.db.add(scan)
        self.db.flush()
        ProductTaskDispatchService(self.db).enqueue("product.cv.extract", "cv_scan", scan.id)
        idempotency.complete(result.record, resource_type="cv_scan", resource_id=scan.id, response_status=202)
        self.db.commit()
        self.db.refresh(scan)
        self._dispatch_scan(scan)
        return scan

    def retry_scan(self, current: ProductCurrentUser, scan_id: str, idempotency_key: str) -> CvScan:
        original = self.get_scan(current, scan_id)
        idempotency = IdempotencyService(self.db)
        result = idempotency.begin(
            scope="user:" + current.id,
            operation="cv.retry_scan:" + scan_id,
            key=idempotency_key,
            request_hash=idempotency.request_hash({"scan_id": scan_id}),
        )
        replay = self._replayed_resource(current, result, CvScan, "CV_SCAN_NOT_FOUND")
        if replay is not None:
            return replay
        IdentityService(self.db).require_consent(current.id)
        if original.status != "extraction_failed":
            raise AppError(409, "CV_SCAN_NOT_RETRYABLE", "Only failed CV scans can be retried")
        attempt = (self.db.scalar(select(func.max(CvScan.attempt_number)).where(
            CvScan.file_id == original.file_id,
            CvScan.schema_version == original.schema_version,
        )) or 0) + 1
        scan = CvScan(
            user_id=current.id,
            file_id=original.file_id,
            cv_id=original.cv_id,
            parent_scan_id=original.id,
            attempt_number=attempt,
            status="queued",
            schema_version=original.schema_version,
            locale_hint=original.locale_hint,
        )
        self.db.add(scan)
        self.db.flush()
        ProductTaskDispatchService(self.db).enqueue("product.cv.extract", "cv_scan", scan.id)
        idempotency.complete(result.record, resource_type="cv_scan", resource_id=scan.id, response_status=202)
        self.db.commit()
        self.db.refresh(scan)
        self._dispatch_scan(scan)
        return scan

    def _dispatch_scan(self, scan: CvScan) -> None:
        ProductTaskDispatchService(self.db).publish_resource("product.cv.extract", scan.id)

    def get_scan(self, current: ProductCurrentUser, scan_id: str) -> CvScan:
        scan = self.db.get(CvScan, scan_id)
        if scan is None or (current.role != "admin" and scan.user_id != current.id):
            raise AppError(404, "CV_SCAN_NOT_FOUND", "CV scan was not found")
        return scan

    def get_draft(self, current: ProductCurrentUser, scan_id: str) -> CvDraft:
        scan = self.get_scan(current, scan_id)
        if scan.status not in {"draft_ready", "confirmed"}:
            raise AppError(409, "CV_DRAFT_NOT_READY", "CV draft is not ready")
        draft = self.db.scalar(select(CvDraft).where(CvDraft.scan_id == scan.id))
        if draft is None:
            raise AppError(404, "CV_DRAFT_NOT_FOUND", "CV draft was not found")
        return draft

    def create_version_draft(
        self,
        current: ProductCurrentUser,
        version_id: str,
        idempotency_key: str,
    ) -> CvDraft:
        idempotency = IdempotencyService(self.db)
        result = idempotency.begin(
            scope="user:" + current.id,
            operation="cv.create_version_draft:" + version_id,
            key=idempotency_key,
            request_hash=idempotency.request_hash({"version_id": version_id}),
        )
        if result.replayed:
            scan = self._replayed_resource(current, result, CvScan, "CV_SCAN_NOT_FOUND")
            return self.get_draft(current, scan.id)
        IdentityService(self.db).require_consent(current.id)
        version = self.db.scalar(
            select(ProductCvVersion)
            .join(ProductCV, ProductCV.id == ProductCvVersion.cv_id)
            .where(
                ProductCvVersion.id == version_id,
                ProductCvVersion.user_id == current.id,
                ProductCV.status == "active",
            )
        )
        if version is None:
            raise AppError(404, "CV_VERSION_NOT_FOUND", "Active CV version was not found")
        attempt = (self.db.scalar(select(func.max(CvScan.attempt_number)).where(
            CvScan.file_id == version.source_file_id,
            CvScan.schema_version == version.schema_version,
        )) or 0) + 1
        now = _utcnow()
        scan = CvScan(
            user_id=current.id,
            file_id=version.source_file_id,
            cv_id=version.cv_id,
            parent_scan_id=version.source_scan_id,
            attempt_number=attempt,
            status="draft_ready",
            schema_version=version.schema_version,
            provider="user_edit",
            started_at=now,
            completed_at=now,
        )
        self.db.add(scan)
        self.db.flush()
        draft = CvDraft(
            scan_id=scan.id,
            revision=1,
            schema_version=version.schema_version,
            content=version.content,
            field_confidence={},
            warnings=["Draft created from immutable CV version " + version.id],
            checksum=version.checksum,
        )
        self.db.add(draft)
        idempotency.complete(result.record, resource_type="cv_scan", resource_id=scan.id, response_status=201)
        self.db.commit()
        self.db.refresh(draft)
        return draft

    def update_draft(self, current: ProductCurrentUser, scan_id: str, revision: int, payload: CvDraftPatch) -> CvDraft:
        scan = self.get_scan(current, scan_id)
        if scan.status != "draft_ready":
            raise AppError(409, "CV_DRAFT_NOT_EDITABLE", "CV draft is not editable")
        draft = self.db.scalar(select(CvDraft).where(CvDraft.scan_id == scan.id).with_for_update())
        if draft is None:
            raise AppError(404, "CV_DRAFT_NOT_FOUND", "CV draft was not found")
        if draft.revision != revision:
            raise AppError(
                409,
                "CV_DRAFT_REVISION_CONFLICT",
                "CV draft was edited by another request",
                details={"current_revision": draft.revision},
            )
        content = CvContent.model_validate(payload.content)
        serialized = content.model_dump(mode="json")
        draft.content = serialized
        draft.checksum = _checksum(serialized)
        draft.revision += 1
        draft.updated_at = _utcnow()
        self.db.commit()
        self.db.refresh(draft)
        return draft

    def confirm(self, current: ProductCurrentUser, scan_id: str, payload: ConfirmCvDraftRequest, idempotency_key: str) -> ProductCvVersion:
        scan = self.get_scan(current, scan_id)
        idempotency = IdempotencyService(self.db)
        result = idempotency.begin(
            scope="user:" + current.id,
            operation="cv.confirm_scan:" + scan_id,
            key=idempotency_key,
            request_hash=idempotency.request_hash(payload.model_dump(mode="json")),
        )
        replay = self._replayed_resource(current, result, ProductCvVersion, "CV_VERSION_NOT_FOUND")
        if replay is not None:
            return replay
        IdentityService(self.db).require_consent(current.id)
        existing = self.db.scalar(select(ProductCvVersion).where(ProductCvVersion.source_scan_id == scan.id))
        if existing is not None:
            idempotency.complete(result.record, resource_type="cv_version", resource_id=existing.id, response_status=201)
            self.db.commit()
            return existing
        if scan.status != "draft_ready":
            raise AppError(409, "CV_SCAN_NOT_CONFIRMABLE", "CV scan cannot be confirmed")
        draft = self.db.scalar(select(CvDraft).where(CvDraft.scan_id == scan.id).with_for_update())
        if draft is None:
            raise AppError(404, "CV_DRAFT_NOT_FOUND", "CV draft was not found")
        if draft.revision != payload.revision or draft.checksum != payload.checksum.lower():
            raise AppError(
                409,
                "CV_DRAFT_REVISION_CONFLICT",
                "Confirm request does not reference the current draft",
                details={"current_revision": draft.revision, "current_checksum": draft.checksum},
            )
        cv = self._cv(current, scan.cv_id) if scan.cv_id else ProductCV(
            user_id=current.id,
            title=payload.title or self._default_title(draft.content),
            status="active",
        )
        if scan.cv_id is None:
            self.db.add(cv)
            self.db.flush()
            scan.cv_id = cv.id
        elif cv.status != "active":
            raise AppError(409, "CV_ARCHIVED", "Archived CVs cannot receive new versions")
        next_version = (self.db.scalar(select(func.max(ProductCvVersion.version)).where(ProductCvVersion.cv_id == cv.id)) or 0) + 1
        version = ProductCvVersion(
            cv_id=cv.id,
            user_id=current.id,
            source_scan_id=scan.id,
            source_file_id=scan.file_id,
            version=next_version,
            schema_version=draft.schema_version,
            content=draft.content,
            checksum=draft.checksum,
        )
        self.db.add(version)
        self.db.flush()
        cv.active_version_id = version.id
        cv.updated_at = _utcnow()
        scan.status = "confirmed"
        scan.completed_at = _utcnow()
        draft.confirmed_at = _utcnow()
        from app.services.candidate_profiles import invalidate_candidate_profiles

        invalidate_candidate_profiles(self.db, current.id)
        idempotency.complete(result.record, resource_type="cv_version", resource_id=version.id, response_status=201)
        self.db.commit()
        self.db.refresh(version)
        return version

    def list_cvs(self, current: ProductCurrentUser, cursor: str | None, limit: int) -> CvPage:
        statement = select(ProductCV).where(ProductCV.user_id == current.id, ProductCV.status != "deleting")
        if cursor:
            created_at, item_id = _decode_cursor(cursor)
            statement = statement.where(
                (ProductCV.created_at < created_at)
                | ((ProductCV.created_at == created_at) & (ProductCV.id < item_id))
            )
        records = list(self.db.scalars(statement.order_by(ProductCV.created_at.desc(), ProductCV.id.desc()).limit(limit + 1)))
        has_more = len(records) > limit
        records = records[:limit]
        return CvPage(
            items=[self.cv_view(item) for item in records],
            next_cursor=_encode_cursor(records[-1].created_at, records[-1].id) if has_more and records else None,
        )

    def list_versions(self, current: ProductCurrentUser, cv_id: str) -> list[ProductCvVersion]:
        cv = self._cv(current, cv_id)
        return list(self.db.scalars(select(ProductCvVersion).where(ProductCvVersion.cv_id == cv.id).order_by(ProductCvVersion.version.desc())))

    def set_active_version(self, current: ProductCurrentUser, cv_id: str, version_id: str, idempotency_key: str) -> ProductCvVersion:
        cv = self._cv(current, cv_id)
        idempotency = IdempotencyService(self.db)
        result = idempotency.begin(
            scope="user:" + current.id,
            operation="cv.set_active_version:" + cv_id,
            key=idempotency_key,
            request_hash=idempotency.request_hash({"version_id": version_id}),
        )
        replay = self._replayed_resource(current, result, ProductCvVersion, "CV_VERSION_NOT_FOUND")
        if replay is not None:
            return replay
        if cv.status != "active":
            raise AppError(409, "CV_ARCHIVED", "Archived CVs cannot change active version")
        version = self.db.scalar(
            select(ProductCvVersion).where(ProductCvVersion.id == version_id, ProductCvVersion.cv_id == cv.id)
        )
        if version is None:
            raise AppError(404, "CV_VERSION_NOT_FOUND", "CV version was not found")
        cv.active_version_id = version.id
        cv.updated_at = _utcnow()
        from app.services.candidate_profiles import invalidate_candidate_profiles

        invalidate_candidate_profiles(self.db, current.id)
        idempotency.complete(result.record, resource_type="cv_version", resource_id=version.id, response_status=200)
        self.db.commit()
        return version

    def archive(self, current: ProductCurrentUser, cv_id: str, idempotency_key: str) -> ProductCV:
        cv = self._cv(current, cv_id)
        idempotency = IdempotencyService(self.db)
        result = idempotency.begin(
            scope="user:" + current.id,
            operation="cv.archive:" + cv_id,
            key=idempotency_key,
            request_hash=idempotency.request_hash({"cv_id": cv_id}),
        )
        replay = self._replayed_resource(current, result, ProductCV, "CV_NOT_FOUND")
        if replay is not None:
            return replay
        cv.status = "archived"
        cv.active_version_id = None
        cv.updated_at = _utcnow()
        from app.services.candidate_profiles import invalidate_candidate_profiles

        invalidate_candidate_profiles(self.db, current.id)
        idempotency.complete(result.record, resource_type="cv", resource_id=cv.id, response_status=200)
        self.db.commit()
        self.db.refresh(cv)
        return cv

    def create_analysis(self, current: ProductCurrentUser, version_id: str, idempotency_key: str) -> CvAnalysis:
        idempotency = IdempotencyService(self.db)
        result = idempotency.begin(
            scope="user:" + current.id,
            operation="cv.create_analysis:" + version_id,
            key=idempotency_key,
            request_hash=idempotency.request_hash({"version_id": version_id}),
        )
        replay = self._replayed_resource(current, result, CvAnalysis, "CV_ANALYSIS_NOT_FOUND")
        if replay is not None:
            return replay
        IdentityService(self.db).require_consent(current.id)
        version = self.db.scalar(
            select(ProductCvVersion)
            .join(ProductCV, ProductCV.id == ProductCvVersion.cv_id)
            .where(
                ProductCvVersion.id == version_id,
                ProductCvVersion.user_id == current.id,
                ProductCV.status == "active",
            )
        )
        if version is None:
            raise AppError(404, "CV_VERSION_NOT_FOUND", "CV version was not found")
        analysis = CvAnalysis(user_id=current.id, cv_version_id=version.id, status="queued", attempt_number=1)
        self.db.add(analysis)
        self.db.flush()
        from app.services.product_billing import ProductBillingService

        reservation = ProductBillingService(self.db).reserve(current, "cv_analysis", "cv_analysis", analysis.id)
        analysis.credit_reservation_id = reservation.id if reservation else None
        ProductTaskDispatchService(self.db).enqueue("product.cv.analyze", "cv_analysis", analysis.id)
        idempotency.complete(result.record, resource_type="cv_analysis", resource_id=analysis.id, response_status=202)
        self.db.commit()
        self.db.refresh(analysis)
        self._dispatch_analysis(analysis)
        return analysis

    def retry_analysis(self, current: ProductCurrentUser, analysis_id: str, idempotency_key: str) -> CvAnalysis:
        original = self.get_analysis(current, analysis_id)
        idempotency = IdempotencyService(self.db)
        result = idempotency.begin(
            scope="user:" + current.id,
            operation="cv.retry_analysis:" + analysis_id,
            key=idempotency_key,
            request_hash=idempotency.request_hash({"analysis_id": analysis_id}),
        )
        replay = self._replayed_resource(current, result, CvAnalysis, "CV_ANALYSIS_NOT_FOUND")
        if replay is not None:
            return replay
        IdentityService(self.db).require_consent(current.id)
        if original.status != "failed":
            raise AppError(409, "CV_ANALYSIS_NOT_RETRYABLE", "Only failed CV analyses can be retried")
        version = self.db.scalar(
            select(ProductCvVersion)
            .join(ProductCV, ProductCV.id == ProductCvVersion.cv_id)
            .where(ProductCvVersion.id == original.cv_version_id, ProductCV.status == "active")
        )
        if version is None:
            raise AppError(409, "CV_ARCHIVED", "Archived CVs cannot be analyzed")
        attempt = (self.db.scalar(select(func.max(CvAnalysis.attempt_number)).where(
            CvAnalysis.cv_version_id == original.cv_version_id
        )) or 0) + 1
        analysis = CvAnalysis(
            user_id=current.id,
            cv_version_id=version.id,
            parent_analysis_id=original.id,
            attempt_number=attempt,
            status="queued",
        )
        self.db.add(analysis)
        self.db.flush()
        from app.services.product_billing import ProductBillingService

        reservation = ProductBillingService(self.db).reserve(current, "cv_analysis", "cv_analysis", analysis.id)
        analysis.credit_reservation_id = reservation.id if reservation else None
        ProductTaskDispatchService(self.db).enqueue("product.cv.analyze", "cv_analysis", analysis.id)
        idempotency.complete(result.record, resource_type="cv_analysis", resource_id=analysis.id, response_status=202)
        self.db.commit()
        self.db.refresh(analysis)
        self._dispatch_analysis(analysis)
        return analysis

    def _dispatch_analysis(self, analysis: CvAnalysis) -> None:
        ProductTaskDispatchService(self.db).publish_resource("product.cv.analyze", analysis.id)

    def get_analysis(self, current: ProductCurrentUser, analysis_id: str) -> CvAnalysis:
        analysis = self.db.get(CvAnalysis, analysis_id)
        if analysis is None or (current.role != "admin" and analysis.user_id != current.id):
            raise AppError(404, "CV_ANALYSIS_NOT_FOUND", "CV analysis was not found")
        return analysis

    def scan_view(self, scan: CvScan) -> CvScanView:
        draft = self.db.scalar(select(CvDraft.id).where(CvDraft.scan_id == scan.id))
        return CvScanView(
            id=scan.id,
            file_id=scan.file_id,
            cv_id=scan.cv_id,
            parent_scan_id=scan.parent_scan_id,
            attempt_number=scan.attempt_number,
            status=scan.status,
            schema_version=scan.schema_version,
            draft_id=draft,
            error=scan.error,
            created_at=scan.created_at,
            completed_at=scan.completed_at,
        )

    def draft_view(self, draft: CvDraft) -> CvDraftView:
        return CvDraftView(
            id=draft.id,
            scan_id=draft.scan_id,
            revision=draft.revision,
            schema_version=draft.schema_version,
            content=CvContent.model_validate(draft.content),
            field_confidence=draft.field_confidence or {},
            warnings=draft.warnings or [],
            checksum=draft.checksum,
            updated_at=draft.updated_at,
        )

    def version_view(self, version: ProductCvVersion, active_version_id: str | None = None) -> CvVersionView:
        if active_version_id is None:
            active_version_id = self.db.scalar(select(ProductCV.active_version_id).where(ProductCV.id == version.cv_id))
        return CvVersionView(
            id=version.id,
            cv_id=version.cv_id,
            version=version.version,
            schema_version=version.schema_version,
            content=CvContent.model_validate(version.content),
            checksum=version.checksum,
            active=active_version_id == version.id,
            created_at=version.created_at,
        )

    def cv_view(self, cv: ProductCV) -> CvView:
        version = self.db.get(ProductCvVersion, cv.active_version_id) if cv.active_version_id else None
        return CvView(
            id=cv.id,
            title=cv.title,
            status=cv.status,
            active_version=self.version_view(version, cv.active_version_id) if version else None,
            created_at=cv.created_at,
            updated_at=cv.updated_at,
        )

    def analysis_view(self, analysis: CvAnalysis) -> CvAnalysisView:
        return CvAnalysisView(
            id=analysis.id,
            cv_version_id=analysis.cv_version_id,
            parent_analysis_id=analysis.parent_analysis_id,
            attempt_number=analysis.attempt_number,
            status=analysis.status,
            scores=analysis.scores,
            findings=analysis.findings,
            provider=analysis.provider,
            model=analysis.model_name,
            model_configuration_id=analysis.model_configuration_id,
            prompt_version=analysis.prompt_version,
            usage=analysis.usage_json,
            disclaimer=analysis.disclaimer,
            error=analysis.error,
            created_at=analysis.created_at,
            completed_at=analysis.completed_at,
        )

    def _replayed_resource(self, current: ProductCurrentUser, result, model, not_found_code: str):
        if not result.replayed:
            return None
        record = result.record
        if record.status != "completed" or not record.resource_id:
            raise AppError(409, "IDEMPOTENCY_REQUEST_IN_PROGRESS", "The original request has not completed", retryable=True)
        resource = self.db.get(model, record.resource_id)
        if resource is None or (current.role != "admin" and resource.user_id != current.id):
            raise AppError(404, not_found_code, "The idempotent request resource was not found")
        return resource

    def _cv(self, current: ProductCurrentUser, cv_id: str | None) -> ProductCV:
        cv = self.db.get(ProductCV, cv_id) if cv_id else None
        if cv is None or (current.role != "admin" and cv.user_id != current.id):
            raise AppError(404, "CV_NOT_FOUND", "CV was not found")
        return cv

    @staticmethod
    def _default_title(content: dict[str, Any]) -> str:
        name = content.get("basics", {}).get("full_name")
        return ("CV - " + name) if name else "My CV"
