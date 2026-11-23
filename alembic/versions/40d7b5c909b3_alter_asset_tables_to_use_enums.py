"""alter_asset_tables_to_use_enums

Revision ID: 40d7b5c909b3
Revises: 236dabc38c64
Create Date: 2026-11-16 10:08:02.584988

Alter asset tables to use enum types instead of varchar for status columns.

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '40d7b5c909b3'
down_revision: Union[str, None] = '236dabc38c64'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Alter asset_maintenance_records.status to use maintenance_status enum
    # First drop the default, then alter the column, then add the default back
    op.execute("ALTER TABLE asset_maintenance_records ALTER COLUMN status DROP DEFAULT")
    op.execute("""
        ALTER TABLE asset_maintenance_records 
        ALTER COLUMN status TYPE maintenance_status 
        USING status::maintenance_status
    """)
    op.execute("ALTER TABLE asset_maintenance_records ALTER COLUMN status SET DEFAULT 'REQUESTED'::maintenance_status")
    
    # Alter asset_requests.request_type to use asset_request_type enum
    op.execute("""
        ALTER TABLE asset_requests 
        ALTER COLUMN request_type TYPE asset_request_type 
        USING request_type::asset_request_type
    """)
    
    # Alter asset_requests.status to use asset_request_status enum
    op.execute("ALTER TABLE asset_requests ALTER COLUMN status DROP DEFAULT")
    op.execute("""
        ALTER TABLE asset_requests 
        ALTER COLUMN status TYPE asset_request_status 
        USING status::asset_request_status
    """)
    op.execute("ALTER TABLE asset_requests ALTER COLUMN status SET DEFAULT 'PENDING'::asset_request_status")


def downgrade() -> None:
    # Revert asset_maintenance_records.status to varchar
    op.execute("ALTER TABLE asset_maintenance_records ALTER COLUMN status DROP DEFAULT")
    op.execute("""
        ALTER TABLE asset_maintenance_records 
        ALTER COLUMN status TYPE VARCHAR(30) 
        USING status::VARCHAR
    """)
    op.execute("ALTER TABLE asset_maintenance_records ALTER COLUMN status SET DEFAULT 'REQUESTED'")
    
    # Revert asset_requests.request_type to varchar
    op.execute("""
        ALTER TABLE asset_requests 
        ALTER COLUMN request_type TYPE VARCHAR(50) 
        USING request_type::VARCHAR
    """)
    
    # Revert asset_requests.status to varchar
    op.execute("ALTER TABLE asset_requests ALTER COLUMN status DROP DEFAULT")
    op.execute("""
        ALTER TABLE asset_requests 
        ALTER COLUMN status TYPE VARCHAR(30) 
        USING status::VARCHAR
    """)
    op.execute("ALTER TABLE asset_requests ALTER COLUMN status SET DEFAULT 'PENDING'")