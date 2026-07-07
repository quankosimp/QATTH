"""security and privacy hardening

Revision ID: 20260707_0005
Revises: 20260707_0004
Create Date: 2026-07-07
"""

from alembic import op

from app.core.db import Base
import app.models.db  # noqa: F401

revision = "20260707_0005"
down_revision = "20260707_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.tables["password_reset_tokens"].create(bind=bind, checkfirst=True)
    Base.metadata.tables["audit_logs"].create(bind=bind, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    Base.metadata.tables["audit_logs"].drop(bind=bind, checkfirst=True)
    Base.metadata.tables["password_reset_tokens"].drop(bind=bind, checkfirst=True)
