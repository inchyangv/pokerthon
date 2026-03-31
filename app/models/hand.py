import enum
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class HandStatus(str, enum.Enum):
    IN_PROGRESS = "IN_PROGRESS"
    FINISHED = "FINISHED"


class StreetType(str, enum.Enum):
    PREFLOP = "preflop"
    FLOP = "flop"
    TURN = "turn"
    RIVER = "river"
    SHOWDOWN = "showdown"


class Hand(Base):
    __tablename__ = "hands"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    table_id: Mapped[int] = mapped_column(Integer, ForeignKey("tables.id"), nullable=False)
    hand_no: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[HandStatus] = mapped_column(Enum(HandStatus), default=HandStatus.IN_PROGRESS, nullable=False)
    button_seat_no: Mapped[int | None] = mapped_column(Integer, nullable=True)
    small_blind_seat_no: Mapped[int | None] = mapped_column(Integer, nullable=True)
    big_blind_seat_no: Mapped[int | None] = mapped_column(Integer, nullable=True)
    street: Mapped[str | None] = mapped_column(String(16), nullable=True)
    board_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    deck_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    current_bet: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    action_seat_no: Mapped[int | None] = mapped_column(Integer, nullable=True)
    action_deadline_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deal_index: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    small_blind_amount: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    big_blind_amount: Mapped[int] = mapped_column(Integer, default=2, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    table: Mapped["Table"] = relationship(back_populates="hands")
    players: Mapped[list["HandPlayer"]] = relationship(back_populates="hand", order_by="HandPlayer.seat_no")
    actions: Mapped[list["HandAction"]] = relationship(back_populates="hand", order_by="HandAction.seq")
    result: Mapped["HandResult | None"] = relationship(back_populates="hand", uselist=False)


class HandPlayer(Base):
    __tablename__ = "hand_players"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    hand_id: Mapped[int] = mapped_column(Integer, ForeignKey("hands.id"), nullable=False)
    account_id: Mapped[int] = mapped_column(Integer, ForeignKey("accounts.id"), nullable=False)
    seat_no: Mapped[int] = mapped_column(Integer, nullable=False)
    hole_cards_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    starting_stack: Mapped[int] = mapped_column(Integer, nullable=False)
    ending_stack: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    folded: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    all_in: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    round_contribution: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    hand_contribution: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    hand: Mapped["Hand"] = relationship(back_populates="players")
    account: Mapped["Account"] = relationship()


class HandAction(Base):
    __tablename__ = "hand_actions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    hand_id: Mapped[int] = mapped_column(Integer, ForeignKey("hands.id"), nullable=False)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    street: Mapped[str | None] = mapped_column(String(16), nullable=True)
    actor_account_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    actor_seat_no: Mapped[int | None] = mapped_column(Integer, nullable=True)
    action_type: Mapped[str] = mapped_column(String(32), nullable=False)
    amount: Mapped[int | None] = mapped_column(Integer, nullable=True)
    amount_to: Mapped[int | None] = mapped_column(Integer, nullable=True)
    payload_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_system_action: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    hand: Mapped["Hand"] = relationship(back_populates="actions")


class HandResult(Base):
    __tablename__ = "hand_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    hand_id: Mapped[int] = mapped_column(Integer, ForeignKey("hands.id"), unique=True, nullable=False)
    result_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    hand: Mapped["Hand"] = relationship(back_populates="result")


class TableSnapshot(Base):
    __tablename__ = "table_snapshots"

    table_id: Mapped[int] = mapped_column(Integer, ForeignKey("tables.id"), primary_key=True)
    version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    snapshot_json: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    table: Mapped["Table"] = relationship(back_populates="snapshot")
