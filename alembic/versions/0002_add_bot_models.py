"""add bot models (no-op: already in 0001_initial)

Revision ID: 0002
Revises: 0001
Create Date: 2026-03-21
"""
from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # bot_profiles and is_bot column are included in the 0001 initial migration.
    pass


def downgrade() -> None:
    pass
