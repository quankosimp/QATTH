from datetime import UTC, datetime
import re
from uuid import uuid4

import structlog
from celery import Celery, signals
from structlog.contextvars import bind_contextvars, clear_contextvars, get_contextvars

from app.core.config import get_settings

settings = get_settings()

celery_app = Celery(
    "qatth",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=["app.workers.tasks"],
)

celery_app.conf.update(
    task_track_started=True,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    worker_prefetch_multiplier=1,
    task_acks_late=True,
    beat_schedule={
        "publish-job-search-dispatches": {"task": "product.jobs.publish_dispatches", "schedule": 30.0},
        "publish-recommendation-dispatches": {"task": "product.recommendations.publish_dispatches", "schedule": 30.0},
        "publish-privacy-dispatches": {"task": "product.privacy.publish_dispatches", "schedule": 30.0},
        "publish-product-task-dispatches": {"task": "product.tasks.publish_dispatches", "schedule": 30.0},
        "publish-operational-job-retries": {"task": "product.ops.publish_retries", "schedule": 30.0},
        "recover-product-task-leases": {"task": "product.tasks.recover_stalled", "schedule": 60.0},
        "reconcile-credit-reservations": {"task": "product.billing.reconcile_reservations", "schedule": 300.0},
        "reconcile-payment-provider": {"task": "product.billing.reconcile_payments", "schedule": 900.0},
        "cleanup-payment-payloads": {"task": "product.billing.cleanup_payment_payloads", "schedule": 3600.0},
        "expire-timed-out-interviews": {"task": "product.interview.expire_timed_out", "schedule": 60.0},
        "mark-stale-jobs": {"task": "product.jobs.mark_stale", "schedule": 3600.0},
        "cleanup-privacy-artifacts": {"task": "product.privacy.cleanup_artifacts", "schedule": 3600.0},
    },
)

logger = structlog.get_logger(__name__)
_UUID_PATTERN = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$")


def _safe_args(body) -> list[str]:
    args = body[0] if isinstance(body, (list, tuple)) and body else []
    return [str(value) if _UUID_PATTERN.fullmatch(str(value)) else "<redacted>" for value in args if isinstance(value, (str, int))][:8]


@signals.before_task_publish.connect
def register_operational_job(sender=None, body=None, headers=None, routing_key=None, **kwargs):
    headers = headers or {}
    task_id = str(headers.get("id") or "")
    if not task_id:
        return
    try:
        from app.core.db import SessionLocal
        from app.models.product_admin_ops import OperationalJob

        args = _safe_args(body)
        context = get_contextvars()
        request_id = str(headers.get("request_id") or context.get("request_id") or uuid4())
        headers["request_id"] = request_id
        with SessionLocal() as db:
            if db.get(OperationalJob, task_id) is not None:
                return
            parent = db.get(OperationalJob, headers.get("retry_of")) if headers.get("retry_of") else None
            db.add(OperationalJob(id=task_id, task_name=str(sender or headers.get("task") or "unknown"), queue=str(routing_key or "celery"), status="queued", attempt=(parent.attempt + 1) if parent else 0, max_attempts=parent.max_attempts if parent else 3, resource_type=str(sender or headers.get("task") or "task"), resource_id=args[0] if args else None, args_payload=args, request_id=request_id, parent_job_id=parent.id if parent else None))
            db.commit()
    except Exception as exc:
        logger.error("operational_job_publish_tracking_failed", task_id=task_id, error_code="OPERATIONAL_JOB_TRACKING_FAILED", error_type=type(exc).__name__)


@signals.task_prerun.connect
def mark_operational_job_running(task_id=None, task=None, args=None, **kwargs):
    clear_contextvars()
    request_headers = getattr(getattr(task, "request", None), "headers", None) or {}
    request_id = str(request_headers.get("request_id") or uuid4())
    safe_args = [str(value) if _UUID_PATTERN.fullmatch(str(value)) else "<redacted>" for value in (args or []) if isinstance(value, (str, int))][:8]
    bind_contextvars(
        request_id=request_id,
        task_id=str(task_id),
        task_name=getattr(task, "name", "unknown"),
        resource_id=safe_args[0] if safe_args else None,
    )
    try:
        from app.core.db import SessionLocal
        from app.models.product_admin_ops import OperationalJob

        with SessionLocal() as db:
            job = db.get(OperationalJob, str(task_id))
            if job is None:
                job = OperationalJob(id=str(task_id), task_name=task.name, status="running", resource_type=task.name, resource_id=safe_args[0] if safe_args else None, args_payload=safe_args)
                db.add(job)
            job.status = "running"
            job.started_at = job.started_at or datetime.now(UTC)
            db.commit()
    except Exception as exc:
        logger.error("operational_job_start_tracking_failed", task_id=str(task_id), error_code="OPERATIONAL_JOB_TRACKING_FAILED", error_type=type(exc).__name__)


@signals.task_postrun.connect
def mark_operational_job_finished(task_id=None, retval=None, state=None, **kwargs):
    try:
        from app.core.db import SessionLocal
        from app.models.product_admin_ops import OperationalJob

        with SessionLocal() as db:
            job = db.get(OperationalJob, str(task_id))
            if job is None:
                return
            if state == "SUCCESS":
                job.status = "succeeded"
            elif job.status != "dead_letter":
                job.status = "failed"
            job.finished_at = datetime.now(UTC)
            if isinstance(retval, dict):
                job.result_summary = {key: value for key, value in retval.items() if key in {"status", "run_id", "request_id", "analysis_id", "report_id"}}
            db.commit()
    except Exception as exc:
        logger.error("operational_job_finish_tracking_failed", task_id=str(task_id), error_code="OPERATIONAL_JOB_TRACKING_FAILED", error_type=type(exc).__name__)
    finally:
        clear_contextvars()


@signals.task_failure.connect
def mark_operational_job_failed(task_id=None, exception=None, **kwargs):
    try:
        from app.core.db import SessionLocal
        from app.models.product_admin_ops import OperationalJob

        with SessionLocal() as db:
            job = db.get(OperationalJob, str(task_id))
            if job is None:
                return
            job.status = "dead_letter" if job.attempt >= job.max_attempts else "failed"
            job.error_code = type(exception).__name__.upper()[:120] if exception else "TASK_FAILED"
            job.error_message = "Task failed; use the request ID and structured logs for investigation."
            job.finished_at = datetime.now(UTC)
            db.commit()
    except Exception as exc:
        logger.error("operational_job_failure_tracking_failed", task_id=str(task_id), error_code="OPERATIONAL_JOB_TRACKING_FAILED", error_type=type(exc).__name__)
