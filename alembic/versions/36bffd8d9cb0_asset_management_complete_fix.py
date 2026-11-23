"""asset_management_complete_fix

Revision ID: 36bffd8d9cb0
Revises: e1f2a3b4c5d6
Create Date: 2026-11-15

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '36bffd8d9cb0'
down_revision: Union[str, None] = 'e1f2a3b4c5d6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Asset model changes
    # 1. Drop global unique index on tag, add composite unique index on (company_id, tag)
    op.drop_index('ix_assets_tag', table_name='assets')
    op.create_index('ix_assets_company_tag', 'assets', ['company_id', 'tag'], unique=True)
    
    # 2. Add soft deletion columns to assets
    op.add_column('assets', sa.Column('is_deleted', sa.Boolean(), server_default=sa.text('false'), nullable=False))
    op.add_column('assets', sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True))
    op.create_index('ix_assets_is_deleted', 'assets', ['is_deleted'], unique=False)
    
    # 3. Add lost asset tracking columns
    op.add_column('assets', sa.Column('lost_date', sa.Date(), nullable=True))
    op.add_column('assets', sa.Column('lost_reason', sa.Text(), nullable=True))
    op.add_column('assets', sa.Column('last_known_holder_id', sa.UUID(), sa.ForeignKey('employees.id', ondelete='SET NULL'), nullable=True))
    
    # 4. Change timeline column to use MutableList (no schema change needed, just SQLAlchemy behavior)
    
    # AssetMaintenanceRecord model changes
    # 5. Add new columns to asset_maintenance_records
    op.add_column('asset_maintenance_records', sa.Column('completion_date', sa.Date(), nullable=True))
    op.add_column('asset_maintenance_records', sa.Column('estimated_cost', sa.Numeric(precision=14, scale=2), nullable=True))
    op.add_column('asset_maintenance_records', sa.Column('completion_notes', sa.Text(), nullable=True))
    op.add_column('asset_maintenance_records', sa.Column('status', sa.String(length=30), server_default=sa.text("'REQUESTED'"), nullable=False))
    
    # 6. Create asset_requests table
    op.create_table('asset_requests',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('company_id', sa.UUID(), nullable=False),
        sa.Column('employee_id', sa.UUID(), nullable=False),
        sa.Column('request_type', sa.String(length=50), nullable=False),
        sa.Column('category', sa.String(length=50), nullable=False),
        sa.Column('justification', sa.Text(), nullable=False),
        sa.Column('preferred_brand', sa.String(length=100), nullable=True),
        sa.Column('preferred_model', sa.String(length=100), nullable=True),
        sa.Column('estimated_cost', sa.Float(), nullable=True),
        sa.Column('status', sa.String(length=30), server_default=sa.text("'PENDING'"), nullable=False),
        sa.Column('approver_id', sa.UUID(), nullable=True),
        sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('rejection_reason', sa.Text(), nullable=True),
        sa.Column('assigned_asset_id', sa.UUID(), nullable=True),
        sa.Column('fulfilled_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], name=op.f('fk_asset_requests_company_id_companies'), ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['employee_id'], ['employees.id'], name=op.f('fk_asset_requests_employee_id_employees'), ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['approver_id'], ['employees.id'], name=op.f('fk_asset_requests_approver_id_employees'), ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['assigned_asset_id'], ['assets.id'], name=op.f('fk_asset_requests_assigned_asset_id_assets'), ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_asset_requests'))
    )
    op.create_index(op.f('ix_asset_requests_company_id'), 'asset_requests', ['company_id'], unique=False)
    op.create_index(op.f('ix_asset_requests_employee_id'), 'asset_requests', ['employee_id'], unique=False)
    op.create_index(op.f('ix_asset_requests_status'), 'asset_requests', ['status'], unique=False)
    
    # 7. Create asset_damage_reports table
    op.create_table('asset_damage_reports',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('company_id', sa.UUID(), nullable=False),
        sa.Column('asset_id', sa.UUID(), nullable=False),
        sa.Column('reported_by_id', sa.UUID(), nullable=False),
        sa.Column('damage_type', sa.String(length=50), nullable=False),
        sa.Column('severity', sa.String(length=20), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('location_of_incident', sa.String(length=200), nullable=True),
        sa.Column('incident_date', sa.Date(), nullable=True),
        sa.Column('status', sa.String(length=30), server_default=sa.text("'REPORTED'"), nullable=False),
        sa.Column('maintenance_record_id', sa.UUID(), nullable=True),
        sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('resolution_notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], name=op.f('fk_asset_damage_reports_company_id_companies'), ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['asset_id'], ['assets.id'], name=op.f('fk_asset_damage_reports_asset_id_assets'), ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['reported_by_id'], ['employees.id'], name=op.f('fk_asset_damage_reports_reported_by_id_employees'), ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['maintenance_record_id'], ['asset_maintenance_records.id'], name=op.f('fk_asset_damage_reports_maintenance_record_id_asset_maintenance_records'), ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_asset_damage_reports'))
    )
    op.create_index(op.f('ix_asset_damage_reports_company_id'), 'asset_damage_reports', ['company_id'], unique=False)
    op.create_index(op.f('ix_asset_damage_reports_asset_id'), 'asset_damage_reports', ['asset_id'], unique=False)
    op.create_index(op.f('ix_asset_damage_reports_reported_by_id'), 'asset_damage_reports', ['reported_by_id'], unique=False)
    op.create_index(op.f('ix_asset_damage_reports_status'), 'asset_damage_reports', ['status'], unique=False)


def downgrade() -> None:
    # Drop asset_damage_reports table
    op.drop_index(op.f('ix_asset_damage_reports_status'), table_name='asset_damage_reports')
    op.drop_index(op.f('ix_asset_damage_reports_reported_by_id'), table_name='asset_damage_reports')
    op.drop_index(op.f('ix_asset_damage_reports_asset_id'), table_name='asset_damage_reports')
    op.drop_index(op.f('ix_asset_damage_reports_company_id'), table_name='asset_damage_reports')
    op.drop_table('asset_damage_reports')
    
    # Drop asset_requests table
    op.drop_index(op.f('ix_asset_requests_status'), table_name='asset_requests')
    op.drop_index(op.f('ix_asset_requests_employee_id'), table_name='asset_requests')
    op.drop_index(op.f('ix_asset_requests_company_id'), table_name='asset_requests')
    op.drop_table('asset_requests')
    
    # Revert asset_maintenance_records changes
    op.drop_column('asset_maintenance_records', 'status')
    op.drop_column('asset_maintenance_records', 'completion_notes')
    op.drop_column('asset_maintenance_records', 'estimated_cost')
    op.drop_column('asset_maintenance_records', 'completion_date')
    
    # Revert assets changes
    op.drop_column('assets', 'last_known_holder_id')
    op.drop_column('assets', 'lost_reason')
    op.drop_column('assets', 'lost_date')
    op.drop_index('ix_assets_is_deleted', table_name='assets')
    op.drop_column('assets', 'deleted_at')
    op.drop_column('assets', 'is_deleted')
    
    # Restore global unique index on tag
    op.drop_index('ix_assets_company_tag', table_name='assets')
    op.create_index('ix_assets_tag', 'assets', ['tag'], unique=True)