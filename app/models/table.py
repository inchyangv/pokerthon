import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class TableStatus(str, enum.Enum):
    OPEN = "OPEN"
    PAUSED = "PAUSED"
    CLOSED = "CLOSED"


class SeatStatus(str, enum.Enum):
    EMPTY = "EMPTY"
    SEATED = "SEATED"
    LEAVING_AFTER_HAND = "LEAVING_AFTER_HAND"


class Table(Base):
    __tablename__ = "tables"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    table_no: Mapped[int] = mapped_column(Integer, unique=True, nullable=False)
    status: Mapped[TableStatus] = mapped_column(Enum(TableStatus), default=TableStatus.OPEN, nullable=False)
    max_seats: Mapped[int] = mapped_column(Integer, default=9, nullable=False)
    small_blind: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    big_blind: Mapped[int] = mapped_column(Integer, default=2, nullable=False)
    buy_in: Mapped[int] = mapped_column(Integer, default=40, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    seats: Mapped[list["TableSeat"]] = relationship(back_populates="table", order_by="TableSeat.seat_no")
    hands: Mapped[list["Hand"]] = relationship(back_populates="table")
    snapshot: Mapped["TableSnapshot | None"] = relationship(back_populates="table", uselist=False)


class TableSeat(Base):
    __tablename__ = "table_seats"
    __table_args__ = (UniqueConstraint("table_id", "seat_no", name="uq_table_seat"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    table_id: Mapped[int] = mapped_column(Integer, ForeignKey("tables.id"), nullable=False)
    seat_no: Mapped[int] = mapped_column(Integer, nullable=False)
    account_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("accounts.id"), nullable=True)
    seat_status: Mapped[SeatStatus] = mapped_column(Enum(SeatStatus), default=SeatStatus.EMPTY, nullable=False)
    stack: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    joined_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    table: Mapped["Table"] = relationship(back_populates="seats")
    account: Mapped["Account | None"] = relationship()
