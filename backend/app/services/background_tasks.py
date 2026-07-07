from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.core.security import CurrentUser
from app.models.db import BackgroundTask
from app.schemas.tasks import BackgroundTaskCreate, BackgroundTaskList, BackgroundTaskRead
from app.workers.tasks import noop_task


class BackgroundTaskService:
    def __init__(self, *, db: Session, current_user: CurrentUser | None = None) -> None:
        self.db = db
        self.current_user = current_user

    def enqueue(self, payload: BackgroundTaskCreate) -> BackgroundTaskRead:
        if payload.task_type != "noop":
            raise AppError(
                status_code=422,
                code="UNSUPPORTED_TASK_TYPE",
                message="This task type is not wired to a worker yet.",
                details={"supported_task_types": ["noop"]},
            )

        record = BackgroundTask(
            user_id=self.current_user.id if self.current_user else None,
            task_type=payload.task_type,
            status="queued",
            resource_type=payload.resource_type,
            resource_id=payload.resource_id,
            payload=payload.payload,
            attempts=1,
        )
        self.db.add(record)
        self.db.commit()
        self.db.refresh(record)

        celery_result = noop_task.delay(record.id)
        record.celery_task_id = celery_result.id
        self.db.commit()
        self.db.refresh(record)
        return self._to_read(record)

    def list(self) -> BackgroundTaskList:
        statement = select(BackgroundTask).order_by(BackgroundTask.created_at.desc())
        if self.current_user and not self.current_user.is_admin:
            statement = statement.where(BackgroundTask.user_id == self.current_user.id)
        tasks = list(self.db.scalars(statement).all())
        return BackgroundTaskList(items=[self._to_read(task) for task in tasks], total=len(tasks))

    def get(self, *, task_id: str) -> BackgroundTaskRead:
        task = self.db.get(BackgroundTask, task_id)
        self._ensure_access(task=task, task_id=task_id)
        return self._to_read(task)

    def retry(self, *, task_id: str) -> BackgroundTaskRead:
        task = self.db.get(BackgroundTask, task_id)
        self._ensure_access(task=task, task_id=task_id)
        if task.status not in {"failed", "completed"}:
            raise AppError(
                status_code=409,
                code="TASK_NOT_RETRYABLE",
                message="Only failed or completed tasks can be retried manually.",
                details={"status": task.status},
            )
        if task.attempts >= task.max_attempts:
            raise AppError(
                status_code=409,
                code="TASK_MAX_ATTEMPTS_REACHED",
                message="Task has reached max attempts.",
            )
        task.status = "queued"
        task.attempts += 1
        task.started_at = None
        task.completed_at = None
        task.error_payload = None
        task.result_payload = None
        task.updated_at = datetime.now(UTC)
        self.db.commit()
        celery_result = noop_task.delay(task.id)
        task.celery_task_id = celery_result.id
        self.db.commit()
        self.db.refresh(task)
        return self._to_read(task)

    def _ensure_access(self, *, task: BackgroundTask | None, task_id: str) -> None:
        if not task:
            raise AppError(
                status_code=404,
                code="TASK_NOT_FOUND",
                message="Background task was not found.",
                details={"task_id": task_id},
            )
        if self.current_user and not self.current_user.is_admin and task.user_id != self.current_user.id:
            raise AppError(
                status_code=404,
                code="TASK_NOT_FOUND",
                message="Background task was not found.",
                details={"task_id": task_id},
            )

    def _to_read(self, task: BackgroundTask) -> BackgroundTaskRead:
        return BackgroundTaskRead(
            task_id=task.id,
            celery_task_id=task.celery_task_id,
            user_id=task.user_id,
            task_type=task.task_type,
            status=task.status,
            resource_type=task.resource_type,
            resource_id=task.resource_id,
            attempts=task.attempts,
            max_attempts=task.max_attempts,
            result_payload=task.result_payload,
            error_payload=task.error_payload,
            created_at=task.created_at,
            started_at=task.started_at,
            completed_at=task.completed_at,
        )
