"""add viewer-critical indexes

Revision ID: 0004
Revises: 0003
Create Date: 2026-03-31
"""
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("ix_hands_table_status", "hands", ["table_id", "status"])
    op.create_index("ix_hands_table_id_desc", "hands", ["table_id", op.f("id")], postgresql_ops={"id": "DESC"})
    op.create_index("ix_hand_actions_hand_seq", "hand_actions", ["hand_id", "seq"])
    op.create_index("ix_hand_players_hand", "hand_players", ["hand_id"])
    op.create_index("ix_chip_ledger_account_reason", "chip_ledger", ["account_id", "reason_type"])


def downgrade() -> None:
    op.drop_index("ix_chip_ledger_account_reason", table_name="chip_ledger")
    op.drop_index("ix_hand_players_hand", table_name="hand_players")
    op.drop_index("ix_hand_actions_hand_seq", table_name="hand_actions")
    op.drop_index("ix_hands_table_id_desc", table_name="hands")
    op.drop_index("ix_hands_table_status", table_name="hands")
