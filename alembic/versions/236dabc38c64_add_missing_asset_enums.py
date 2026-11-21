"""add_missing_asset_enums

Revision ID: 236dabc38c64
Revises: 4b2891fdd6b8
Create Date: 2026-11-16 10:05:28.249363

Create the missing enum types for maintenance_status, asset_request_type,
and asset_request_status that are used by the Asset models but were not
created in the database because the database was stamped past the migrations
that should have created them.

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '236dabc38c64'
down_revision: Union[str, None] = '4b2891fdd6b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create maintenance_status enum (idempotent)
    op.execute("DO $$ BEGIN CREATE TYPE maintenance_status AS ENUM ('REQUESTED', 'IN_PROGRESS', 'COMPLETED', 'CANCELLED'); EXCEPTION WHEN duplicate_object THEN NULL; END $$;")
    
    # Create asset_request_type enum (idempotent)
    op.execute("DO $$ BEGIN CREATE TYPE asset_request_type AS ENUM ('NEW_ASSET', 'REPLACEMENT', 'PERIPHERAL', 'UPGRADE', 'ACCESSORY'); EXCEPTION WHEN duplicate_object THEN NULL; END $$;")
    
    # Create asset_request_status enum (idempotent)
    op.execute("DO $$ BEGIN CREATE TYPE asset_request_status AS ENUM ('PENDING', 'APPROVED', 'REJECTED', 'FULFILLED', 'CANCELLED'); EXCEPTION WHEN duplicate_object THEN NULL; END $$;")


def downgrade() -> None:
    # Drop enum types (only if they exist and are not used)
    op.execute("DROP TYPE IF EXISTS asset_request_status")
    op.execute("DROP TYPE IF EXISTS asset_request_type")
    op.execute("DROP TYPE IF EXISTS maintenance_status")