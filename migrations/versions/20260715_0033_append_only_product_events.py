"""protect append-only application and recommendation events

Revision ID: 20260715_0033
Revises: 20260715_0032
Create Date: 2026-07-15
"""

from typing import Sequence, Union

from alembic import op


revision: str = "20260715_0033"
down_revision: Union[str, None] = "20260715_0032"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(
            "CREATE TRIGGER trg_product_application_event_immutable BEFORE UPDATE OF "
            "application_id, sequence, from_status, to_status, actor_type, reason_code, metadata_json, created_at "
            "ON product_job_application_events FOR EACH ROW EXECUTE FUNCTION product_domain_history_immutable()"
        )
        op.execute(
            "CREATE TRIGGER trg_product_recommendation_feedback_immutable BEFORE UPDATE ON "
            "product_recommendation_feedback FOR EACH ROW EXECUTE FUNCTION product_domain_history_immutable()"
        )
    elif bind.dialect.name == "sqlite":
        op.execute(
            "CREATE TRIGGER trg_product_application_event_no_update BEFORE UPDATE OF "
            "application_id, sequence, from_status, to_status, actor_type, reason_code, metadata_json, created_at "
            "ON product_job_application_events BEGIN SELECT RAISE(ABORT, 'domain history is immutable'); END"
        )
        op.execute(
            "CREATE TRIGGER trg_product_recommendation_feedback_no_update BEFORE UPDATE ON "
            "product_recommendation_feedback BEGIN SELECT RAISE(ABORT, 'domain history is immutable'); END"
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(
            "DROP TRIGGER IF EXISTS trg_product_recommendation_feedback_immutable "
            "ON product_recommendation_feedback"
        )
        op.execute(
            "DROP TRIGGER IF EXISTS trg_product_application_event_immutable "
            "ON product_job_application_events"
        )
    elif bind.dialect.name == "sqlite":
        op.execute("DROP TRIGGER IF EXISTS trg_product_recommendation_feedback_no_update")
        op.execute("DROP TRIGGER IF EXISTS trg_product_application_event_no_update")
