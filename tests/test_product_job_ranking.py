from datetime import datetime, timezone

import pytest

from app.models.product_jobs import CandidateProfile, ProductJob
from app.services.product_job_search import ProductJobSearchService


class _SourceFreeDatabase:
    def scalars(self, _statement):
        return self

    def all(self):
        return []


def test_rerank_uses_cv_preferences_interview_and_freshness() -> None:
    service = ProductJobSearchService(_SourceFreeDatabase())  # type: ignore[arg-type]
    job = ProductJob(
        title="Junior Python Backend Developer",
        company_name="Example",
        location_text="Ho Chi Minh City",
        remote_mode="hybrid",
        skills=["Python", "PostgreSQL", "Docker"],
        last_seen_at=datetime.now(timezone.utc),
    )
    candidate = CandidateProfile(
        profile_json={
            "skills": ["Python", "PostgreSQL"],
            "target_roles": ["backend developer"],
            "locations": ["Ho Chi Minh"],
            "remote_modes": ["hybrid"],
            "interview_scores": [{"technical": 8, "communication": 7}],
        }
    )

    ranked = service._score(job, "python backend", candidate, lexical=0.02, vector=0.01)

    assert ranked["breakdown"]["cv_skill_match"] == pytest.approx(2 / 3, abs=1e-6)
    assert ranked["breakdown"]["role_preference"] == 1
    assert ranked["breakdown"]["location_preference"] == 1
    assert ranked["breakdown"]["work_mode_preference"] == 1
    assert ranked["breakdown"]["interview_readiness"] == pytest.approx(0.75)
    assert ranked["breakdown"]["freshness"] > 0.99
    assert ranked["breakdown"]["final"] == pytest.approx(ranked["final"], abs=1e-6)
    assert ranked["gaps"] == ["No explicit CV evidence found for: Docker"]
