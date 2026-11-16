"""Repair remaining Employee encryption/storage and statutory nullability drift.

Revision ID: 41a_employee_schema_contract
Revises: 40d7b5c909b3

Earlier repair revisions already cover missing blind indexes and TEXT storage.
Recheck them for installations stamped past those revisions. Never decrypt or
rewrite PII in DDL. Run the controlled encrypted-PII backfill separately.
"""
from alembic import op
import sqlalchemy as sa

revision = "41a_employee_schema_contract"
down_revision = "40d7b5c909b3"
branch_labels = None
depends_on = None

FIELDS = {"aadhaar_number": "aadhaar", "pan_number": "pan", "uan_number": "uan",
          "passport_number": "passport", "voter_id": "voter"}
FLAGS = {"is_pf_eligible": "true", "is_international_worker": "false",
         "pf_wage_ceiling_applicable": "true"}


def upgrade():
    conn = op.get_bind()
    # Fail promptly rather than wait indefinitely for application traffic.
    op.execute("SET LOCAL lock_timeout = '5s'")
    columns = {c['name']: c for c in sa.inspect(conn).get_columns('employees')}
    for field, short in FIELDS.items():
        source = columns[field]
        if not isinstance(source['type'], sa.Text):
            if not isinstance(source['type'], sa.String):
                raise RuntimeError(f"Unexpected encrypted storage type for employees.{field}")
            op.alter_column('employees', field, existing_type=source['type'], type_=sa.Text())
        blind = f"{field}_blind_idx"
        existing = columns.get(blind)
        if existing is None:
            op.add_column('employees', sa.Column(blind, sa.String(64), nullable=True))
        elif (not isinstance(existing['type'], sa.String) or existing['type'].length != 64
              or not existing['nullable']):
            raise RuntimeError(f"Incompatible definition for employees.{blind}; manual review required")
        name = f"ix_employees_company_{short}_blind_idx"
        actual = next((i for i in sa.inspect(conn).get_indexes('employees') if i['name'] == name), None)
        if actual is None:
            op.create_index(name, 'employees', ['company_id', blind], unique=False)
        elif (actual['column_names'] != ['company_id', blind] or actual['unique']
              or actual.get('dialect_options', {}).get('postgresql_where')):
            raise RuntimeError(f"Incompatible index {name}; manual review required")
        valid = conn.execute(sa.text("SELECT indisvalid AND indisready FROM pg_index WHERE indexrelid = to_regclass(:name)"), {'name': name}).scalar_one()
        if not valid:
            raise RuntimeError(f"Index {name} is invalid; manual review required")

    for name, default in FLAGS.items():
        column = columns[name]
        if not isinstance(column['type'], sa.Boolean):
            raise RuntimeError(f"Unexpected type for employees.{name}")
        if column['nullable']:
            # NULL does not establish statutory eligibility. Require an operator
            # to resolve it from authoritative employee records, not a guess.
            count = conn.execute(sa.text(f'SELECT count(*) FROM employees WHERE {name} IS NULL')).scalar_one()
            if count:
                raise RuntimeError(f"employees.{name}: {count} NULL rows require explicit review before migration")
            op.alter_column('employees', name, existing_type=sa.Boolean(), nullable=False)
        op.alter_column('employees', name, existing_type=sa.Boolean(), server_default=sa.text(default))


def downgrade():
    # Repair-only revision: preserve data, ciphertext capacity, indexes and
    # constraints already required by the preceding application revision.
    pass
