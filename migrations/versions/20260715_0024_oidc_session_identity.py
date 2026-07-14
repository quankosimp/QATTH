"""bind OIDC sessions to provider session identity

Revision ID: 20260715_0024
Revises: 20260715_0023
Create Date: 2026-07-15
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260715_0024"
down_revision: Union[str, None] = "20260715_0023"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        WITH ranked AS (
            SELECT id,
                   ROW_NUMBER() OVER (
                       PARTITION BY identity_id, provider_session_id
                       ORDER BY created_at DESC, id DESC
                   ) AS duplicate_rank
            FROM user_sessions
            WHERE provider_session_id IS NOT NULL
        )
        UPDATE user_sessions
        SET provider_session_id = NULL,
            revoked_at = COALESCE(revoked_at, CURRENT_TIMESTAMP)
        WHERE id IN (SELECT id FROM ranked WHERE duplicate_rank > 1)
        """
    )
    op.create_index(
        "uq_user_sessions_identity_provider_sid",
        "user_sessions",
        ["identity_id", "provider_session_id"],
        unique=True,
        postgresql_where=sa.text("provider_session_id IS NOT NULL"),
        sqlite_where=sa.text("provider_session_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_user_sessions_identity_provider_sid", table_name="user_sessions")
