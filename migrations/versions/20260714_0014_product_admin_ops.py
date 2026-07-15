"""product administration and operations

Revision ID: 20260714_0014
Revises: 20260714_0013
"""

from alembic import op
import sqlalchemy as sa


revision = "20260714_0014"
down_revision = "20260714_0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("product_model_configurations", sa.Column("id", sa.String(36), primary_key=True), sa.Column("purpose", sa.String(120), nullable=False), sa.Column("version", sa.String(80), nullable=False), sa.Column("status", sa.String(24), nullable=False), sa.Column("provider", sa.String(40), nullable=False), sa.Column("model", sa.String(160), nullable=False), sa.Column("configuration", sa.JSON(), nullable=False), sa.Column("output_schema_version", sa.String(80)), sa.Column("idempotency_key", sa.String(255), nullable=False), sa.Column("request_hash", sa.String(64), nullable=False), sa.Column("created_by_user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False), sa.Column("activated_by_user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL")), sa.Column("activation_reason", sa.Text()), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("activated_at", sa.DateTime(timezone=True)), sa.Column("retired_at", sa.DateTime(timezone=True)), sa.UniqueConstraint("purpose", "version", name="uq_product_model_configuration_version"), sa.UniqueConstraint("created_by_user_id", "idempotency_key", name="uq_product_model_configuration_idempotency"))
    op.create_index("ix_product_model_configurations_purpose_status", "product_model_configurations", ["purpose", "status"])
    op.create_table("product_operational_jobs", sa.Column("id", sa.String(36), primary_key=True), sa.Column("task_name", sa.String(160), nullable=False), sa.Column("queue", sa.String(80), nullable=False), sa.Column("status", sa.String(24), nullable=False), sa.Column("attempt", sa.Integer(), nullable=False), sa.Column("max_attempts", sa.Integer(), nullable=False), sa.Column("resource_type", sa.String(80)), sa.Column("resource_id", sa.String(80)), sa.Column("args_payload", sa.JSON(), nullable=False), sa.Column("request_id", sa.String(128)), sa.Column("parent_job_id", sa.String(36), sa.ForeignKey("product_operational_jobs.id", ondelete="SET NULL")), sa.Column("error_code", sa.String(120)), sa.Column("error_message", sa.Text()), sa.Column("result_summary", sa.JSON()), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("started_at", sa.DateTime(timezone=True)), sa.Column("finished_at", sa.DateTime(timezone=True)), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_product_operational_jobs_status_created", "product_operational_jobs", ["status", "created_at"])
    op.create_index("ix_product_operational_jobs_resource", "product_operational_jobs", ["resource_type", "resource_id"])
    op.create_index("ix_product_operational_jobs_request", "product_operational_jobs", ["request_id"])
    op.create_table("product_privileged_commands", sa.Column("id", sa.String(36), primary_key=True), sa.Column("actor_user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False), sa.Column("command_type", sa.String(160), nullable=False), sa.Column("idempotency_key", sa.String(255), nullable=False), sa.Column("request_hash", sa.String(64), nullable=False), sa.Column("status", sa.String(24), nullable=False), sa.Column("resource_type", sa.String(80)), sa.Column("resource_id", sa.String(80)), sa.Column("response_snapshot", sa.JSON()), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("completed_at", sa.DateTime(timezone=True)), sa.UniqueConstraint("actor_user_id", "command_type", "idempotency_key", name="uq_product_privileged_command_idempotency"))
    op.create_table("product_audit_chain_heads", sa.Column("id", sa.String(80), primary_key=True), sa.Column("sequence", sa.Integer(), nullable=False), sa.Column("last_hash", sa.String(64)), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False))
    op.execute("INSERT INTO product_audit_chain_heads (id, sequence, last_hash, updated_at) VALUES ('privileged', 0, NULL, CURRENT_TIMESTAMP)")
    op.create_table("product_privileged_audit_events", sa.Column("id", sa.String(36), primary_key=True), sa.Column("sequence", sa.Integer(), nullable=False, unique=True), sa.Column("actor_user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False), sa.Column("action", sa.String(160), nullable=False), sa.Column("resource_type", sa.String(80)), sa.Column("resource_id", sa.String(80)), sa.Column("reason", sa.Text()), sa.Column("request_id", sa.String(128)), sa.Column("source_ip_hash", sa.String(64)), sa.Column("metadata_json", sa.JSON(), nullable=False), sa.Column("previous_hash", sa.String(64)), sa.Column("event_hash", sa.String(64), nullable=False, unique=True), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_product_privileged_audit_actor_created", "product_privileged_audit_events", ["actor_user_id", "created_at"])
    op.create_index("ix_product_privileged_audit_resource", "product_privileged_audit_events", ["resource_type", "resource_id"])
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("CREATE FUNCTION product_privileged_audit_immutable() RETURNS trigger AS $$ BEGIN RAISE EXCEPTION 'privileged audit events are immutable'; END; $$ LANGUAGE plpgsql")
        op.execute("CREATE TRIGGER trg_product_privileged_audit_immutable BEFORE UPDATE OR DELETE ON product_privileged_audit_events FOR EACH ROW EXECUTE FUNCTION product_privileged_audit_immutable()")
    elif bind.dialect.name == "sqlite":
        op.execute("CREATE TRIGGER trg_product_privileged_audit_no_update BEFORE UPDATE ON product_privileged_audit_events BEGIN SELECT RAISE(ABORT, 'privileged audit events are immutable'); END")
        op.execute("CREATE TRIGGER trg_product_privileged_audit_no_delete BEFORE DELETE ON product_privileged_audit_events BEGIN SELECT RAISE(ABORT, 'privileged audit events are immutable'); END")


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS trg_product_privileged_audit_immutable ON product_privileged_audit_events")
        op.execute("DROP FUNCTION IF EXISTS product_privileged_audit_immutable")
    elif bind.dialect.name == "sqlite":
        op.execute("DROP TRIGGER IF EXISTS trg_product_privileged_audit_no_update")
        op.execute("DROP TRIGGER IF EXISTS trg_product_privileged_audit_no_delete")
    op.drop_table("product_privileged_audit_events")
    op.drop_table("product_audit_chain_heads")
    op.drop_table("product_privileged_commands")
    op.drop_table("product_operational_jobs")
    op.drop_table("product_model_configurations")
