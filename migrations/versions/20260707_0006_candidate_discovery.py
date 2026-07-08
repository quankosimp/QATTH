"""candidate discovery profiles

Revision ID: 20260707_0006
Revises: 20260707_0005
Create Date: 2026-07-08
"""

from alembic import op
import sqlalchemy as sa

from app.core.db import Base
import app.models.db  # noqa: F401

revision = "20260707_0006"
down_revision = "20260707_0005"
branch_labels = None
depends_on = None


def _has_column(table_name: str, column_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return any(column["name"] == column_name for column in inspector.get_columns(table_name))


def _has_index(table_name: str, index_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return any(index["name"] == index_name for index in inspector.get_indexes(table_name))


def upgrade() -> None:
    bind = op.get_bind()
    if not _has_column("interview_sessions", "interview_type"):
        op.add_column(
            "interview_sessions",
            sa.Column("interview_type", sa.String(length=40), nullable=False, server_default="mock"),
        )
    if not _has_index("interview_sessions", "ix_interview_sessions_interview_type"):
        op.create_index(
            "ix_interview_sessions_interview_type",
            "interview_sessions",
            ["interview_type"],
            unique=False,
        )
    Base.metadata.tables["candidate_discovery_profiles"].create(bind=bind, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    Base.metadata.tables["candidate_discovery_profiles"].drop(bind=bind, checkfirst=True)
    if _has_index("interview_sessions", "ix_interview_sessions_interview_type"):
        op.drop_index("ix_interview_sessions_interview_type", table_name="interview_sessions")
    if _has_column("interview_sessions", "interview_type"):
        op.drop_column("interview_sessions", "interview_type")
