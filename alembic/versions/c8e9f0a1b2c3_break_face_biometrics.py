"""add face verification and geofence columns to attendance_breaks

Revision ID: c8e9f0a1b2c3
Revises: b7e8d9c0a1f3
Create Date: 2026-10-01 20:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c8e9f0a1b2c3'
down_revision: Union[str, None] = 'b7e8d9c0a1f3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add face biometric proof and geolocation columns to attendance_breaks
    op.add_column('attendance_breaks', sa.Column('start_image_url', sa.String(length=500), nullable=True))
    op.add_column('attendance_breaks', sa.Column('end_image_url', sa.String(length=500), nullable=True))
    op.add_column('attendance_breaks', sa.Column('start_face_distance', sa.Float(), nullable=True))
    op.add_column('attendance_breaks', sa.Column('end_face_distance', sa.Float(), nullable=True))
    op.add_column('attendance_breaks', sa.Column('start_liveness_score', sa.Float(), nullable=True))
    op.add_column('attendance_breaks', sa.Column('end_liveness_score', sa.Float(), nullable=True))
    op.add_column('attendance_breaks', sa.Column('start_latitude', sa.Float(), nullable=True))
    op.add_column('attendance_breaks', sa.Column('start_longitude', sa.Float(), nullable=True))
    op.add_column('attendance_breaks', sa.Column('end_latitude', sa.Float(), nullable=True))
    op.add_column('attendance_breaks', sa.Column('end_longitude', sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column('attendance_breaks', 'end_longitude')
    op.drop_column('attendance_breaks', 'end_latitude')
    op.drop_column('attendance_breaks', 'start_longitude')
    op.drop_column('attendance_breaks', 'start_latitude')
    op.drop_column('attendance_breaks', 'end_liveness_score')
    op.drop_column('attendance_breaks', 'start_liveness_score')
    op.drop_column('attendance_breaks', 'end_face_distance')
    op.drop_column('attendance_breaks', 'start_face_distance')
    op.drop_column('attendance_breaks', 'end_image_url')
    op.drop_column('attendance_breaks', 'start_image_url')
