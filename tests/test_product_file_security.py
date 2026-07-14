import hashlib
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.identity_security import ProductCurrentUser
from app.models.db import Base
from app.models.foundation import IdempotencyRecord
from app.models.product_cv import ProductFileAsset
from app.schemas.product_cv import CompleteUploadRequest
from app.services.object_storage import ObjectStat
from app.services.product_files import ProductFileService


class MemoryStorage:
    backend = "local"
    bucket = "test-private"

    def __init__(self, staging_key: str, content: bytes) -> None:
        self.objects = {staging_key: content}

    def stat(self, object_key: str) -> ObjectStat:
        content = self.objects[object_key]
        return ObjectStat(size=len(content), etag="staging-etag", content_type="application/pdf", metadata={})

    def read(self, object_key: str, max_bytes: int) -> bytes:
        return self.objects[object_key][: max_bytes + 1]

    def put_system(self, object_key: str, content: bytes, content_type: str) -> None:
        assert content_type == "application/pdf"
        self.objects[object_key] = content

    def delete(self, object_key: str) -> None:
        self.objects.pop(object_key, None)


@pytest.fixture
def db() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[ProductFileAsset.__table__, IdempotencyRecord.__table__])
    with Session(engine) as session:
        yield session


def test_verified_file_is_promoted_away_from_reusable_upload_key(db: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    content = b"%PDF-1.7\nverified content\n%%EOF"
    checksum = hashlib.sha256(content).hexdigest()
    staging_key = "users/user-1/cv-staging/upload.pdf"
    asset = ProductFileAsset(
        id="file-1",
        user_id="user-1",
        purpose="cv_source",
        original_filename="cv.pdf",
        content_type="application/pdf",
        declared_size_bytes=len(content),
        declared_sha256=checksum,
        bucket="test-private",
        object_key=staging_key,
        storage_backend="local",
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
    )
    db.add(asset)
    db.flush()
    storage = MemoryStorage(staging_key, content)
    current = ProductCurrentUser(
        id="user-1",
        email="candidate@example.com",
        role="student",
        email_verified=True,
        scopes=frozenset(),
        session_id="session-1",
    )
    monkeypatch.setattr("app.services.product_files.IdentityService.require_consent", lambda *_args, **_kwargs: object())

    completed = ProductFileService(db, storage=storage).complete(
        current,
        asset.id,
        CompleteUploadRequest(sha256=checksum),
        "complete-file-1",
    )

    assert completed.object_key != staging_key
    assert "/cv-clean/" in completed.object_key
    assert completed.security_status == "clean"
    assert storage.objects[completed.object_key] == content
    assert staging_key not in storage.objects

    storage.objects[staging_key] = b"%PDF-1.7\nreplaced after scan\n%%EOF"
    _, stored_content = ProductFileService(db, storage=storage).read_owned(current, asset.id)
    assert stored_content == content
