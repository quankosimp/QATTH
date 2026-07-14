from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlparse

from backend.app.core.config import get_settings
from backend.app.core.errors import AppError


@dataclass(frozen=True)
class ObjectStat:
    size: int
    etag: str | None
    metadata: dict[str, str]


class ObjectStorage:
    def __init__(self) -> None:
        settings = get_settings()
        self.backend = os.getenv("STORAGE_BACKEND", str(getattr(settings, "storage_backend", "local")))
        self.bucket = os.getenv("R2_BUCKET", str(getattr(settings, "r2_bucket", "qatth-private")))
        self.local_root = Path(os.getenv("UPLOAD_DIR", str(getattr(settings, "upload_dir", "data/uploads")))) / "product"

    def create_put_url(self, object_key: str, expires_seconds: int) -> str:
        if self.backend == "local":
            return "/v1/files/local-upload/" + object_key
        return self._client().presigned_put_object(self.bucket, object_key, expires=timedelta(seconds=expires_seconds))

    def create_get_url(self, object_key: str, expires_seconds: int) -> str:
        if self.backend == "local":
            return "/v1/files/local-download/" + object_key
        return self._client().presigned_get_object(self.bucket, object_key, expires=timedelta(seconds=expires_seconds))

    def put_local(self, object_key: str, content: bytes) -> None:
        if self.backend != "local":
            raise AppError(404, "LOCAL_UPLOAD_DISABLED", "Local upload endpoint is disabled")
        path = self._local_path(object_key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)

    def stat(self, object_key: str) -> ObjectStat:
        if self.backend == "local":
            path = self._local_path(object_key)
            if not path.is_file():
                raise AppError(409, "UPLOAD_NOT_FOUND", "Uploaded object was not found")
            return ObjectStat(size=path.stat().st_size, etag=None, metadata={})
        try:
            stat = self._client().stat_object(self.bucket, object_key)
        except Exception as exc:
            raise AppError(409, "UPLOAD_NOT_FOUND", "Uploaded object was not found") from exc
        metadata = {str(key).lower(): str(value) for key, value in (stat.metadata or {}).items()}
        return ObjectStat(size=stat.size, etag=stat.etag, metadata=metadata)

    def read(self, object_key: str, max_bytes: int) -> bytes:
        if self.backend == "local":
            content = self._local_path(object_key).read_bytes()
        else:
            response = self._client().get_object(self.bucket, object_key)
            try:
                content = response.read(max_bytes + 1)
            finally:
                response.close()
                response.release_conn()
        if len(content) > max_bytes:
            raise AppError(413, "FILE_TOO_LARGE", "Stored object exceeds its allowed size")
        return content

    def delete(self, object_key: str) -> None:
        if self.backend == "local":
            self._local_path(object_key).unlink(missing_ok=True)
        else:
            self._client().remove_object(self.bucket, object_key)

    def _local_path(self, object_key: str) -> Path:
        path = (self.local_root / object_key).resolve()
        root = self.local_root.resolve()
        if root not in path.parents:
            raise AppError(400, "INVALID_OBJECT_KEY", "Invalid object key")
        return path

    def _client(self):
        from minio import Minio

        endpoint = os.getenv("R2_ENDPOINT", "")
        parsed = urlparse(endpoint if "://" in endpoint else "https://" + endpoint)
        access_key = os.getenv("R2_ACCESS_KEY_ID", "")
        secret_key = os.getenv("R2_SECRET_ACCESS_KEY", "")
        if not parsed.hostname or not access_key or not secret_key or not self.bucket:
            raise AppError(500, "STORAGE_CONFIGURATION_INVALID", "R2 storage is not fully configured")
        host = parsed.hostname + ((":" + str(parsed.port)) if parsed.port else "")
        return Minio(host, access_key=access_key, secret_key=secret_key, secure=parsed.scheme == "https")
