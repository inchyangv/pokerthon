"""initial schema — all tables

Revision ID: 0001
Revises:
Create Date: 2026-03-21
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # accounts
    op.create_table(
        "accounts",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("nickname", sa.String(64), nullable=False),
        sa.Column("status", sa.Enum("ACTIVE", "BLOCKED", name="accountstatus"), nullable=False, server_default="ACTIVE"),
        sa.Column("wallet_balance", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_bot", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("nickname", name="uq_accounts_nickname"),
    )

    # api_credentials
    op.create_table(
        "api_credentials",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("api_key", sa.String(128), nullable=False),
        sa.Column("secret_hash", sa.String(256), nullable=False),
        sa.Column("status", sa.Enum("ACTIVE", "REVOKED", name="credentialstatus"), nullable=False, server_default="ACTIVE"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("api_key", name="uq_api_credentials_api_key"),
    )

    # api_nonces
    op.create_table(
        "api_nonces",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("api_key", sa.String(128), nullable=False, index=True),
        sa.Column("nonce", sa.String(64), nullable=False),
        sa.Column("timestamp", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("api_key", "nonce", name="uq_api_nonces_key_nonce"),
    )

    # chip_ledger
    op.create_table(
        "chip_ledger",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("delta", sa.Integer(), nullable=False),
        sa.Column("balance_after", sa.Integer(), nullable=False),
        sa.Column(
            "reason_type",
            sa.Enum(
                "ADMIN_GRANT", "ADMIN_DEDUCT", "TABLE_BUYIN", "TABLE_CASHOUT",
                "HAND_WIN", "HAND_LOSS", "MANUAL_ADJUST",
                name="ledgerreasontype",
            ),
            nullable=False,
        ),
        sa.Column("reason_text", sa.String(256), nullable=True),
        sa.Column("ref_type", sa.String(64), nullable=True),
        sa.Column("ref_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    # tables
    op.create_table(
        "tables",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("table_no", sa.Integer(), nullable=False),
        sa.Column("status", sa.Enum("OPEN", "PAUSED", "CLOSED", name="tablestatus"), nullable=False, server_default="OPEN"),
        sa.Column("max_seats", sa.Integer(), nullable=False, server_default="9"),
        sa.Column("small_blind", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("big_blind", sa.Integer(), nullable=False, server_default="2"),
        sa.Column("buy_in", sa.Integer(), nullable=False, server_default="40"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("table_no", name="uq_tables_table_no"),
    )

    # table_seats
    op.create_table(
        "table_seats",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("table_id", sa.Integer(), sa.ForeignKey("tables.id"), nullable=False),
        sa.Column("seat_no", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("accounts.id"), nullable=True),
        sa.Column(
            "seat_status",
            sa.Enum("EMPTY", "SEATED", "LEAVING_AFTER_HAND", name="seatstatus"),
            nullable=False,
            server_default="EMPTY",
        ),
        sa.Column("stack", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("joined_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("table_id", "seat_no", name="uq_table_seat"),
    )

    # hands
    op.create_table(
        "hands",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("table_id", sa.Integer(), sa.ForeignKey("tables.id"), nullable=False),
        sa.Column("hand_no", sa.Integer(), nullable=False),
        sa.Column("status", sa.Enum("IN_PROGRESS", "FINISHED", name="handstatus"), nullable=False, server_default="IN_PROGRESS"),
        sa.Column("button_seat_no", sa.Integer(), nullable=True),
        sa.Column("small_blind_seat_no", sa.Integer(), nullable=True),
        sa.Column("big_blind_seat_no", sa.Integer(), nullable=True),
        sa.Column("street", sa.String(16), nullable=True),
        sa.Column("board_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("deck_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("current_bet", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("action_seat_no", sa.Integer(), nullable=True),
        sa.Column("action_deadline_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deal_index", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )

    # hand_players
    op.create_table(
        "hand_players",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("hand_id", sa.Integer(), sa.ForeignKey("hands.id"), nullable=False),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("seat_no", sa.Integer(), nullable=False),
        sa.Column("hole_cards_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("starting_stack", sa.Integer(), nullable=False),
        sa.Column("ending_stack", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("folded", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("all_in", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("round_contribution", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("hand_contribution", sa.Integer(), nullable=False, server_default="0"),
        sa.PrimaryKeyConstraint("id"),
    )

    # hand_actions
    op.create_table(
        "hand_actions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("hand_id", sa.Integer(), sa.ForeignKey("hands.id"), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("street", sa.String(16), nullable=True),
        sa.Column("actor_account_id", sa.Integer(), nullable=True),
        sa.Column("actor_seat_no", sa.Integer(), nullable=True),
        sa.Column("action_type", sa.String(32), nullable=False),
        sa.Column("amount", sa.Integer(), nullable=True),
        sa.Column("amount_to", sa.Integer(), nullable=True),
        sa.Column("payload_json", sa.Text(), nullable=True),
        sa.Column("is_system_action", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    # hand_results
    op.create_table(
        "hand_results",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("hand_id", sa.Integer(), sa.ForeignKey("hands.id"), unique=True, nullable=False),
        sa.Column("result_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    # table_snapshots
    op.create_table(
        "table_snapshots",
        sa.Column("table_id", sa.Integer(), sa.ForeignKey("tables.id"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("snapshot_json", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("table_id"),
    )

    # bot_profiles
    op.create_table(
        "bot_profiles",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("bot_type", sa.String(16), nullable=False),
        sa.Column("display_name", sa.String(64), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("config_json", postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("account_id"),
        sa.CheckConstraint("bot_type IN ('TAG', 'LAG', 'FISH')", name="ck_bot_type"),
    )


def downgrade() -> None:
    op.drop_table("bot_profiles")
    op.drop_table("table_snapshots")
    op.drop_table("hand_results")
    op.drop_table("hand_actions")
    op.drop_table("hand_players")
    op.drop_table("hands")
    op.drop_table("table_seats")
    op.drop_table("tables")
    op.drop_table("chip_ledger")
    op.drop_table("api_nonces")
    op.drop_table("api_credentials")
    op.drop_table("accounts")
    op.execute("DROP TYPE IF EXISTS accountstatus")
    op.execute("DROP TYPE IF EXISTS credentialstatus")
    op.execute("DROP TYPE IF EXISTS ledgerreasontype")
    op.execute("DROP TYPE IF EXISTS tablestatus")
    op.execute("DROP TYPE IF EXISTS seatstatus")
    op.execute("DROP TYPE IF EXISTS handstatus")
