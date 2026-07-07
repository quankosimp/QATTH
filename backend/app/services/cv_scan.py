from fastapi import UploadFile
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.core.security import CurrentUser
from app.models.db import CVRecord
from app.schemas.cv import CVProfile, CVReadResult, CVSaveResult, CVScanResult
from app.services.gemini import GeminiService
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

        try:
            profile_payload = await self.gemini.extract_cv_profile(
                file_path=stored.path,
                mime_type=stored.content_type,
                response_schema=CVProfile,
                target_role=target_role,
                language=language,
            )
            profile = CVProfile.model_validate(profile_payload)
        except AppError as exc:
            record.scan_status = "failed"
            record.failure_reason = exc.message
            self.db.commit()
            raise
        except Exception as exc:
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
        self.db.commit()
        self.db.refresh(record)

        return CVSaveResult(
            cv_id=record.id,
            status=record.scan_status,
            profile=profile,
            warnings=profile.warnings,
        )

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
            draft_profile=draft_profile,
            profile=profile,
            warnings=record.warnings or [],
        )

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
