from fastapi import UploadFile
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.models.db import CVRecord
from app.schemas.cv import CVProfile, CVReadResult, CVScanResult
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
    ) -> CVScanResult:
        stored = await self.storage.save_upload(
            upload_file,
            subdir="cvs",
            allowed_extensions=ALLOWED_EXTENSIONS,
            allowed_content_types=ALLOWED_CONTENT_TYPES,
            max_size_bytes=MAX_CV_SIZE_BYTES,
        )

        record = CVRecord(
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

        record.scan_status = "completed"
        record.parsed_profile = profile.model_dump(mode="json")
        record.raw_model_response = profile_payload
        record.warnings = profile.warnings
        self.db.commit()
        self.db.refresh(record)

        return CVScanResult(
            cv_id=record.id,
            status=record.scan_status,
            profile=profile,
            warnings=profile.warnings,
        )

    def get(self, *, cv_id: str) -> CVReadResult:
        record = self.db.get(CVRecord, cv_id)
        if not record:
            raise AppError(
                status_code=404,
                code="CV_NOT_FOUND",
                message="CV was not found.",
                details={"cv_id": cv_id},
            )

        profile = CVProfile.model_validate(record.parsed_profile) if record.parsed_profile else None
        return CVReadResult(
            cv_id=record.id,
            status=record.scan_status,
            original_file_name=record.original_file_name,
            profile=profile,
            warnings=record.warnings or [],
        )
