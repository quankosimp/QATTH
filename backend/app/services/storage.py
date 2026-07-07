from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from fastapi import UploadFile

from app.core.config import Settings, get_settings
from app.core.errors import AppError


@dataclass(frozen=True)
class StoredFile:
    original_name: str
    content_type: str
    path: Path
    size_bytes: int


class LocalStorage:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    async def save_upload(
        self,
        upload_file: UploadFile,
        *,
        subdir: str,
        allowed_extensions: set[str],
        allowed_content_types: set[str],
        max_size_bytes: int,
    ) -> StoredFile:
        original_name = upload_file.filename or "uploaded-file"
        extension = Path(original_name).suffix.lower()
        content_type = upload_file.content_type or "application/octet-stream"

        if extension not in allowed_extensions:
            raise AppError(
                status_code=422,
                code="UNSUPPORTED_FILE_EXTENSION",
                message=f"Unsupported file extension: {extension or '(none)'}",
                details={"allowed_extensions": sorted(allowed_extensions)},
            )

        if content_type not in allowed_content_types:
            raise AppError(
                status_code=422,
                code="UNSUPPORTED_CONTENT_TYPE",
                message=f"Unsupported content type: {content_type}",
                details={"allowed_content_types": sorted(allowed_content_types)},
            )

        content = await upload_file.read()
        if len(content) > max_size_bytes:
            raise AppError(
                status_code=413,
                code="FILE_TOO_LARGE",
                message="Uploaded file is too large.",
                details={"max_size_bytes": max_size_bytes},
            )

        target_dir = self.settings.upload_dir / subdir
        target_dir.mkdir(parents=True, exist_ok=True)
        safe_name = f"{uuid4()}{extension}"
        path = target_dir / safe_name
        path.write_bytes(content)

        return StoredFile(
            original_name=original_name,
            content_type=content_type,
            path=path,
            size_bytes=len(content),
        )
