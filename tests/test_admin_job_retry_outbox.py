from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.identity_security import ProductCurrentUser
from app.models.db import Base, User
from app.models.product_admin_ops import (
    AuditChainHead,
    OperationalJob,
    OperationalJobDispatch,
    PrivilegedAuditEvent,
    PrivilegedCommand,
)
from app.schemas.product_admin_ops import RetryBackgroundJobRequest
from app.services import product_admin_ops
from app.services.product_admin_ops import ProductAdminOpsService


@pytest.fixture
def db() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[
            User.__table__,
            OperationalJob.__table__,
            OperationalJobDispatch.__table__,
            PrivilegedCommand.__table__,
            AuditChainHead.__table__,
            PrivilegedAuditEvent.__table__,
        ],
    )
    with Session(engine) as session:
        yield session


def _current(user_id: str) -> ProductCurrentUser:
    return ProductCurrentUser(
        id=user_id,
        email="operator@example.com",
        role="admin",
        email_verified=True,
        scopes=frozenset({"ops:jobs:write"}),
        session_id="session-1",
    )


def _failed_job(db: Session, user_id: str) -> OperationalJob:
    db.add(User(id=user_id, email="operator@example.com", password_hash="unused", role="admin", is_active=True))
    job = OperationalJob(
        id=str(uuid4()),
        task_name="product.jobs.search",
        queue="celery",
        status="failed",
        attempt=0,
        max_attempts=3,
        resource_type="product.jobs.search",
        resource_id=str(uuid4()),
        args_payload=[str(uuid4())],
        request_id="original-request",
    )
    db.add(job)
    db.commit()
    return job


def test_admin_retry_commits_job_dispatch_command_and_audit_before_publish(db: Session, monkeypatch) -> None:
    user_id = str(uuid4())
    original = _failed_job(db, user_id)
    observed: list[dict] = []

    def send_task(name, *, args, queue, task_id, headers):
        assert db.get(OperationalJob, task_id) is not None
        assert db.scalar(select(OperationalJobDispatch).where(OperationalJobDispatch.job_id == task_id)) is not None
        assert db.scalar(select(PrivilegedCommand).where(PrivilegedCommand.resource_id == task_id)) is not None
        observed.append({"name": name, "args": args, "queue": queue, "task_id": task_id, "headers": headers})
        return SimpleNamespace(id=task_id)

    monkeypatch.setattr(product_admin_ops.celery_app, "send_task", send_task)
    service = ProductAdminOpsService(db)
    retried = service.retry_job(
        _current(user_id),
        original.id,
        RetryBackgroundJobRequest(reason="operator reviewed transient failure"),
        "retry-job-once",
        {"request_id": "admin-request", "ip": "127.0.0.1"},
    )

    assert observed[0]["task_id"] == retried.id
    assert observed[0]["headers"] == {"retry_of": original.id, "request_id": "admin-request"}
    dispatch = db.scalar(select(OperationalJobDispatch).where(OperationalJobDispatch.job_id == retried.id))
    assert dispatch is not None and dispatch.status == "published"
    assert db.scalar(select(PrivilegedAuditEvent).where(PrivilegedAuditEvent.action == "background_job.retry")) is not None

    replayed = service.retry_job(
        _current(user_id),
        original.id,
        RetryBackgroundJobRequest(reason="operator reviewed transient failure"),
        "retry-job-once",
        {"request_id": "admin-request-replay", "ip": "127.0.0.1"},
    )
    assert replayed.id == retried.id
    assert len(observed) == 1


def test_admin_retry_remains_pending_when_broker_publish_fails(db: Session, monkeypatch) -> None:
    user_id = str(uuid4())
    original = _failed_job(db, user_id)
    monkeypatch.setattr(
        product_admin_ops.celery_app,
        "send_task",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("SECRET BROKER URL")),
    )

    retried = ProductAdminOpsService(db).retry_job(
        _current(user_id),
        original.id,
        RetryBackgroundJobRequest(reason="retry after broker outage"),
        "retry-job-fail",
        {"request_id": "admin-request", "ip": "127.0.0.1"},
    )

    dispatch = db.scalar(select(OperationalJobDispatch).where(OperationalJobDispatch.job_id == retried.id))
    assert dispatch is not None
    assert dispatch.status == "pending"
    assert dispatch.last_error == "BACKGROUND_JOB_DISPATCH_FAILED"
