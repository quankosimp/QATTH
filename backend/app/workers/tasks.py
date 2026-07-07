from datetime import UTC, datetime

from app.core.celery_app import celery_app
from app.core.db import SessionLocal
from app.models.db import BackgroundTask


@celery_app.task(name="tasks.noop")
def noop_task(background_task_id: str) -> dict:
    db = SessionLocal()
    try:
        task = db.get(BackgroundTask, background_task_id)
        if not task:
            return {"status": "missing", "task_id": background_task_id}

        task.status = "completed"
        task.started_at = task.started_at or datetime.now(UTC)
        task.completed_at = datetime.now(UTC)
        task.result_payload = {"message": "No-op task completed."}
        db.commit()
        return {"status": "completed", "task_id": background_task_id}
    finally:
        db.close()
