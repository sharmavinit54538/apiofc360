"""Add password reset table

Revision ID: 21cb61c4b06d
Revises: 1f1a9ff06066
Create Date: 2026-07-02 12:49:20.979399

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '21cb61c4b06d'
down_revision: Union[str, None] = '1f1a9ff06066'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create password_resets table
    op.create_table(
        'password_resets',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('user_id', sa.UUID(), nullable=False),
        sa.Column('role', sa.String(length=50), nullable=False),
        sa.Column('hashed_token', sa.String(length=64), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('used_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    # Create unique index on hashed_token
    op.create_index('ix_password_resets_hashed_token', 'password_resets', ['hashed_token'], unique=True)


def downgrade() -> None:
    op.drop_index('ix_password_resets_hashed_token', table_name='password_resets')
    op.drop_table('password_resets')
