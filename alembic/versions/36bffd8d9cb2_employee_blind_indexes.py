"""employee_blind_indexes

Revision ID: 36bffd8d9cb2
Revises: 36bffd8d9cb1
Create Date: 2026-11-15

Add missing Employee PII blind index columns and indexes that were supposed to be
added by revision 905a_dpdp_field_encryption but were not applied because the
database was stamped to a later revision without running that migration.

This migration adds blind index columns for encrypted Employee PII fields and
creates the corresponding composite indexes with company_id.

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '36bffd8d9cb2'
down_revision: Union[str, None] = '36bffd8d9cb1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_EMPLOYEE_PII_FIELDS = {
    "aadhaar_number": "aadhaar_number_blind_idx",
    "pan_number": "pan_number_blind_idx",
    "uan_number": "uan_number_blind_idx",
    "passport_number": "passport_number_blind_idx",
    "voter_id": "voter_id_blind_idx",
}


def upgrade() -> None:
    # Add blind index columns if they don't exist
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing_columns = [c['name'] for c in inspector.get_columns('employees')]

    for field_name, blind_name in _EMPLOYEE_PII_FIELDS.items():
        if blind_name not in existing_columns:
            op.add_column('employees', sa.Column(blind_name, sa.String(length=64), nullable=True))

    # Create composite indexes with company_id
    indexes_to_create = [
        ("ix_employees_company_aadhaar_blind_idx", "aadhaar_number_blind_idx"),
        ("ix_employees_company_pan_blind_idx", "pan_number_blind_idx"),
        ("ix_employees_company_uan_blind_idx", "uan_number_blind_idx"),
        ("ix_employees_company_passport_blind_idx", "passport_number_blind_idx"),
        ("ix_employees_company_voter_blind_idx", "voter_id_blind_idx"),
    ]

    for index_name, column_name in indexes_to_create:
        # Check if index already exists
        indexes = inspector.get_indexes('employees')
        existing_index_names = [idx['name'] for idx in indexes]
        if index_name not in existing_index_names:
            op.create_index(index_name, 'employees', ['company_id', column_name], unique=False)


def downgrade() -> None:
    # Drop indexes
    for index_name, _ in [
        ("ix_employees_company_aadhaar_blind_idx", "aadhaar_number_blind_idx"),
        ("ix_employees_company_pan_blind_idx", "pan_number_blind_idx"),
        ("ix_employees_company_uan_blind_idx", "uan_number_blind_idx"),
        ("ix_employees_company_passport_blind_idx", "passport_number_blind_idx"),
        ("ix_employees_company_voter_blind_idx", "voter_id_blind_idx"),
    ]:
        conn = op.get_bind()
        inspector = sa.inspect(conn)
        indexes = inspector.get_indexes('employees')
        existing_index_names = [idx['name'] for idx in indexes]
        if index_name in existing_index_names:
            op.drop_index(index_name, table_name='employees')

    # Drop blind index columns
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing_columns = [c['name'] for c in inspector.get_columns('employees')]

    for blind_name in _EMPLOYEE_PII_FIELDS.values():
        if blind_name in existing_columns:
            op.drop_column('employees', blind_name)