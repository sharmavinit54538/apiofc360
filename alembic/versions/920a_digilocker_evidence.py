"""Persist DigiLocker state and authenticated provider evidence.

Revision ID: 920a_digilocker_evidence
Revises: 919a_backend_automation
"""
from alembic import op
import sqlalchemy as sa

revision = "920a_digilocker_evidence"
down_revision = "919a_backend_automation"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("document_verifications", sa.Column("extra_data", sa.JSON(), nullable=True))


def downgrade():
    op.drop_column("document_verifications", "extra_data")
