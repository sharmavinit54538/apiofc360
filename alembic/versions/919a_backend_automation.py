"""Persist automation rules/executions and constrain the platform owner identity."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "919a_backend_automation"
down_revision = "0003"
branch_labels = None
depends_on = None


def timestamps():
    return [sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())]


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    # Historical create-all migrations may already have created model tables on
    # a clean install. Existing deployments still require explicit Alembic DDL.
    if not inspector.has_table("notification_automation_rules"):
        op.create_table("notification_automation_rules",
            sa.Column("id", UUID(as_uuid=True), primary_key=True),
            sa.Column("company_id", UUID(as_uuid=True), sa.ForeignKey("companies.id", ondelete="CASCADE"), nullable=False),
            sa.Column("created_by", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("name", sa.String(160), nullable=False),
            sa.Column("trigger_event", sa.String(100), nullable=False),
            sa.Column("configuration", sa.JSON(), nullable=False),
            sa.Column("is_enabled", sa.Boolean(), nullable=False),
            sa.Column("next_run_at", sa.DateTime(timezone=True)),
            sa.Column("interval_minutes", sa.Integer()),
            sa.Column("last_triggered", sa.DateTime(timezone=True)), *timestamps())
        op.create_index("ix_notification_automation_rules_company_id", "notification_automation_rules", ["company_id"])
    if not inspector.has_table("automation_executions"):
        op.create_table("automation_executions",
            sa.Column("id", UUID(as_uuid=True), primary_key=True),
            sa.Column("company_id", UUID(as_uuid=True), sa.ForeignKey("companies.id", ondelete="CASCADE"), nullable=False),
            sa.Column("actor_id", UUID(as_uuid=True), sa.ForeignKey("users.id")),
            sa.Column("rule_id", UUID(as_uuid=True), sa.ForeignKey("notification_automation_rules.id", ondelete="SET NULL")),
            sa.Column("kind", sa.String(40), nullable=False),
            sa.Column("idempotency_key", sa.String(200), nullable=False),
            sa.Column("status", sa.String(20), nullable=False),
            sa.Column("payload", sa.JSON(), nullable=False), sa.Column("result", sa.JSON()),
            sa.Column("attempts", sa.Integer(), nullable=False), sa.Column("error", sa.Text()),
            sa.Column("available_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("started_at", sa.DateTime(timezone=True)), sa.Column("completed_at", sa.DateTime(timezone=True)),
            *timestamps(), sa.UniqueConstraint("company_id", "kind", "idempotency_key", name="uq_automation_execution_key"))
        op.create_index("ix_automation_executions_company_id", "automation_executions", ["company_id"])
        op.create_index("ix_automation_execution_due", "automation_executions", ["status", "available_at"])
    # Fail visibly on historical unauthorized owners; never reactivate or demote them.
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_single_platform_owner ON users (role) WHERE role = 'super_admin'")
    constraints = {c["name"] for c in sa.inspect(bind).get_check_constraints("users")}
    if "ck_users_platform_owner_identity" not in constraints:
        op.create_check_constraint(op.f("ck_users_platform_owner_identity"), "users",
            "role <> 'super_admin' OR (lower(email) = 'superadmin@ofc360.com' AND company_id IS NULL)")


def downgrade():
    op.drop_constraint(op.f("ck_users_platform_owner_identity"), "users", type_="check")
    op.drop_index("ux_single_platform_owner", table_name="users")
    op.drop_table("automation_executions")
    op.drop_table("notification_automation_rules")
