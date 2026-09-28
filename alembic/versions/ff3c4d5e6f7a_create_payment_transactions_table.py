"""create payment_transactions table for Razorpay integration

Revision ID: ff3c4d5e6f7a
Revises: ff2c3d4e5f6a
Create Date: 2026-08-24 13:40:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'ff3c4d5e6f7a'
down_revision: Union[str, None] = 'ff2c3d4e5f6a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = inspector.get_table_names()

    if "payment_transactions" not in tables:
        op.create_table(
            'payment_transactions',
            sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column('company_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('companies.id', ondelete='CASCADE'), nullable=False),
            sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
            sa.Column('plan_id', sa.String(length=100), nullable=False),
            sa.Column('billing_cycle', sa.String(length=50), nullable=False, server_default='monthly'),
            sa.Column('razorpay_order_id', sa.String(length=100), nullable=False),
            sa.Column('razorpay_payment_id', sa.String(length=100), nullable=True),
            sa.Column('razorpay_signature', sa.String(length=255), nullable=True),
            sa.Column('amount', sa.Float(), nullable=False),
            sa.Column('amount_paise', sa.Integer(), nullable=False),
            sa.Column('currency', sa.String(length=10), nullable=False, server_default='INR'),
            sa.Column('status', sa.String(length=50), nullable=False, server_default='CREATED'),
            sa.Column('payment_method', sa.String(length=50), nullable=True),
            sa.Column('failure_reason', sa.Text(), nullable=True),
            sa.Column('payment_metadata', sa.JSON(), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
            sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        )
        op.create_index('ix_payment_transactions_company_id', 'payment_transactions', ['company_id'])
        op.create_index('ix_payment_transactions_user_id', 'payment_transactions', ['user_id'])
        op.create_index('ix_payment_transactions_razorpay_order_id', 'payment_transactions', ['razorpay_order_id'], unique=True)
        op.create_index('ix_payment_transactions_razorpay_payment_id', 'payment_transactions', ['razorpay_payment_id'], unique=True)
        op.create_index('ix_payment_transactions_status', 'payment_transactions', ['status'])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = inspector.get_table_names()

    if "payment_transactions" in tables:
        op.drop_index('ix_payment_transactions_status', table_name='payment_transactions')
        op.drop_index('ix_payment_transactions_razorpay_payment_id', table_name='payment_transactions')
        op.drop_index('ix_payment_transactions_razorpay_order_id', table_name='payment_transactions')
        op.drop_index('ix_payment_transactions_user_id', table_name='payment_transactions')
        op.drop_index('ix_payment_transactions_company_id', table_name='payment_transactions')
        op.drop_table('payment_transactions')
