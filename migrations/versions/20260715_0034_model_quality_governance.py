"""add model quality gates and staged rollout

Revision ID: 20260715_0034
Revises: 20260715_0033
Create Date: 2026-07-15
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260715_0034"
down_revision: Union[str, None] = "20260715_0033"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "product_model_evaluation_reports",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("model_configuration_id", sa.String(36), sa.ForeignKey("product_model_configurations.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("dataset_key", sa.String(120), nullable=False),
        sa.Column("dataset_version", sa.String(80), nullable=False),
        sa.Column("dataset_sha256", sa.String(64), nullable=False),
        sa.Column("quality_policy_version", sa.String(80), nullable=False),
        sa.Column("evaluator_version", sa.String(80), nullable=False),
        sa.Column("sample_count", sa.Integer(), nullable=False),
        sa.Column("metrics", sa.JSON(), nullable=False),
        sa.Column("criteria", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("external_report_id", sa.String(255), nullable=True),
        sa.Column("idempotency_key", sa.String(255), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("created_by_user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("created_by_user_id", "idempotency_key", name="uq_product_model_evaluation_report_idempotency"),
    )
    op.create_index("ix_product_model_evaluation_reports_configuration_created", "product_model_evaluation_reports", ["model_configuration_id", "created_at"])
    op.add_column("product_model_configurations", sa.Column("evaluation_report_id", sa.String(36), nullable=True))
    op.add_column("product_model_configurations", sa.Column("rollout_percentage", sa.Integer(), nullable=False, server_default="0"))
    op.create_foreign_key("fk_product_model_configuration_evaluation_report", "product_model_configurations", "product_model_evaluation_reports", ["evaluation_report_id"], ["id"], ondelete="RESTRICT")
    op.execute("UPDATE product_model_configurations SET rollout_percentage = 100 WHERE status = 'active'")
    op.create_index("uq_product_model_configuration_active_purpose", "product_model_configurations", ["purpose"], unique=True, postgresql_where=sa.text("status = 'active'"), sqlite_where=sa.text("status = 'active'"))
    op.create_index("uq_product_model_configuration_canary_purpose", "product_model_configurations", ["purpose"], unique=True, postgresql_where=sa.text("status = 'canary'"), sqlite_where=sa.text("status = 'canary'"))

    bind = op.get_bind()
    protected_columns = "purpose, version, provider, model, configuration, output_schema_version, idempotency_key, request_hash, created_by_user_id, created_at"
    if bind.dialect.name == "postgresql":
        op.execute(f"CREATE TRIGGER trg_product_model_configuration_version_immutable BEFORE UPDATE OF {protected_columns} ON product_model_configurations FOR EACH ROW EXECUTE FUNCTION product_domain_history_immutable()")
        op.execute("CREATE TRIGGER trg_product_model_evaluation_report_immutable BEFORE UPDATE OR DELETE ON product_model_evaluation_reports FOR EACH ROW EXECUTE FUNCTION product_domain_history_immutable()")
    elif bind.dialect.name == "sqlite":
        op.execute(f"CREATE TRIGGER trg_product_model_configuration_version_no_update BEFORE UPDATE OF {protected_columns} ON product_model_configurations BEGIN SELECT RAISE(ABORT, 'domain history is immutable'); END")
        op.execute("CREATE TRIGGER trg_product_model_evaluation_report_no_update BEFORE UPDATE ON product_model_evaluation_reports BEGIN SELECT RAISE(ABORT, 'domain history is immutable'); END")
        op.execute("CREATE TRIGGER trg_product_model_evaluation_report_no_delete BEFORE DELETE ON product_model_evaluation_reports BEGIN SELECT RAISE(ABORT, 'domain history is immutable'); END")


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS trg_product_model_evaluation_report_immutable ON product_model_evaluation_reports")
        op.execute("DROP TRIGGER IF EXISTS trg_product_model_configuration_version_immutable ON product_model_configurations")
    elif bind.dialect.name == "sqlite":
        op.execute("DROP TRIGGER IF EXISTS trg_product_model_evaluation_report_no_delete")
        op.execute("DROP TRIGGER IF EXISTS trg_product_model_evaluation_report_no_update")
        op.execute("DROP TRIGGER IF EXISTS trg_product_model_configuration_version_no_update")
    op.drop_index("uq_product_model_configuration_canary_purpose", table_name="product_model_configurations")
    op.drop_index("uq_product_model_configuration_active_purpose", table_name="product_model_configurations")
    op.drop_constraint("fk_product_model_configuration_evaluation_report", "product_model_configurations", type_="foreignkey")
    op.drop_column("product_model_configurations", "rollout_percentage")
    op.drop_column("product_model_configurations", "evaluation_report_id")
    op.drop_index("ix_product_model_evaluation_reports_configuration_created", table_name="product_model_evaluation_reports")
    op.drop_table("product_model_evaluation_reports")
