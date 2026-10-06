"""add rotated_at and replaced_by to refresh_tokens

Revision ID: e1f2a3b4c5d6
Revises: d7e8f9a0b1c2
Create Date: 2026-10-02 22:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e1f2a3b4c5d6'
down_revision: Union[str, None] = 'd7e8f9a0b1c2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    insp = sa.inspect(conn)
    columns = [c['name'] for c in insp.get_columns('refresh_tokens')]

    if 'rotated_at' not in columns:
        op.add_column('refresh_tokens', sa.Column('rotated_at', sa.DateTime(timezone=True), nullable=True))
    if 'replaced_by' not in columns:
        op.add_column('refresh_tokens', sa.Column('replaced_by', sa.String(length=255), nullable=True))


def downgrade() -> None:
    conn = op.get_bind()
    insp = sa.inspect(conn)
    columns = [c['name'] for c in insp.get_columns('refresh_tokens')]

    if 'replaced_by' in columns:
        op.drop_column('refresh_tokens', 'replaced_by')
    if 'rotated_at' in columns:
        op.drop_column('refresh_tokens', 'rotated_at')
