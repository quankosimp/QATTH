from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.core.security import CurrentUser
from app.models.db import CVRecord, InterviewSession, InterviewTurn
from app.schemas.cv import CVProfile
from app.schemas.interview import (
    InterviewClientEvent,
    InterviewCreateResult,
    InterviewEndResult,
    InterviewResult,
    InterviewResultRead,
    TranscriptMessage,
)
from app.services.evaluation import EvaluationService


class InterviewService:
    def __init__(self, *, db: Session, current_user: CurrentUser | None = None) -> None:
        self.db = db
        self.current_user = current_user

    def create(self, *, cv_id: str, target_role: str, language: str) -> InterviewCreateResult:
        cv_record = self._get_cv(cv_id)
        profile = CVProfile.model_validate(cv_record.parsed_profile or {})
        opening_message = self._opening_message(profile=profile, target_role=target_role)

        session = InterviewSession(
            user_id=self.current_user.id if self.current_user else cv_record.user_id,
            cv_id=cv_id,
            target_role=target_role,
            language=language,
            status="created",
            opening_message=opening_message,
        )
        self.db.add(session)
        self.db.commit()
        self.db.refresh(session)

        self._add_turn(
            interview_id=session.id,
            role="model",
            event_type="transcript.model",
            text=opening_message,
            payload={"source": "opening_message"},
        )
        self.db.commit()

        return InterviewCreateResult(
            interview_id=session.id,
            cv_id=cv_id,
            status=session.status,
            target_role=target_role,
            opening_message=opening_message,
        )

    def mark_live(self, *, interview_id: str) -> None:
        session = self._get_session(interview_id)
        if session.status in {"created", "disconnected"}:
            session.status = "live"
            self.db.commit()

    def mark_disconnected(self, *, interview_id: str) -> None:
        session = self._get_session(interview_id)
        if session.status == "live":
            session.status = "disconnected"
            self.db.commit()

    def record_user_text(
        self,
        *,
        interview_id: str,
        text: str,
        payload: dict[str, Any] | None = None,
    ) -> None:
        self._add_turn(
            interview_id=interview_id,
            role="user",
            event_type="transcript.user",
            text=text,
            payload=payload,
        )
        self.db.commit()

    def record_user_audio(self, *, interview_id: str, payload: dict[str, Any]) -> None:
        self._add_turn(
            interview_id=interview_id,
            role="user",
            event_type="audio.chunk",
            text=None,
            payload=self._safe_audio_payload(payload),
        )
        self.db.commit()

    def record_model_text(
        self,
        *,
        interview_id: str,
        text: str,
        payload: dict[str, Any] | None = None,
    ) -> None:
        self._add_turn(
            interview_id=interview_id,
            role="model",
            event_type="transcript.model",
            text=text,
            payload=payload,
        )
        self.db.commit()

    def handle_client_event(self, *, interview_id: str, raw_event: dict[str, Any]) -> list[dict[str, Any]]:
        session = self._get_session(interview_id)
        event = InterviewClientEvent.model_validate(raw_event)

        if session.status not in {"created", "live", "disconnected"}:
            raise AppError(
                status_code=409,
                code="INTERVIEW_NOT_STREAMABLE",
                message="Interview cannot receive stream events in its current status.",
                details={"status": session.status},
            )

        if event.type == "text.message":
            text = str(event.payload.get("text") or "").strip()
            if not text:
                raise AppError(
                    status_code=422,
                    code="EMPTY_INTERVIEW_MESSAGE",
                    message="text.message payload.text is required.",
                )
            return self._handle_text_message(session=session, text=text, payload=event.payload)

        if event.type == "audio.chunk":
            stored_payload = self._safe_audio_payload(event.payload)
            self._add_turn(
                interview_id=interview_id,
                role="user",
                event_type="audio.chunk",
                text=None,
                payload=stored_payload,
            )
            self.db.commit()
            return [
                {
                    "type": "interview.state",
                    "payload": {
                        "state": "live",
                        "message": "Audio chunk received. Gemini Live proxy can be enabled with GEMINI_API_KEY.",
                    },
                }
            ]

        if event.type == "control.end_turn":
            question = self._next_question(session=session)
            self._add_turn(
                interview_id=interview_id,
                role="model",
                event_type="transcript.model",
                text=question,
                payload={"source": "end_turn"},
            )
            self.db.commit()
            return [{"type": "transcript.model", "payload": {"text": question, "final": True}}]

        if event.type == "control.end":
            return [{"type": "interview.state", "payload": {"state": "ready_to_end"}}]

        raise AppError(
            status_code=422,
            code="UNSUPPORTED_INTERVIEW_EVENT",
            message=f"Unsupported interview event type: {event.type}",
        )

    async def end(self, *, interview_id: str) -> InterviewEndResult:
        session = self._get_session(interview_id)
        cv_record = self._get_cv(session.cv_id)

        if session.result:
            return InterviewEndResult(
                interview_id=session.id,
                status=session.status,
                result=InterviewResult.model_validate(session.result),
            )

        session.status = "evaluating"
        self.db.commit()

        try:
            result = await EvaluationService(db=self.db).evaluate(session=session, cv_record=cv_record)
        except Exception as exc:
            session.status = "failed"
            session.failure_reason = str(exc)
            self.db.commit()
            raise

        session.status = "completed"
        session.ended_at = datetime.now(UTC)
        session.result = result.model_dump(mode="json")
        self.db.commit()

        return InterviewEndResult(interview_id=session.id, status=session.status, result=result)

    def get_result(self, *, interview_id: str) -> InterviewResultRead:
        session = self._get_session(interview_id)
        transcript = self._load_transcript(interview_id=interview_id)
        result = InterviewResult.model_validate(session.result) if session.result else None
        return InterviewResultRead(
            interview_id=session.id,
            cv_id=session.cv_id,
            status=session.status,
            target_role=session.target_role,
            result=result,
            transcript=transcript,
        )

    def _handle_text_message(
        self,
        *,
        session: InterviewSession,
        text: str,
        payload: dict[str, Any],
    ) -> list[dict[str, Any]]:
        self._add_turn(
            interview_id=session.id,
            role="user",
            event_type="transcript.user",
            text=text,
            payload=payload,
        )

        question = self._next_question(session=session)
        self._add_turn(
            interview_id=session.id,
            role="model",
            event_type="transcript.model",
            text=question,
            payload={"source": "demo_interviewer"},
        )
        self.db.commit()

        return [
            {"type": "transcript.user", "payload": {"text": text, "final": True}},
            {"type": "transcript.model", "payload": {"text": question, "final": True}},
        ]

    def _next_question(self, *, session: InterviewSession) -> str:
        user_turn_count = self.db.scalar(
            select(func.count())
            .select_from(InterviewTurn)
            .where(InterviewTurn.interview_id == session.id, InterviewTurn.role == "user")
        )
        question_bank = [
            f"Bạn hãy chọn một project gần nhất và giải thích kiến trúc chính liên quan tới {session.target_role}.",
            "Nếu API backend trả chậm trong production, bạn sẽ debug theo các bước nào?",
            "Bạn đã từng thiết kế database cho feature nào chưa? Hãy nói về bảng chính và quan hệ dữ liệu.",
            "Khi làm việc nhóm, bạn xử lý conflict code hoặc requirement thay đổi như thế nào?",
            "Bạn muốn cải thiện kỹ năng kỹ thuật nào trong 3 tháng tới để phù hợp hơn với vị trí này?",
        ]
        index = min(max((user_turn_count or 1) - 1, 0), len(question_bank) - 1)
        return question_bank[index]

    def _opening_message(self, *, profile: CVProfile, target_role: str) -> str:
        name = profile.name or "bạn"
        return (
            f"Chào {name}, mình sẽ phỏng vấn bạn cho vị trí {target_role}. "
            "Trước tiên, hãy giới thiệu ngắn gọn về bản thân và một project IT bạn tự tin nhất."
        )

    def _safe_audio_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        data = str(payload.get("data_base64") or "")
        return {
            "mime": payload.get("mime"),
            "sample_rate": payload.get("sample_rate"),
            "data_base64": "<omitted>",
            "size_base64_chars": len(data),
        }

    def _add_turn(
        self,
        *,
        interview_id: str,
        role: str,
        event_type: str,
        text: str | None,
        payload: dict[str, Any] | None,
    ) -> InterviewTurn:
        turn = InterviewTurn(
            interview_id=interview_id,
            role=role,
            event_type=event_type,
            text=text,
            payload=payload,
        )
        self.db.add(turn)
        return turn

    def _load_transcript(self, *, interview_id: str) -> list[TranscriptMessage]:
        turns = self.db.scalars(
            select(InterviewTurn)
            .where(
                InterviewTurn.interview_id == interview_id,
                InterviewTurn.text.is_not(None),
            )
            .order_by(InterviewTurn.created_at.asc(), InterviewTurn.id.asc())
        ).all()
        return [
            TranscriptMessage(role=turn.role, text=turn.text or "", created_at=turn.created_at)
            for turn in turns
        ]

    def _get_cv(self, cv_id: str) -> CVRecord:
        cv_record = self.db.get(CVRecord, cv_id)
        if not cv_record:
            raise AppError(
                status_code=404,
                code="CV_NOT_FOUND",
                message="CV was not found.",
                details={"cv_id": cv_id},
            )
        if cv_record.scan_status != "completed":
            raise AppError(
                status_code=409,
                code="CV_NOT_READY",
                message="CV must be scanned successfully before starting an interview.",
                details={"status": cv_record.scan_status},
            )
        if (
            self.current_user
            and not self.current_user.is_admin
            and cv_record.user_id not in {None, self.current_user.id}
        ):
            raise AppError(
                status_code=404,
                code="CV_NOT_FOUND",
                message="CV was not found.",
                details={"cv_id": cv_id},
            )
        return cv_record

    def _get_session(self, interview_id: str) -> InterviewSession:
        session = self.db.get(InterviewSession, interview_id)
        if not session:
            raise AppError(
                status_code=404,
                code="INTERVIEW_NOT_FOUND",
                message="Interview was not found.",
                details={"interview_id": interview_id},
            )
        if (
            self.current_user
            and not self.current_user.is_admin
            and session.user_id not in {None, self.current_user.id}
        ):
            raise AppError(
                status_code=404,
                code="INTERVIEW_NOT_FOUND",
                message="Interview was not found.",
                details={"interview_id": interview_id},
            )
        return session
