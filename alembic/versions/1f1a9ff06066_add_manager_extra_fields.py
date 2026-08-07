"""add_manager_extra_fields

Revision ID: 1f1a9ff06066
Revises: 9449fdcd34d5
Create Date: 2026-07-02 09:49:17.141582

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '1f1a9ff06066'
down_revision: Union[str, None] = '9449fdcd34d5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('managers', sa.Column('is_first_login', sa.Boolean(), server_default=sa.text('true'), nullable=False))
    op.add_column('managers', sa.Column('profile_completed', sa.Boolean(), server_default=sa.text('false'), nullable=False))
    op.add_column('managers', sa.Column('last_login', sa.DateTime(timezone=True), nullable=True))
    op.add_column('managers', sa.Column('office_location', sa.String(length=100), nullable=True))
    op.add_column('managers', sa.Column('reporting_to', sa.UUID(), nullable=True))
    op.add_column('managers', sa.Column('avatar', sa.String(length=500), nullable=True))
    op.add_column('managers', sa.Column('bio', sa.String(length=500), nullable=True))
    op.add_column('managers', sa.Column('timezone', sa.String(length=100), nullable=True))
    op.add_column('managers', sa.Column('language', sa.String(length=50), nullable=True))
    
    op.create_foreign_key(
        'fk_managers_reporting_to_managers',
        'managers', 'managers',
        ['reporting_to'], ['id'],
        ondelete='SET NULL'
    )


def downgrade() -> None:
    op.drop_constraint('fk_managers_reporting_to_managers', 'managers', type_='foreignkey')
    op.drop_column('managers', 'language')
    op.drop_column('managers', 'timezone')
    op.drop_column('managers', 'bio')
    op.drop_column('managers', 'avatar')
    op.drop_column('managers', 'reporting_to')
    op.drop_column('managers', 'office_location')
    op.drop_column('managers', 'last_login')
    op.drop_column('managers', 'profile_completed')
    op.drop_column('managers', 'is_first_login')
