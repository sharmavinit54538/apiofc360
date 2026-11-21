"""Persist payroll ownership across worker crashes without changing financial rows."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "915a_payroll_processing_lease"
down_revision = "914a_payment_idempotency"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("payroll_runs", sa.Column("processing_token", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("payroll_runs", sa.Column("processing_lease_until", sa.DateTime(timezone=True), nullable=True))


def downgrade():
    op.drop_column("payroll_runs", "processing_lease_until")
    op.drop_column("payroll_runs", "processing_token")
