"""add small_blind_amount and big_blind_amount to hands

Revision ID: 0005
Revises: 0004
Create Date: 2026-03-31
"""
import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("hands", sa.Column("small_blind_amount", sa.Integer(), nullable=False, server_default="1"))
    op.add_column("hands", sa.Column("big_blind_amount", sa.Integer(), nullable=False, server_default="2"))


def downgrade() -> None:
    op.drop_column("hands", "big_blind_amount")
    op.drop_column("hands", "small_blind_amount")
