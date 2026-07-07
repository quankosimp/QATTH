from datetime import datetime

from pydantic import BaseModel


class FileAssetRead(BaseModel):
    file_id: str
    owner_type: str | None = None
    owner_id: str | None = None
    original_file_name: str
    content_type: str
    size_bytes: int
    storage_backend: str
    created_at: datetime | None = None


class SignedUrlResult(BaseModel):
    file_id: str
    url: str
    expires_seconds: int
    storage_backend: str
