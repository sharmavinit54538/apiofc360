"""create visitors table and align model exports

Revision ID: 7489259cd72d
Revises: f4799539de17
Create Date: 2026-11-27 12:03:05.103589

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "7489259cd72d"
down_revision: Union[str, None] = "f4799539de17"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = set(insp.get_table_names(schema="public"))
    if "visitors" not in tables:
        op.create_table(
            "visitors",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("name", sa.String(length=200), nullable=False),
            sa.Column("contact", sa.String(length=100), nullable=False),
            sa.Column("purpose", sa.Text(), nullable=False),
            sa.Column("host_employee_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("organization", sa.String(length=200), nullable=True),
            sa.Column("vehicle_number", sa.String(length=50), nullable=True),
            sa.Column("id_proof_type", sa.String(length=50), nullable=True),
            sa.Column("id_proof_number", sa.String(length=100), nullable=True),
            sa.Column("status", sa.String(length=30), nullable=False, server_default=sa.text("'scheduled'")),
            sa.Column("checked_in_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("checked_out_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("checked_in_by", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("checked_out_by", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.PrimaryKeyConstraint("id", name="pk_visitors"),
            sa.ForeignKeyConstraint(["company_id"], ["companies.id"], name="fk_visitors_company_id_companies", ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["host_employee_id"], ["employees.id"], name="fk_visitors_host_employee_id_employees", ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["checked_in_by"], ["users.id"], name="fk_visitors_checked_in_by_users", ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["checked_out_by"], ["users.id"], name="fk_visitors_checked_out_by_users", ondelete="SET NULL"),
        )
        op.create_index("ix_visitors_company_status", "visitors", ["company_id", "status"], unique=False)
        op.create_index("ix_visitors_host_employee", "visitors", ["host_employee_id"], unique=False)
        op.create_index("ix_visitors_scheduled_at", "visitors", ["scheduled_at"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = set(insp.get_table_names(schema="public"))
    if "visitors" in tables:
        idxs = {i["name"] for i in insp.get_indexes("visitors", schema="public") if i.get("name")}
        for idx_name in ("ix_visitors_scheduled_at", "ix_visitors_host_employee", "ix_visitors_company_status"):
            if idx_name in idxs:
                op.drop_index(idx_name, table_name="visitors")
        op.drop_table("visitors")
