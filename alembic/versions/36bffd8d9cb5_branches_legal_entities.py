"""branches_legal_entities

Revision ID: 36bffd8d9cb5
Revises: 36bffd8d9cb4
Create Date: 2026-11-15

Create branches and legal_entities tables that were dropped in migration
908a_batch4_onboarding_letters_fnf_migration and never re-created.

These tables are required for Employee.branch_id and Employee.legal_entity_id
foreign keys.

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '36bffd8d9cb5'
down_revision: Union[str, None] = '36bffd8d9cb3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _uuid():
    return postgresql.UUID(as_uuid=True)


def _fk(table, column, target, ondelete=None):
    kwargs = {"ondelete": ondelete} if ondelete else {}
    return sa.ForeignKeyConstraint(
        [column], [f"{target}.id"],
        name=op.f(f"fk_{table}_{column}_{target}"), **kwargs,
    )


def _statutory_columns():
    return [
        sa.Column("gstin", sa.String(length=15), nullable=True),
        sa.Column("pan", sa.String(length=10), nullable=True),
        sa.Column("tan", sa.String(length=10), nullable=True),
        sa.Column("pf_code", sa.String(length=40), nullable=True),
        sa.Column("esi_code", sa.String(length=40), nullable=True),
        sa.Column("pt_reg_no", sa.String(length=50), nullable=True),
        sa.Column("lwf_reg_no", sa.String(length=50), nullable=True),
        sa.Column("state_code", sa.String(length=2), nullable=True),
        sa.Column("address", sa.Text(), nullable=True),
    ]


def _timestamps():
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    ]


def upgrade() -> None:
    # Create legal_entities table
    op.create_table(
        "legal_entities",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("company_id", _uuid(), nullable=True),
        sa.Column("name", sa.String(length=150), nullable=False),
        sa.Column("legal_name", sa.String(length=200), nullable=True),
        sa.Column("code", sa.String(length=30), nullable=False),
        sa.Column("manager_id", _uuid(), nullable=True),
        *_statutory_columns(),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], name=op.f("fk_legal_entities_company_id_companies"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["manager_id"], ["employees.id"], name=op.f("fk_legal_entities_manager_id_employees"), ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_legal_entities")),
        sa.UniqueConstraint("company_id", "code", name="uq_legal_entities_company_code"),
    )

    # Create branches table
    op.create_table(
        "branches",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("company_id", _uuid(), nullable=True),
        sa.Column("legal_entity_id", _uuid(), nullable=False),
        sa.Column("branch_manager_id", _uuid(), nullable=True),
        sa.Column("name", sa.String(length=150), nullable=False),
        sa.Column("code", sa.String(length=30), nullable=False),
        *_statutory_columns(),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], name=op.f("fk_branches_company_id_companies"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["legal_entity_id"], ["legal_entities.id"], name=op.f("fk_branches_legal_entity_id_legal_entities"), ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["branch_manager_id"], ["employees.id"], name=op.f("fk_branches_branch_manager_id_employees"), ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_branches")),
        sa.UniqueConstraint("company_id", "code", name="uq_branches_company_code"),
    )

    # Add foreign keys from employees to branches and legal_entities
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing_columns = [c['name'] for c in inspector.get_columns('employees')]

    if 'branch_id' not in existing_columns:
        op.add_column('employees', sa.Column('branch_id', _uuid(), nullable=True))
    if 'legal_entity_id' not in existing_columns:
        op.add_column('employees', sa.Column('legal_entity_id', _uuid(), nullable=True))

    # Add foreign keys
    op.create_foreign_key(
        "fk_employees_branch_id_branches", "employees", "branches",
        ["branch_id"], ["id"], ondelete="SET NULL"
    )
    op.create_foreign_key(
        "fk_employees_legal_entity_id_legal_entities", "employees", "legal_entities",
        ["legal_entity_id"], ["id"], ondelete="SET NULL"
    )

    # Add indexes
    op.create_index("ix_employees_branch_id", "employees", ["branch_id"], unique=False)
    op.create_index("ix_employees_legal_entity_id", "employees", ["legal_entity_id"], unique=False)
    op.create_index("ix_branches_company_id", "branches", ["company_id"], unique=False)
    op.create_index("ix_branches_legal_entity_id", "branches", ["legal_entity_id"], unique=False)
    op.create_index("ix_legal_entities_company_id", "legal_entities", ["company_id"], unique=False)


def downgrade() -> None:
    # Drop foreign keys and columns from employees
    op.drop_constraint("fk_employees_legal_entity_id_legal_entities", "employees", type_="foreignkey")
    op.drop_constraint("fk_employees_branch_id_branches", "employees", type_="foreignkey")
    op.drop_index("ix_employees_legal_entity_id", table_name="employees")
    op.drop_index("ix_employees_branch_id", table_name="employees")

    # Drop columns from employees
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing_columns = [c['name'] for c in inspector.get_columns('employees')]
    for col_name in ['branch_id', 'legal_entity_id']:
        if col_name in existing_columns:
            op.drop_column('employees', col_name)

    # Drop indexes
    op.drop_index("ix_branches_company_id", table_name="branches")
    op.drop_index("ix_branches_legal_entity_id", table_name="branches")
    op.drop_index("ix_legal_entities_company_id", table_name="legal_entities")

    # Drop tables
    op.drop_table("branches")
    op.drop_table("legal_entities")