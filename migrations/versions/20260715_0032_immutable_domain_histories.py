"""protect immutable CV and interview histories

Revision ID: 20260715_0032
Revises: 20260715_0031
Create Date: 2026-07-15
"""

from typing import Sequence, Union

from alembic import op


revision: str = "20260715_0032"
down_revision: Union[str, None] = "20260715_0031"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(
            "CREATE FUNCTION product_domain_history_immutable() RETURNS trigger AS $$ "
            "BEGIN RAISE EXCEPTION 'domain history is immutable'; END; $$ LANGUAGE plpgsql"
        )
        op.execute(
            "CREATE TRIGGER trg_product_cv_version_immutable BEFORE UPDATE OF "
            "cv_id, user_id, source_file_id, version, schema_version, content, checksum, created_at "
            "ON product_cv_versions FOR EACH ROW EXECUTE FUNCTION product_domain_history_immutable()"
        )
        op.execute(
            "CREATE TRIGGER trg_product_interview_event_immutable BEFORE UPDATE ON "
            "product_interview_events FOR EACH ROW EXECUTE FUNCTION product_domain_history_immutable()"
        )
    elif bind.dialect.name == "sqlite":
        op.execute(
            "CREATE TRIGGER trg_product_cv_version_no_update BEFORE UPDATE OF "
            "cv_id, user_id, source_file_id, version, schema_version, content, checksum, created_at "
            "ON product_cv_versions BEGIN SELECT RAISE(ABORT, 'domain history is immutable'); END"
        )
        op.execute(
            "CREATE TRIGGER trg_product_interview_event_no_update BEFORE UPDATE ON "
            "product_interview_events BEGIN SELECT RAISE(ABORT, 'domain history is immutable'); END"
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS trg_product_interview_event_immutable ON product_interview_events")
        op.execute("DROP TRIGGER IF EXISTS trg_product_cv_version_immutable ON product_cv_versions")
        op.execute("DROP FUNCTION IF EXISTS product_domain_history_immutable")
    elif bind.dialect.name == "sqlite":
        op.execute("DROP TRIGGER IF EXISTS trg_product_interview_event_no_update")
        op.execute("DROP TRIGGER IF EXISTS trg_product_cv_version_no_update")
