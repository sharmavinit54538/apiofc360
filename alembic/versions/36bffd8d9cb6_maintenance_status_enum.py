"""maintenance_status_enum

Revision ID: 36bffd8d9cb6
Revises: 36bffd8d9cb5
Create Date: 2026-11-15

Create the maintenance_status enum type that was missing from the database.

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '36bffd8d9cb6'
down_revision: Union[str, None] = '36bffd8d9cb5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create the maintenance_status enum type
    op.execute("CREATE TYPE maintenance_status AS ENUM ('REQUESTED', 'IN_PROGRESS', 'COMPLETED', 'CANCELLED')")


def downgrade() -> None:
    # Drop the enum type
    op.execute("DROP TYPE IF EXISTS maintenance_status")