from __future__ import annotations

import hashlib
import os
import socket
import struct
from datetime import datetime, timedelta, timezone
from pathlib import PurePath
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.core.config import get_settings
from backend.app.core.errors import AppError
from backend.app.core.identity_security import ProductCurrentUser
from backend.app.models.product_cv import ProductFileAsset
from backend.app.schemas.product_cv import CompleteUploadRequest, CreateUploadIntentRequest, UploadIntentView
from backend.app.services.object_storage import ObjectStorage


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ProductFileService:
    def __init__(self, db: Session, storage: ObjectStorage | None = None) -> None:
        self.db = db
        self.storage = storage or ObjectStorage()

    def create_intent(self, current: ProductCurrentUser, payload: CreateUploadIntentRequest) -> UploadIntentView:
        existing = self.db.scalar(
            select(ProductFileAsset).where(
                ProductFileAsset.user_id == current.id,
                ProductFileAsset.declared_sha256 == payload.sha256.lower(),
                ProductFileAsset.upload_status == "pending",
                ProductFileAsset.expires_at > _utcnow(),
            )
        )
        if existing is None:
            expires_at = _utcnow() + timedelta(minutes=15)
            safe_name = PurePath(payload.filename).name
            asset = ProductFileAsset(
                user_id=current.id,
                purpose=payload.purpose,
                original_filename=safe_name,
                content_type=payload.content_type,
                declared_size_bytes=payload.size_bytes,
                declared_sha256=payload.sha256.lower(),
                bucket=self.storage.bucket,
                object_key="users/" + current.id + "/cv-source/" + str(uuid4()) + ".pdf",
                storage_backend=self.storage.backend,
                expires_at=expires_at,
            )
            self.db.add(asset)
            self.db.commit()
            self.db.refresh(asset)
        else:
            asset = existing
        upload_url = self.storage.create_put_url(asset.object_key, max(60, int((asset.expires_at - _utcnow()).total_seconds())))
        return UploadIntentView(
            file=asset,
            upload_url=upload_url,
            required_headers={
                "Content-Type": asset.content_type,
                "x-amz-meta-sha256": asset.declared_sha256,
            },
            expires_at=asset.expires_at,
        )

    def put_local(self, object_key: str, content: bytes, content_type: str | None) -> None:
        asset = self.db.scalar(select(ProductFileAsset).where(ProductFileAsset.object_key == object_key))
        if asset is None or asset.upload_status != "pending" or asset.expires_at <= _utcnow():
            raise AppError(404, "UPLOAD_INTENT_NOT_FOUND", "Upload intent was not found")
        if content_type != asset.content_type:
            raise AppError(422, "CONTENT_TYPE_MISMATCH", "Uploaded content type does not match intent")
        if len(content) > asset.declared_size_bytes:
            raise AppError(413, "FILE_TOO_LARGE", "Uploaded object exceeds declared size")
        self.storage.put_local(object_key, content)

    def complete(self, current: ProductCurrentUser, file_id: str, payload: CompleteUploadRequest) -> ProductFileAsset:
        asset = self._owned(current, file_id)
        if asset.upload_status == "uploaded" and asset.verified_sha256 == payload.sha256.lower():
            return asset
        if asset.upload_status != "pending" or asset.expires_at <= _utcnow():
            raise AppError(409, "UPLOAD_NOT_COMPLETABLE", "Upload intent is no longer completable")
        if payload.sha256.lower() != asset.declared_sha256:
            raise AppError(422, "CHECKSUM_MISMATCH", "Completion checksum differs from upload intent")
        stat = self.storage.stat(asset.object_key)
        if stat.size != asset.declared_size_bytes:
            return self._reject(asset, "Uploaded size differs from declared size")
        content = self.storage.read(asset.object_key, asset.declared_size_bytes)
        actual_sha256 = hashlib.sha256(content).hexdigest()
        if actual_sha256 != asset.declared_sha256:
            return self._reject(asset, "Uploaded checksum differs from declared checksum")
        self._validate_pdf(content)
        self._scan_malware(content)
        asset.actual_size_bytes = len(content)
        asset.verified_sha256 = actual_sha256
        asset.provider_etag = payload.provider_etag or stat.etag
        asset.upload_status = "uploaded"
        asset.security_status = "clean"
        asset.uploaded_at = _utcnow()
        self.db.commit()
        self.db.refresh(asset)
        return asset

    def download_url(self, current: ProductCurrentUser, file_id: str, expires_seconds: int = 300) -> tuple[str, datetime]:
        asset = self._owned(current, file_id)
        if asset.upload_status != "uploaded" or asset.security_status != "clean":
            raise AppError(409, "FILE_NOT_AVAILABLE", "File is not available for download")
        expires_at = _utcnow() + timedelta(seconds=expires_seconds)
        return self.storage.create_get_url(asset.object_key, expires_seconds), expires_at

    def read_owned(self, current: ProductCurrentUser, file_id: str) -> tuple[ProductFileAsset, bytes]:
        asset = self._owned(current, file_id)
        if asset.upload_status != "uploaded" or asset.security_status != "clean":
            raise AppError(409, "FILE_NOT_READY", "File upload has not passed security checks")
        return asset, self.storage.read(asset.object_key, asset.declared_size_bytes)

    def _owned(self, current: ProductCurrentUser, file_id: str) -> ProductFileAsset:
        asset = self.db.get(ProductFileAsset, file_id)
        if asset is None or (current.role != "admin" and asset.user_id != current.id):
            raise AppError(404, "FILE_NOT_FOUND", "File was not found")
        return asset

    def _reject(self, asset: ProductFileAsset, reason: str):
        asset.upload_status = "rejected"
        asset.security_status = "quarantined"
        asset.rejection_reason = reason
        self.db.commit()
        raise AppError(422, "FILE_REJECTED", reason)

    @staticmethod
    def _validate_pdf(content: bytes) -> None:
        if not content.startswith(b"%PDF-") or b"%%EOF" not in content[-8192:]:
            raise AppError(422, "INVALID_PDF", "Uploaded file is not a structurally valid PDF")
        if b"/JavaScript" in content or b"/Launch" in content or b"/EmbeddedFile" in content:
            raise AppError(422, "UNSAFE_PDF", "PDF contains unsupported active or embedded content")

    @staticmethod
    def _scan_malware(content: bytes) -> None:
        host = os.getenv("CLAMAV_HOST", "")
        environment = str(getattr(get_settings(), "app_env", "local")).lower()
        if not host:
            if environment not in {"local", "development", "test"}:
                raise AppError(503, "MALWARE_SCANNER_UNAVAILABLE", "Malware scanner is required", retryable=True)
            return
        port = int(os.getenv("CLAMAV_PORT", "3310"))
        try:
            with socket.create_connection((host, port), timeout=10) as client:
                client.sendall(b"zINSTREAM\0")
                for offset in range(0, len(content), 65536):
                    chunk = content[offset : offset + 65536]
                    client.sendall(struct.pack(">I", len(chunk)) + chunk)
                client.sendall(struct.pack(">I", 0))
                result = client.recv(4096).decode("utf-8", "replace")
        except OSError as exc:
            raise AppError(503, "MALWARE_SCANNER_UNAVAILABLE", "Malware scanner is unavailable", retryable=True) from exc
        if "FOUND" in result:
            raise AppError(422, "MALWARE_DETECTED", "Uploaded file failed security scanning")
        if "OK" not in result:
            raise AppError(503, "MALWARE_SCANNER_ERROR", "Malware scan did not complete", retryable=True)
