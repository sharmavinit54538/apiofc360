"""widen_pii_columns

Revision ID: 36bffd8d9cb3
Revises: 36bffd8d9cb2
Create Date: 2026-11-15

Widen Employee PII columns to TEXT type to accommodate encrypted values.
This was supposed to be done by revision 905a_dpdp_field_encryption but
was not applied because the database was stamped to a later revision.

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '36bffd8d9cb3'
down_revision: Union[str, None] = '36bffd8d9cb2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_EMPLOYEE_PII_TYPES = {
    "aadhaar_number": sa.String(length=20),
    "pan_number": sa.String(length=10),
    "uan_number": sa.String(length=12),
    "passport_number": sa.String(length=20),
    "voter_id": sa.String(length=20),
}


def upgrade() -> None:
    # Widen PII columns to TEXT to accommodate encrypted values
    for column_name, existing_type in _EMPLOYEE_PII_TYPES.items():
        op.alter_column('employees', column_name, existing_type=existing_type, type_=sa.Text(), existing_nullable=True)

    # Also widen bank account columns if needed
    op.alter_column(
        'employee_bank_accounts',
        'account_number',
        existing_type=sa.String(length=30),
        type_=sa.Text(),
        existing_nullable=False,
    )
    op.alter_column(
        'employee_bank_accounts',
        'ifsc_code',
        existing_type=sa.String(length=15),
        type_=sa.Text(),
        existing_nullable=False,
    )


def downgrade() -> None:
    # Revert PII columns to original types
    for column_name, original_type in _EMPLOYEE_PII_TYPES.items():
        op.alter_column('employees', column_name, existing_type=sa.Text(), type_=original_type, existing_nullable=True)

    # Revert bank account columns
    op.alter_column(
        'employee_bank_accounts', 'ifsc_code', existing_type=sa.Text(), type_=sa.String(length=15), existing_nullable=False
    )
    op.alter_column(
        'employee_bank_accounts', 'account_number', existing_type=sa.Text(), type_=sa.String(length=30), existing_nullable=False
    )