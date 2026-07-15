from sqlalchemy.orm import Session

from app.models.product_jobs import CandidateProfile


def invalidate_candidate_profiles(db: Session, user_id: str) -> int:
    return int(
        db.query(CandidateProfile)
        .filter(CandidateProfile.user_id == user_id, CandidateProfile.status == "fresh")
        .update({CandidateProfile.status: "stale"}, synchronize_session=False)
    )
