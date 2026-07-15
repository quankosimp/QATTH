from pathlib import Path
from unittest.mock import MagicMock

from app.services.candidate_profiles import invalidate_candidate_profiles


ROOT = Path(__file__).resolve().parents[1]


def test_candidate_profile_invalidation_updates_all_fresh_profiles() -> None:
    db = MagicMock()
    update = db.query.return_value.filter.return_value.update
    update.return_value = 3

    assert invalidate_candidate_profiles(db, "user-1") == 3
    update.assert_called_once()
    assert update.call_args.kwargs["synchronize_session"] is False


def test_all_candidate_inputs_invalidate_and_active_cv_is_authoritative() -> None:
    identity = (ROOT / "backend/app/services/identity.py").read_text()
    cv = (ROOT / "backend/app/services/product_cv.py").read_text()
    worker = (ROOT / "backend/app/workers/tasks.py").read_text()
    recommendations = (ROOT / "backend/app/services/product_recommendations.py").read_text()

    assert "invalidate_candidate_profiles(self.db, user_id)" in identity
    assert cv.count("invalidate_candidate_profiles(self.db, current.id)") >= 3
    assert "invalidate_candidate_profiles(db, report.user_id)" in worker
    assert "ProductCV.active_version_id == ProductCvVersion.id" in recommendations
    assert 'CandidateProfile.generation_version == "candidate-v2"' in recommendations
