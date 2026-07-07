"""initial schema

Revision ID: 20260707_0001
Revises:
Create Date: 2026-07-07
"""

from alembic import op

from app.core.db import Base
import app.models.db  # noqa: F401

revision = "20260707_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind)


def downgrade() -> None:
    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind)
