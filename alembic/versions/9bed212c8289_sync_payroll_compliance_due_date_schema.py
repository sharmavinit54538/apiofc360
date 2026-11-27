"""sync payroll compliance due date schema

Revision ID: 9bed212c8289
Revises: b8f42a1e7d05
Create Date: 2026-11-27 10:26:04.111999

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9bed212c8289'
down_revision: Union[str, None] = 'b8f42a1e7d05'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE_NAME = "payroll_compliance_due_dates"
INDEX_NAME = "ix_payroll_compliance_due_dates_company"


def upgrade() -> None:
    """Safely synchronize payroll_compliance_due_dates columns, constraints, and index."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if TABLE_NAME not in inspector.get_table_names():
        raise RuntimeError(f"Expected table '{TABLE_NAME}' does not exist.")

    cols = {col["name"]: col for col in inspector.get_columns(TABLE_NAME)}
    indexes = {idx["name"] for idx in inspector.get_indexes(TABLE_NAME)}

    # 1. Safely add filing_frequency (nullable first), backfill from verified rules, validate, then enforce NOT NULL.
    if "filing_frequency" not in cols:
        op.add_column(
            TABLE_NAME,
            sa.Column("filing_frequency", sa.String(length=20), nullable=True),
        )
        # Backfill linked rows directly from parent payroll_compliance rule.
        bind.execute(
            sa.text(
                """
                UPDATE payroll_compliance_due_dates AS d
                SET filing_frequency = pc.filing_frequency
                FROM payroll_compliance AS pc
                WHERE d.compliance_id = pc.id
                  AND d.filing_frequency IS NULL
                  AND pc.filing_frequency IS NOT NULL
                """
            )
        )
        # Backfill verified monthly statutory EPFO PF & ECR due-date rows created without compliance_id FK.
        bind.execute(
            sa.text(
                """
                UPDATE payroll_compliance_due_dates
                SET filing_frequency = 'MONTHLY'
                WHERE compliance_id IS NULL
                  AND filing_frequency IS NULL
                  AND (
                    title ILIKE 'EPFO PF & ECR Filing%'
                    OR (
                      period_month BETWEEN 1 AND 12
                      AND due_date = (
                        make_date(period_year, period_month, 1)
                        + INTERVAL '1 month'
                        + INTERVAL '14 days'
                      )::date
                    )
                  )
                """
            )
        )
        null_count = bind.execute(
            sa.text("SELECT COUNT(*) FROM payroll_compliance_due_dates WHERE filing_frequency IS NULL")
        ).scalar_one()
        if null_count > 0:
            raise RuntimeError(
                f"Refusing to enforce NOT NULL on {TABLE_NAME}.filing_frequency: "
                f"{null_count} existing row(s) could not be matched to a verified statutory filing frequency."
            )
        op.alter_column(
            TABLE_NAME,
            "filing_frequency",
            existing_type=sa.String(length=20),
            nullable=False,
            server_default=sa.text("'MONTHLY'"),
        )
    else:
        col_info = cols["filing_frequency"]
        if col_info.get("nullable", True):
            null_count = bind.execute(
                sa.text("SELECT COUNT(*) FROM payroll_compliance_due_dates WHERE filing_frequency IS NULL")
            ).scalar_one()
            if null_count == 0:
                op.alter_column(
                    TABLE_NAME,
                    "filing_frequency",
                    existing_type=sa.String(length=20),
                    nullable=False,
                    server_default=sa.text("'MONTHLY'"),
                )

    # 2. Add remaining nullable ORM metadata columns if absent.
    if "filed_at" not in cols:
        op.add_column(
            TABLE_NAME,
            sa.Column("filed_at", sa.DateTime(timezone=True), nullable=True),
        )
    if "filing_reference" not in cols:
        op.add_column(
            TABLE_NAME,
            sa.Column("filing_reference", sa.String(length=150), nullable=True),
        )
    if "remarks" not in cols:
        op.add_column(
            TABLE_NAME,
            sa.Column("remarks", sa.String(length=500), nullable=True),
        )

    # 3. Align created_at / updated_at nullability with ORM after verifying zero NULLs.
    for ts_col in ("created_at", "updated_at"):
        if ts_col in cols and cols[ts_col].get("nullable", True):
            ts_nulls = bind.execute(
                sa.text(f"SELECT COUNT(*) FROM {TABLE_NAME} WHERE {ts_col} IS NULL")
            ).scalar_one()
            if ts_nulls > 0:
                raise RuntimeError(f"Cannot set {TABLE_NAME}.{ts_col} NOT NULL: {ts_nulls} NULL row(s) found.")
            op.alter_column(
                TABLE_NAME,
                ts_col,
                existing_type=sa.DateTime(timezone=True),
                nullable=False,
                existing_server_default=sa.text("now()"),
            )

    # 4. Ensure composite company/period index defined on ComplianceDueDate exists.
    if INDEX_NAME not in indexes:
        op.create_index(
            INDEX_NAME,
            TABLE_NAME,
            ["company_id", "period_year", "period_month"],
            unique=False,
        )


def downgrade() -> None:
    """Safely revert compliance due-date schema synchronization."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if TABLE_NAME not in inspector.get_table_names():
        return

    cols = {col["name"]: col for col in inspector.get_columns(TABLE_NAME)}
    indexes = {idx["name"] for idx in inspector.get_indexes(TABLE_NAME)}

    if INDEX_NAME in indexes:
        op.drop_index(INDEX_NAME, table_name=TABLE_NAME)
    for col_name in ("remarks", "filing_reference", "filed_at", "filing_frequency"):
        if col_name in cols:
            op.drop_column(TABLE_NAME, col_name)
