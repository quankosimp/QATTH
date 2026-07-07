"""file asset storage

Revision ID: 20260707_0003
Revises: 20260707_0002
Create Date: 2026-07-07
"""

from alembic import op

from app.core.db import Base
import app.models.db  # noqa: F401

revision = "20260707_0003"
down_revision = "20260707_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.tables["file_assets"].create(bind=bind, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    Base.metadata.tables["file_assets"].drop(bind=bind, checkfirst=True)
