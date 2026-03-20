"""add home_table_no to bot_profiles

Revision ID: 0003
Revises: 0002
Create Date: 2026-03-21
"""
from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("bot_profiles", sa.Column("home_table_no", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("bot_profiles", "home_table_no")
