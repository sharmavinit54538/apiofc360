"""Add company_id to assets table with backfill and tenant scoping.

Revision ID: e2a3b4c5d6e7
Revises: d1a2b3c4d5e7
Create Date: 2026-09-29 12:50:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'e2a3b4c5d6e7'
down_revision = 'd1a2b3c4d5e7'
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if 'assets' in tables:
        cols = {c['name'] for c in inspector.get_columns('assets')}
        
        # 1. Add company_id column as nullable first to allow backfill
        if 'company_id' not in cols:
            op.add_column('assets', sa.Column('company_id', postgresql.UUID(as_uuid=True), nullable=True))
        
        # 2. Backfill from assigned employee's company if available
        op.execute("""
            UPDATE assets a
            SET company_id = e.company_id
            FROM employees e
            WHERE a.employee_id = e.id AND a.company_id IS NULL;
        """)

        # 3. For any remaining orphan rows without employee link, assign to first company
        # to ensure NOT NULL constraint can be cleanly applied
        op.execute("""
            UPDATE assets
            SET company_id = (SELECT id FROM companies ORDER BY created_at ASC LIMIT 1)
            WHERE company_id IS NULL AND EXISTS (SELECT 1 FROM companies);
        """)

        # 4. Alter to nullable=False
        op.alter_column('assets', 'company_id', nullable=False)

        # 5. Create foreign key constraint
        fks = {fk['name'] for fk in inspector.get_foreign_keys('assets')}
        if 'fk_assets_company_id_companies' not in fks:
            op.create_foreign_key(
                'fk_assets_company_id_companies',
                'assets',
                'companies',
                ['company_id'],
                ['id'],
                ondelete='CASCADE',
            )

        # 6. Create index
        indexes = {idx['name'] for idx in inspector.get_indexes('assets')}
        if 'ix_assets_company_id' not in indexes:
            op.create_index('ix_assets_company_id', 'assets', ['company_id'])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if 'assets' in tables:
        indexes = {idx['name'] for idx in inspector.get_indexes('assets')}
        if 'ix_assets_company_id' in indexes:
            op.drop_index('ix_assets_company_id', table_name='assets')

        fks = {fk['name'] for fk in inspector.get_foreign_keys('assets')}
        if 'fk_assets_company_id_companies' in fks:
            op.drop_constraint('fk_assets_company_id_companies', 'assets', type_='foreignkey')

        cols = {c['name'] for c in inspector.get_columns('assets')}
        if 'company_id' in cols:
            op.drop_column('assets', 'company_id')
