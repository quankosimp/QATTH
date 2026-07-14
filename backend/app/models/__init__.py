"""SQLAlchemy model registry.

Import domain model modules from Alembic or application startup so every table is
registered on the shared metadata without coupling domain services together.
"""

from app.models.foundation import IdempotencyRecord, OutboxEvent

__all__ = ["IdempotencyRecord", "OutboxEvent"]

from backend.app.models.identity import (
    AccountStatusEvent,
    AuthIdentity,
    UserConsent,
    UserProductProfile,
    UserSession,
)

from backend.app.models.product_cv import (
    CvAnalysis,
    CvDraft,
    CvScan,
    ProductCV,
    ProductCvVersion,
    ProductFileAsset,
)

from backend.app.models.product_interview import (
    InterviewFeedback,
    InterviewRealtimeToken,
    ProductInterview,
    ProductInterviewEvent,
    ProductInterviewReport,
)
