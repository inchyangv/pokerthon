"""add bot models

Revision ID: 0002
Revises: 0001
Create Date: 2026-03-21
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0002"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add is_bot column to accounts
    op.add_column(
        "accounts",
        sa.Column("is_bot", sa.Boolean(), nullable=False, server_default=sa.false()),
    )

    # Create bot_profiles table
    op.create_table(
        "bot_profiles",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("bot_type", sa.String(16), nullable=False),
        sa.Column("display_name", sa.String(64), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("config_json", postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("account_id"),
        sa.CheckConstraint("bot_type IN ('TAG', 'LAG', 'FISH')", name="ck_bot_type"),
    )


def downgrade() -> None:
    op.drop_table("bot_profiles")
    op.drop_column("accounts", "is_bot")
