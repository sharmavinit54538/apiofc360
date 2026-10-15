"""add ai message metadata

Revision ID: 31a2b3c4d5e8
Revises: 2329529ee821
Create Date: 2026-10-15 16:45:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '31a2b3c4d5e8'
down_revision: Union[str, None] = '2329529ee821'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Use execute to safely add column if it does not already exist
    op.execute(
        "ALTER TABLE ai_messages ADD COLUMN IF NOT EXISTS message_metadata JSONB"
    )


def downgrade() -> None:
    op.drop_column('ai_messages', 'message_metadata')
