from fastapi import UploadFile
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.core.security import CurrentUser
from app.models.db import CVRecord, CVVersion
from app.schemas.cv import (
    CVListResult,
    CVProfile,
    CVReadResult,
    CVSaveResult,
    CVScanResult,
    CVSummary,
    CVVersionListResult,
    CVVersionRead,
)
from app.services.gemini import GeminiService
from app.services.files import FileAssetService
from app.services.model_runs import ModelRunService
from app.services.storage import LocalStorage

ALLOWED_EXTENSIONS = {".pdf", ".docx"}
ALLOWED_CONTENT_TYPES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}
MAX_CV_SIZE_BYTES = 15 * 1024 * 1024


class CVScanService:
    def __init__(
        self,
        *,
        db: Session,
        storage: LocalStorage | None = None,
        gemini: GeminiService | None = None,
    ) -> None:
        self.db = db
        self.storage = storage or LocalStorage()
        self.gemini = gemini or GeminiService()

    async def scan(
        self,
        *,
        upload_file: UploadFile,
        target_role: str | None,
        language: str,
        current_user: CurrentUser,
    ) -> CVScanResult:
        stored = await self.storage.save_upload(
            upload_file,
            subdir="cvs",
            allowed_extensions=ALLOWED_EXTENSIONS,
            allowed_content_types=ALLOWED_CONTENT_TYPES,
            max_size_bytes=MAX_CV_SIZE_BYTES,
        )

        record = CVRecord(
            user_id=current_user.id,
            original_file_name=stored.original_name,
            content_type=stored.content_type,
            file_path=str(stored.path),
            scan_status="processing",
        )
        self.db.add(record)
        self.db.commit()
        self.db.refresh(record)

        model_timer = ModelRunService(db=self.db).start(
            user_id=current_user.id,
            run_type="cv_scan",
            provider="gemini",
            model=self.gemini.settings.gemini_cv_model,
            input_payload={
                "cv_id": record.id,
                "file_name": stored.original_name,
                "content_type": stored.content_type,
                "target_role": target_role,
                "language": language,
            },
            output_schema="CVProfile",
        )

        try:
            profile_payload = await self.gemini.extract_cv_profile(
                file_path=stored.path,
                mime_type=stored.content_type,
                response_schema=CVProfile,
                target_role=target_role,
                language=language,
            )
            profile = CVProfile.model_validate(profile_payload)
            model_timer.complete(output_json=profile.model_dump(mode="json"))
        except AppError as exc:
            model_timer.fail(error=exc.message)
            record.scan_status = "failed"
            record.failure_reason = exc.message
            self.db.commit()
            raise
        except Exception as exc:
            model_timer.fail(error=str(exc))
            record.scan_status = "failed"
            record.failure_reason = str(exc)
            self.db.commit()
            raise AppError(
                status_code=502,
                code="CV_SCAN_FAILED",
                message="Could not scan the uploaded CV.",
                details={"reason": str(exc)},
            ) from exc

        record.scan_status = "pending_review"
        record.parsed_profile = None
        record.raw_model_response = profile_payload
        record.warnings = profile.warnings
        FileAssetService(db=self.db, current_user=current_user).create_asset(
            user_id=current_user.id,
            owner_type="cv",
            owner_id=record.id,
            original_file_name=stored.original_name,
            content_type=stored.content_type,
            size_bytes=stored.size_bytes,
            storage_backend=stored.storage_backend,
            storage_key=stored.storage_key,
            local_path=str(stored.path),
        )
        self._create_version(
            cv_id=record.id,
            user_id=current_user.id,
            profile=profile,
            status="draft",
            source="llm_scan",
            edit_note="Initial LLM scan draft.",
        )
        self.db.commit()
        self.db.refresh(record)

        return CVScanResult(
            cv_id=record.id,
            status=record.scan_status,
            draft_profile=profile,
            warnings=profile.warnings,
        )

    def save_profile(
        self,
        *,
        cv_id: str,
        profile: CVProfile,
        current_user: CurrentUser,
        edit_note: str | None = None,
    ) -> CVSaveResult:
        record = self.db.get(CVRecord, cv_id)
        self._ensure_cv_access(record=record, cv_id=cv_id, current_user=current_user)

        if record.scan_status == "failed":
            raise AppError(
                status_code=409,
                code="CV_SCAN_FAILED",
                message="Cannot save a profile for a failed CV scan.",
                details={"failure_reason": record.failure_reason},
            )

        record.scan_status = "completed"
        record.parsed_profile = profile.model_dump(mode="json")
        record.warnings = profile.warnings
        version = self._create_version(
            cv_id=record.id,
            user_id=record.user_id,
            profile=profile,
            status="final",
            source="user_review",
            edit_note=edit_note,
        )
        self.db.commit()
        self.db.refresh(record)
        self.db.refresh(version)

        return CVSaveResult(
            cv_id=record.id,
            status=record.scan_status,
            version_id=version.id,
            version_number=version.version_number,
            profile=profile,
            warnings=profile.warnings,
        )

    def list(self, *, current_user: CurrentUser) -> CVListResult:
        statement = select(CVRecord)
        if not current_user.is_admin:
            statement = statement.where(CVRecord.user_id == current_user.id)

        records = list(self.db.scalars(statement.order_by(CVRecord.created_at.desc())).all())
        items = []
        for record in records:
            latest_version_number = self._latest_version_number(cv_id=record.id)
            profile = CVProfile.model_validate(record.parsed_profile) if record.parsed_profile else None
            items.append(
                CVSummary(
                    cv_id=record.id,
                    status=record.scan_status,
                    original_file_name=record.original_file_name,
                    latest_version_number=latest_version_number,
                    active_profile_name=profile.name if profile else None,
                )
            )
        return CVListResult(items=items, total=len(items))

    def get(self, *, cv_id: str, current_user: CurrentUser) -> CVReadResult:
        record = self.db.get(CVRecord, cv_id)
        self._ensure_cv_access(record=record, cv_id=cv_id, current_user=current_user)

        draft_profile = (
            CVProfile.model_validate(record.raw_model_response) if record.raw_model_response else None
        )
        profile = CVProfile.model_validate(record.parsed_profile) if record.parsed_profile else None
        return CVReadResult(
            cv_id=record.id,
            status=record.scan_status,
            original_file_name=record.original_file_name,
            latest_version_number=self._latest_version_number(cv_id=record.id),
            draft_profile=draft_profile,
            profile=profile,
            warnings=record.warnings or [],
        )

    def list_versions(self, *, cv_id: str, current_user: CurrentUser) -> CVVersionListResult:
        record = self.db.get(CVRecord, cv_id)
        self._ensure_cv_access(record=record, cv_id=cv_id, current_user=current_user)
        versions = list(
            self.db.scalars(
                select(CVVersion)
                .where(CVVersion.cv_id == cv_id)
                .order_by(CVVersion.version_number.desc())
            ).all()
        )
        items = [
            CVVersionRead(
                version_id=version.id,
                cv_id=version.cv_id,
                version_number=version.version_number,
                status=version.status,
                source=version.source,
                profile=CVProfile.model_validate(version.profile_json),
                edit_note=version.edit_note,
            )
            for version in versions
        ]
        return CVVersionListResult(items=items, total=len(items))

    def _create_version(
        self,
        *,
        cv_id: str,
        user_id: str | None,
        profile: CVProfile,
        status: str,
        source: str,
        edit_note: str | None,
    ) -> CVVersion:
        version_number = (self._latest_version_number(cv_id=cv_id) or 0) + 1
        version = CVVersion(
            cv_id=cv_id,
            user_id=user_id,
            version_number=version_number,
            status=status,
            source=source,
            profile_json=profile.model_dump(mode="json"),
            edit_note=edit_note,
        )
        self.db.add(version)
        return version

    def _latest_version_number(self, *, cv_id: str) -> int | None:
        return self.db.scalar(select(func.max(CVVersion.version_number)).where(CVVersion.cv_id == cv_id))

    def _ensure_cv_access(
        self,
        *,
        record: CVRecord | None,
        cv_id: str,
        current_user: CurrentUser,
    ) -> None:
        if not record:
            raise AppError(
                status_code=404,
                code="CV_NOT_FOUND",
                message="CV was not found.",
                details={"cv_id": cv_id},
            )
        if not current_user.is_admin and record.user_id not in {None, current_user.id}:
            raise AppError(
                status_code=404,
                code="CV_NOT_FOUND",
                message="CV was not found.",
                details={"cv_id": cv_id},
            )
