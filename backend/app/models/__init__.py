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

from backend.app.models.product_jobs import (
    CandidateProfile,
    JobEmbedding,
    JobSearchEvent,
    JobSearchDispatch,
    JobSearchResult,
    JobSearchRun,
    JobSnapshot,
    JobSource,
    JobSourceRecord,
    ProductJob,
)

from backend.app.models.product_recommendations import (
    JobApplication,
    JobApplicationEvent,
    JobInteraction,
    JobModerationCase,
    RecommendationDispatch,
    RecommendationMatch,
    RecommendationRun,
)

from backend.app.models.product_billing import (
    BillingCatalogVersion,
    BillingCheckoutSession,
    BillingCommand,
    BillingOffer,
    BillingSubscription,
    CreditAccount,
    CreditBucket,
    CreditLedgerEntry,
    CreditReservation,
    CreditReservationAllocation,
    FeatureCreditPrice,
    PaymentEventInbox,
    SignupTrialGrant,
    SignupTrialPolicy,
)

from backend.app.models.product_privacy import (
    DeletionTombstone,
    PrivacyArtifact,
    PrivacyDispatch,
    PrivacyEvent,
    PrivacyRequest,
)

from backend.app.models.product_admin_ops import (
    AuditChainHead,
    ModelConfiguration,
    OperationalJob,
    PrivilegedAuditEvent,
    PrivilegedCommand,
)
