"""add_missing_payslip_columns

Revision ID: f9a8b7c6d5e4
Revises: f8b9c0d1e2f3
Create Date: 2026-07-21 15:15:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'f9a8b7c6d5e4'
down_revision = 'f8b9c0d1e2f3'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('payslips', sa.Column('email_status', sa.String(length=20), server_default=sa.text("'NOT_SENT'"), nullable=False))
    op.add_column('payslips', sa.Column('email_sent_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('payslips', sa.Column('download_count', sa.Integer(), server_default=sa.text('0'), nullable=False))
    op.add_column('payslips', sa.Column('view_count', sa.Integer(), server_default=sa.text('0'), nullable=False))


def downgrade() -> None:
    op.drop_column('payslips', 'view_count')
    op.drop_column('payslips', 'download_count')
    op.drop_column('payslips', 'email_sent_at')
    op.drop_column('payslips', 'email_status')
