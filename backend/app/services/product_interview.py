from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.core.identity_security import ProductCurrentUser
from app.models.product_cv import ProductCvVersion
from app.models.product_interview import (
    InterviewFeedback,
    InterviewRealtimeToken,
    ProductInterview,
    ProductInterviewEvent,
    ProductInterviewReport,
)
from app.schemas.product_interview import (
    CreateInterviewRequest,
    EvidenceFinding,
    InterviewFeedbackRequest,
    InterviewPage,
    InterviewReportView,
    InterviewView,
    RealtimeTokenView,
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _encode_cursor(created_at: datetime, item_id: str) -> str:
    return base64.urlsafe_b64encode((created_at.isoformat() + "|" + item_id).encode()).decode().rstrip("=")


def _decode_cursor(value: str) -> tuple[datetime, str]:
    try:
        decoded = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4)).decode()
        timestamp, item_id = decoded.rsplit("|", 1)
        return datetime.fromisoformat(timestamp), item_id
    except (ValueError, UnicodeDecodeError) as exc:
        raise AppError(422, "INVALID_CURSOR", "Cursor is invalid") from exc


class ProductInterviewService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def create(self, current: ProductCurrentUser, payload: CreateInterviewRequest) -> ProductInterview:
        version = self.db.scalar(
            select(ProductCvVersion).where(
                ProductCvVersion.id == payload.cv_version_id,
                ProductCvVersion.user_id == current.id,
            )
        )
        if version is None:
            raise AppError(404, "CV_VERSION_NOT_FOUND", "CV version was not found")
        from app.services.runtime_configuration import runtime_model_configuration

        runtime = runtime_model_configuration("interview_live", "gemini", os.getenv("GEMINI_LIVE_MODEL", "gemini-3.1-flash-live-preview"))
        gemini_model = runtime["model"]
        interview = ProductInterview(
            user_id=current.id,
            cv_version_id=version.id,
            job_id=payload.job_id,
            target_role=payload.target_role,
            interview_type=payload.interview_type,
            language=payload.language,
            duration_minutes=payload.duration_minutes,
            status="ready",
            cv_snapshot={
                "version_id": version.id,
                "schema_version": version.schema_version,
                "checksum": version.checksum,
                "content": version.content,
            },
            job_snapshot={"job_id": payload.job_id, "status": "pending_resolution"} if payload.job_id else None,
            plan_snapshot={**self._plan(payload), "instruction_prefix": runtime["configuration"].get("instruction_prefix")},
            rubric_version=os.getenv("INTERVIEW_RUBRIC_VERSION", "interview-v1"),
            prompt_version=runtime["version"] if runtime["version"] != "environment" else os.getenv("INTERVIEW_PROMPT_VERSION", "interview-v1"),
            gemini_model=gemini_model,
        )
        self.db.add(interview)
        self.db.flush()
        from app.services.product_billing import ProductBillingService

        reservation = ProductBillingService(self.db).reserve(
            current,
            "interview",
            "interview",
            interview.id,
            duration_minutes=payload.duration_minutes,
        )
        interview.credit_reservation_id = reservation.id if reservation else None
        self.db.commit()
        self.db.refresh(interview)
        return interview

    def list(self, current: ProductCurrentUser, cursor: str | None, limit: int) -> InterviewPage:
        statement = select(ProductInterview).where(ProductInterview.user_id == current.id)
        if cursor:
            created_at, item_id = _decode_cursor(cursor)
            statement = statement.where(
                (ProductInterview.created_at < created_at)
                | ((ProductInterview.created_at == created_at) & (ProductInterview.id < item_id))
            )
        records = list(
            self.db.scalars(
                statement.order_by(ProductInterview.created_at.desc(), ProductInterview.id.desc()).limit(limit + 1)
            )
        )
        has_more = len(records) > limit
        records = records[:limit]
        return InterviewPage(
            items=[self.view(item) for item in records],
            next_cursor=_encode_cursor(records[-1].created_at, records[-1].id) if has_more and records else None,
        )

    def get(self, current: ProductCurrentUser, interview_id: str) -> ProductInterview:
        interview = self.db.get(ProductInterview, interview_id)
        if interview is None or (current.role != "admin" and interview.user_id != current.id):
            raise AppError(404, "INTERVIEW_NOT_FOUND", "Interview was not found")
        return interview

    def create_realtime_token(
        self,
        current: ProductCurrentUser,
        interview_id: str,
        base_url: str,
    ) -> RealtimeTokenView:
        interview = self.get(current, interview_id)
        if interview.status not in {"ready", "interrupted"}:
            raise AppError(
                409,
                "INTERVIEW_NOT_CONNECTABLE",
                "Interview cannot accept a realtime connection",
                details={"status": interview.status},
            )
        raw_token = secrets.token_urlsafe(32)
        ttl = min(max(int(os.getenv("INTERVIEW_TOKEN_TTL_SECONDS", "60")), 30), 300)
        expires_at = _utcnow() + timedelta(seconds=ttl)
        self.db.add(
            InterviewRealtimeToken(
                interview_id=interview.id,
                user_id=current.id,
                token_hash=hashlib.sha256(raw_token.encode()).hexdigest(),
                expires_at=expires_at,
            )
        )
        self.db.commit()
        websocket_base = base_url.replace("https://", "wss://").replace("http://", "ws://").rstrip("/")
        return RealtimeTokenView(
            token=raw_token,
            websocket_url=websocket_base + "/v1/interviews/" + interview.id + "/realtime",
            expires_at=expires_at,
        )

    def consume_realtime_token(self, interview_id: str, raw_token: str) -> ProductInterview:
        digest = hashlib.sha256(raw_token.encode()).hexdigest()
        token = self.db.scalar(
            select(InterviewRealtimeToken)
            .where(
                InterviewRealtimeToken.interview_id == interview_id,
                InterviewRealtimeToken.token_hash == digest,
            )
            .with_for_update()
        )
        now = _utcnow()
        if token is None or token.expires_at <= now or token.consumed_at is not None or token.revoked_at is not None:
            raise AppError(401, "REALTIME_TOKEN_INVALID", "Realtime token is invalid or expired")
        interview = self.db.get(ProductInterview, interview_id)
        if interview is None or interview.user_id != token.user_id or interview.status not in {"ready", "interrupted"}:
            raise AppError(409, "INTERVIEW_NOT_CONNECTABLE", "Interview cannot accept a realtime connection")
        token.consumed_at = now
        interview.status = "live"
        interview.started_at = interview.started_at or now
        interview.reconnect_until = None
        self.db.commit()
        self.db.refresh(interview)
        return interview

    def mark_interrupted(self, interview_id: str) -> None:
        interview = self.db.get(ProductInterview, interview_id)
        if interview is not None and interview.status == "live":
            interview.status = "interrupted"
            interview.reconnect_until = _utcnow() + timedelta(minutes=5)
            self.db.commit()

    def update_resumption_handle(self, interview_id: str, handle: str | None) -> None:
        interview = self.db.get(ProductInterview, interview_id)
        if interview is not None:
            interview.gemini_resumption_handle = handle
            self.db.commit()

    def record_event(
        self,
        interview_id: str,
        direction: str,
        event_type: str,
        payload: dict[str, Any] | None = None,
        speaker: str | None = None,
        text: str | None = None,
        client_event_id: str | None = None,
        provider_event_id: str | None = None,
    ) -> ProductInterviewEvent:
        if client_event_id:
            existing = self.db.scalar(
                select(ProductInterviewEvent).where(
                    ProductInterviewEvent.interview_id == interview_id,
                    ProductInterviewEvent.client_event_id == client_event_id,
                )
            )
            if existing is not None:
                setattr(existing, "_deduplicated", True)
                return existing
        if provider_event_id:
            existing = self.db.scalar(
                select(ProductInterviewEvent).where(
                    ProductInterviewEvent.interview_id == interview_id,
                    ProductInterviewEvent.provider_event_id == provider_event_id,
                )
            )
            if existing is not None:
                setattr(existing, "_deduplicated", True)
                return existing
        interview = self.db.scalar(
            select(ProductInterview).where(ProductInterview.id == interview_id).with_for_update()
        )
        if interview is None:
            raise AppError(404, "INTERVIEW_NOT_FOUND", "Interview was not found")
        sequence = (
            self.db.scalar(
                select(func.max(ProductInterviewEvent.sequence)).where(
                    ProductInterviewEvent.interview_id == interview_id
                )
            )
            or 0
        ) + 1
        event = ProductInterviewEvent(
            interview_id=interview_id,
            sequence=sequence,
            direction=direction,
            event_type=event_type,
            speaker=speaker,
            text=text,
            payload=payload or {},
            client_event_id=client_event_id,
            provider_event_id=provider_event_id,
        )
        self.db.add(event)
        self.db.commit()
        self.db.refresh(event)
        setattr(event, "_deduplicated", False)
        return event

    def end_realtime(self, interview_id: str) -> ProductInterview:
        interview = self.db.get(ProductInterview, interview_id)
        if interview is None:
            raise AppError(404, "INTERVIEW_NOT_FOUND", "Interview was not found")
        current = ProductCurrentUser(
            id=interview.user_id,
            email="",
            role="student",
            email_verified=True,
            scopes=frozenset({"interview:realtime"}),
            session_id=None,
        )
        return self.end(current, interview_id)

    def end(self, current: ProductCurrentUser, interview_id: str) -> ProductInterview:
        interview = self.get(current, interview_id)
        if interview.status in {"evaluating", "completed", "evaluation_failed"}:
            return interview
        if interview.status == "cancelled":
            raise AppError(409, "INTERVIEW_CANCELLED", "Cancelled interview cannot be evaluated")
        if interview.status not in {"ready", "live", "interrupted", "ending"}:
            raise AppError(409, "INTERVIEW_NOT_ENDABLE", "Interview cannot be ended")
        candidate_events = self.db.scalar(
            select(func.count())
            .select_from(ProductInterviewEvent)
            .where(
                ProductInterviewEvent.interview_id == interview.id,
                ProductInterviewEvent.speaker == "candidate",
                ProductInterviewEvent.text.is_not(None),
            )
        )
        if not candidate_events:
            raise AppError(409, "INTERVIEW_TRANSCRIPT_EMPTY", "Interview has no candidate transcript to evaluate")
        transcript_version = self.db.scalar(
            select(func.max(ProductInterviewEvent.sequence)).where(ProductInterviewEvent.interview_id == interview.id)
        ) or 0
        from app.services.runtime_configuration import runtime_model_configuration

        evaluation_runtime = runtime_model_configuration(
            "interview_evaluation",
            "openai",
            os.getenv("OPENAI_INTERVIEW_MODEL", os.getenv("OPENAI_CV_MODEL", "gpt-4.1-mini")),
        )
        report = self.db.scalar(
            select(ProductInterviewReport).where(
                ProductInterviewReport.interview_id == interview.id,
                ProductInterviewReport.rubric_version == interview.rubric_version,
            )
        )
        if report is None:
            report = ProductInterviewReport(
                interview_id=interview.id,
                user_id=current.id,
                status="processing",
                rubric_version=interview.rubric_version,
                prompt_version=evaluation_runtime["version"] if evaluation_runtime["version"] != "environment" else interview.prompt_version,
                model=evaluation_runtime["model"],
                transcript_version=transcript_version,
            )
            self.db.add(report)
        interview.status = "evaluating"
        interview.ended_at = interview.ended_at or _utcnow()
        from app.services.product_billing import ProductBillingService

        ProductBillingService(self.db).capture(interview.credit_reservation_id)
        self.db.commit()
        from app.workers.tasks import evaluate_product_interview_task

        evaluate_product_interview_task.delay(report.id)
        self.db.refresh(interview)
        return interview

    def cancel(self, current: ProductCurrentUser, interview_id: str) -> ProductInterview:
        interview = self.get(current, interview_id)
        if interview.status in {"completed", "evaluating"}:
            raise AppError(409, "INTERVIEW_NOT_CANCELLABLE", "Interview can no longer be cancelled")
        if interview.status != "cancelled":
            interview.status = "cancelled"
            interview.ended_at = _utcnow()
            from app.services.product_billing import ProductBillingService

            ProductBillingService(self.db).release(interview.credit_reservation_id, "interview_cancelled")
            self.db.commit()
        return interview

    def report(self, current: ProductCurrentUser, interview_id: str) -> ProductInterviewReport | None:
        interview = self.get(current, interview_id)
        return self.db.scalar(
            select(ProductInterviewReport)
            .where(ProductInterviewReport.interview_id == interview.id)
            .order_by(ProductInterviewReport.created_at.desc())
        )

    def feedback(
        self,
        current: ProductCurrentUser,
        interview_id: str,
        payload: InterviewFeedbackRequest,
    ) -> InterviewFeedback:
        report = self.report(current, interview_id)
        if report is None or report.status != "ready":
            raise AppError(409, "INTERVIEW_REPORT_NOT_READY", "Interview report is not ready")
        if payload.event_ids:
            count = self.db.scalar(
                select(func.count())
                .select_from(ProductInterviewEvent)
                .where(
                    ProductInterviewEvent.interview_id == interview_id,
                    ProductInterviewEvent.id.in_(payload.event_ids),
                )
            )
            if count != len(set(payload.event_ids)):
                raise AppError(422, "INVALID_EVIDENCE_EVENT", "Feedback references an unknown interview event")
        feedback = InterviewFeedback(
            interview_id=interview_id,
            report_id=report.id,
            user_id=current.id,
            category=payload.category,
            message=payload.message,
            event_ids=payload.event_ids,
        )
        self.db.add(feedback)
        self.db.commit()
        self.db.refresh(feedback)
        return feedback

    @staticmethod
    def view(interview: ProductInterview) -> InterviewView:
        return InterviewView(
            id=interview.id,
            status=interview.status,
            target_role=interview.target_role,
            interview_type=interview.interview_type,
            cv_version_id=interview.cv_version_id,
            job_id=interview.job_id,
            language=interview.language,
            duration_minutes=interview.duration_minutes,
            started_at=interview.started_at,
            ended_at=interview.ended_at,
            reconnect_until=interview.reconnect_until,
            created_at=interview.created_at,
        )

    @staticmethod
    def report_view(report: ProductInterviewReport) -> InterviewReportView:
        return InterviewReportView(
            id=report.id,
            interview_id=report.interview_id,
            status=report.status,
            rubric_version=report.rubric_version,
            scores=report.scores or {},
            strengths=[EvidenceFinding.model_validate(item) for item in (report.strengths or [])],
            gaps=[EvidenceFinding.model_validate(item) for item in (report.gaps or [])],
            actions=report.actions or [],
            disclaimer=report.disclaimer or "AI coaching output; not a hiring decision.",
            created_at=report.created_at,
        )

    @staticmethod
    def _plan(payload: CreateInterviewRequest) -> dict[str, Any]:
        dimensions = {
            "behavioral": ["communication", "ownership", "teamwork", "learning"],
            "technical": ["technical_depth", "problem_solving", "tradeoffs", "evidence"],
            "mixed": ["communication", "technical_depth", "problem_solving", "role_fit"],
        }
        return {
            "target_role": payload.target_role,
            "interview_type": payload.interview_type,
            "language": payload.language,
            "duration_minutes": payload.duration_minutes,
            "dimensions": dimensions[payload.interview_type],
            "policy": "Ask one concise question at a time and ground follow-ups in candidate answers.",
        }
