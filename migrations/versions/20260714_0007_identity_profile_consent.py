"""identity profile and consent

Revision ID: 20260714_0007
Revises: 82fe1d807848
Create Date: 2026-07-14
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "20260714_0007"
down_revision: Union[str, None] = "82fe1d807848"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "auth_identities",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("issuer", sa.String(length=512), nullable=False),
        sa.Column("subject", sa.String(length=512), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=True),
        sa.Column("email_verified", sa.Boolean(), nullable=False),
        sa.Column("claims_snapshot", sa.JSON(), nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("issuer", "subject", name="uq_auth_identity_issuer_subject"),
    )
    op.create_index("ix_auth_identities_user_id", "auth_identities", ["user_id"])

    op.create_table(
        "user_product_profiles",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("account_status", sa.String(length=32), nullable=False),
        sa.Column("display_name", sa.String(length=200), nullable=True),
        sa.Column("locale", sa.String(length=16), nullable=False),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column("headline", sa.String(length=240), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("location", sa.String(length=200), nullable=True),
        sa.Column("years_of_experience", sa.Integer(), nullable=True),
        sa.Column("skills", sa.JSON(), nullable=False),
        sa.Column("profile_links", sa.JSON(), nullable=False),
        sa.Column("job_preferences", sa.JSON(), nullable=False),
        sa.Column("preference_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id"),
    )
    op.create_index("ix_user_product_profiles_account_status", "user_product_profiles", ["account_status"])

    op.create_table(
        "user_consents",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("purpose", sa.String(length=80), nullable=False),
        sa.Column("policy_version", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("granted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("withdrawn_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "purpose", "policy_version", name="uq_user_consent_policy"),
    )
    op.create_index("ix_user_consents_user_purpose", "user_consents", ["user_id", "purpose"])

    op.create_table(
        "account_status_events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("previous_status", sa.String(length=32), nullable=True),
        sa.Column("new_status", sa.String(length=32), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("actor_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_account_status_events_user_created", "account_status_events", ["user_id", "created_at"])

    op.create_table(
        "user_sessions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("identity_id", sa.String(length=36), nullable=False),
        sa.Column("token_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("provider_session_id", sa.String(length=512), nullable=True),
        sa.Column("device", sa.JSON(), nullable=False),
        sa.Column("scopes", sa.JSON(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["identity_id"], ["auth_identities.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_fingerprint", name="uq_user_sessions_token_fingerprint"),
    )
    op.create_index("ix_user_sessions_user_active", "user_sessions", ["user_id", "revoked_at", "expires_at"])


def downgrade() -> None:
    op.drop_index("ix_user_sessions_user_active", table_name="user_sessions")
    op.drop_table("user_sessions")
    op.drop_index("ix_account_status_events_user_created", table_name="account_status_events")
    op.drop_table("account_status_events")
    op.drop_index("ix_user_consents_user_purpose", table_name="user_consents")
    op.drop_table("user_consents")
    op.drop_index("ix_user_product_profiles_account_status", table_name="user_product_profiles")
    op.drop_table("user_product_profiles")
    op.drop_index("ix_auth_identities_user_id", table_name="auth_identities")
    op.drop_table("auth_identities")
