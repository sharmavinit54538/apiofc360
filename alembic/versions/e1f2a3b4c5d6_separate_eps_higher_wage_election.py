"""Separate EPS eligibility and higher-wage elections from EPF settings.

Revision ID: e1f2a3b4c5d6
Revises: d4e5f6a7b8c9, 915a_payroll_processing_lease
Create Date: 2026-11-15
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "e1f2a3b4c5d6"
down_revision: Union[str, tuple[str, str], None] = (
    "d4e5f6a7b8c9",
    "915a_payroll_processing_lease",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "employees",
        sa.Column("is_eps_eligible", sa.Boolean(), server_default=sa.text("true"), nullable=False),
    )
    op.add_column(
        "employees",
        sa.Column("eps_higher_wage_opted", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("employees", "eps_higher_wage_opted")
    op.drop_column("employees", "is_eps_eligible")
