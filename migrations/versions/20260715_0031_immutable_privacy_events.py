"""make privacy audit events immutable

Revision ID: 20260715_0031
Revises: 20260715_0030
Create Date: 2026-07-15
"""

from typing import Sequence, Union

from alembic import op


revision: str = "20260715_0031"
down_revision: Union[str, None] = "20260715_0030"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("CREATE FUNCTION product_privacy_event_immutable() RETURNS trigger AS $$ BEGIN RAISE EXCEPTION 'privacy events are immutable'; END; $$ LANGUAGE plpgsql")
        op.execute("CREATE TRIGGER trg_product_privacy_event_immutable BEFORE UPDATE OR DELETE ON product_privacy_events FOR EACH ROW EXECUTE FUNCTION product_privacy_event_immutable()")
    elif bind.dialect.name == "sqlite":
        op.execute("CREATE TRIGGER trg_product_privacy_event_no_update BEFORE UPDATE ON product_privacy_events BEGIN SELECT RAISE(ABORT, 'privacy events are immutable'); END")
        op.execute("CREATE TRIGGER trg_product_privacy_event_no_delete BEFORE DELETE ON product_privacy_events BEGIN SELECT RAISE(ABORT, 'privacy events are immutable'); END")


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS trg_product_privacy_event_immutable ON product_privacy_events")
        op.execute("DROP FUNCTION IF EXISTS product_privacy_event_immutable")
    elif bind.dialect.name == "sqlite":
        op.execute("DROP TRIGGER IF EXISTS trg_product_privacy_event_no_update")
        op.execute("DROP TRIGGER IF EXISTS trg_product_privacy_event_no_delete")
