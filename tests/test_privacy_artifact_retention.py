from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.models.db import Base
from app.models.product_privacy import PrivacyArtifact, PrivacyEvent
from app.services.product_privacy import ProductPrivacyService


class RetentionStorage:
    def __init__(self) -> None:
        self.fail = {"failed-object"}
        self.deleted: list[str] = []

    def delete(self, object_key: str) -> None:
        if object_key in self.fail:
            raise RuntimeError("SECRET STORAGE ENDPOINT")
        self.deleted.append(object_key)


@pytest.fixture
def db() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[PrivacyArtifact.__table__, PrivacyEvent.__table__])
    with Session(engine) as session:
        yield session


def _artifact(request_id: str, object_key: str) -> PrivacyArtifact:
    return PrivacyArtifact(
        request_id=request_id,
        user_id="user-1",
        object_key=object_key,
        content_type="application/zip",
        size_bytes=100,
        sha256="a" * 64,
        encryption_version="aes-256-gcm-v1",
        expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
    )


def test_retention_cleanup_is_per_artifact_audited_and_retryable(db: Session) -> None:
    completed = _artifact("request-completed", "completed-object")
    failed = _artifact("request-failed", "failed-object")
    db.add_all([completed, failed])
    db.commit()
    storage = RetentionStorage()
    service = ProductPrivacyService.__new__(ProductPrivacyService)
    service.db = db
    service.storage = storage

    first = service.cleanup_expired_artifacts()

    assert first == {"artifacts_deleted": 1, "artifacts_failed": 1}
    assert completed.deleted_at is not None
    assert failed.deleted_at is None
    events = list(db.scalars(select(PrivacyEvent).order_by(PrivacyEvent.request_id)))
    assert {(event.request_id, event.event_type) for event in events} == {
        ("request-completed", "artifact.cleaned_up"),
        ("request-failed", "artifact.cleanup_failed"),
    }
    assert "SECRET STORAGE ENDPOINT" not in repr([event.payload for event in events])

    storage.fail.clear()
    second = service.cleanup_expired_artifacts()

    assert second == {"artifacts_deleted": 1, "artifacts_failed": 0}
    assert failed.deleted_at is not None
    failed_events = list(db.scalars(select(PrivacyEvent).where(PrivacyEvent.request_id == "request-failed").order_by(PrivacyEvent.sequence)))
    assert [event.event_type for event in failed_events] == ["artifact.cleanup_failed", "artifact.cleaned_up"]
