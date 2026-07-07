from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.core.security import CurrentUser
from app.models.db import FileAsset
from app.schemas.files import FileAssetRead, SignedUrlResult
from app.services.storage import LocalStorage


class FileAssetService:
    def __init__(self, *, db: Session, current_user: CurrentUser) -> None:
        self.db = db
        self.current_user = current_user

    def create_asset(
        self,
        *,
        user_id: str | None,
        owner_type: str | None,
        owner_id: str | None,
        original_file_name: str,
        content_type: str,
        size_bytes: int,
        storage_backend: str,
        storage_key: str,
        local_path: str | None,
    ) -> FileAsset:
        asset = FileAsset(
            user_id=user_id,
            owner_type=owner_type,
            owner_id=owner_id,
            original_file_name=original_file_name,
            content_type=content_type,
            size_bytes=size_bytes,
            storage_backend=storage_backend,
            storage_key=storage_key,
            local_path=local_path,
        )
        self.db.add(asset)
        return asset

    def get(self, *, file_id: str) -> FileAssetRead:
        asset = self._get_asset(file_id=file_id)
        return self._to_read(asset)

    def signed_url(self, *, file_id: str, expires_seconds: int) -> SignedUrlResult:
        asset = self._get_asset(file_id=file_id)
        url = LocalStorage().build_presigned_get_url(
            storage_key=asset.storage_key,
            expires_seconds=expires_seconds,
        )
        return SignedUrlResult(
            file_id=asset.id,
            url=url,
            expires_seconds=expires_seconds,
            storage_backend=asset.storage_backend,
        )

    def _get_asset(self, *, file_id: str) -> FileAsset:
        asset = self.db.get(FileAsset, file_id)
        if not asset:
            raise AppError(status_code=404, code="FILE_NOT_FOUND", message="File was not found.")
        if not self.current_user.is_admin and asset.user_id not in {None, self.current_user.id}:
            raise AppError(status_code=404, code="FILE_NOT_FOUND", message="File was not found.")
        return asset

    def _to_read(self, asset: FileAsset) -> FileAssetRead:
        return FileAssetRead(
            file_id=asset.id,
            owner_type=asset.owner_type,
            owner_id=asset.owner_id,
            original_file_name=asset.original_file_name,
            content_type=asset.content_type,
            size_bytes=asset.size_bytes,
            storage_backend=asset.storage_backend,
            created_at=asset.created_at,
        )
