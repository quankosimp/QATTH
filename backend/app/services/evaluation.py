from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.db import CVRecord, InterviewSession, InterviewTurn
from app.schemas.cv import CVProfile
from app.schemas.interview import InterviewResult, RubricScore, TranscriptMessage
from app.services.gemini import GeminiService


class EvaluationService:
    def __init__(self, *, db: Session, gemini: GeminiService | None = None) -> None:
        self.db = db
        self.gemini = gemini or GeminiService()

    async def evaluate(
        self,
        *,
        session: InterviewSession,
        cv_record: CVRecord,
    ) -> InterviewResult:
        profile = CVProfile.model_validate(cv_record.parsed_profile or {})
        transcript = self._load_transcript(interview_id=session.id)

        if self.gemini.is_configured:
            payload = await self.gemini.evaluate_interview(
                profile=profile.model_dump(mode="json"),
                transcript=[item.model_dump(mode="json") for item in transcript],
                target_role=session.target_role,
                language=session.language,
                response_schema=InterviewResult,
            )
            result = InterviewResult.model_validate(payload)
            result.full_transcript_ref = session.id
            return result

        return self._demo_result(
            profile=profile,
            transcript=transcript,
            target_role=session.target_role,
            interview_id=session.id,
        )

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

    def _demo_result(
        self,
        *,
        profile: CVProfile,
        transcript: list[TranscriptMessage],
        target_role: str,
        interview_id: str,
    ) -> InterviewResult:
        user_turns = [turn for turn in transcript if turn.role == "user"]
        skill_names = [skill.name for skill in profile.skills]
        base_score = 5.5 + min(len(user_turns), 4) * 0.5
        has_project = bool(profile.projects)
        overall = min(8.0 if has_project else 7.0, base_score)

        return InterviewResult(
            overall_score=overall,
            rubric_scores=[
                RubricScore(
                    name="technical_foundation",
                    score=min(8.0, overall),
                    comment="Estimated from CV skills and interview response length.",
                ),
                RubricScore(
                    name="problem_solving",
                    score=max(5.0, overall - 0.5),
                    comment="Needs real-time coding/problem questions for stronger evidence.",
                ),
                RubricScore(
                    name="communication",
                    score=min(8.0, overall + 0.2),
                    comment="Demo score based on completed turns.",
                ),
                RubricScore(
                    name="job_readiness",
                    score=max(5.0, overall - 0.3),
                    comment=f"Estimated readiness for {target_role}.",
                ),
            ],
            strengths=[
                f"Relevant skills detected: {', '.join(skill_names[:5]) or 'not enough evidence'}",
                "Completed a structured interview flow.",
            ],
            weaknesses=[
                "Needs live Gemini evaluation for production-grade scoring.",
                "Add more project impact metrics and deployment details.",
            ],
            recommended_roles=profile.target_roles or [target_role],
            skill_gaps=["Testing fundamentals", "System design basics", "Cloud deployment basics"],
            transcript_summary=(
                f"Demo evaluation generated from {len(user_turns)} candidate turns for {target_role}."
            ),
            full_transcript_ref=interview_id,
        )
