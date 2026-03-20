import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class LedgerReasonType(str, enum.Enum):
    ADMIN_GRANT = "ADMIN_GRANT"
    ADMIN_DEDUCT = "ADMIN_DEDUCT"
    TABLE_BUYIN = "TABLE_BUYIN"
    TABLE_CASHOUT = "TABLE_CASHOUT"
    HAND_WIN = "HAND_WIN"
    HAND_LOSS = "HAND_LOSS"
    MANUAL_ADJUST = "MANUAL_ADJUST"


class ChipLedger(Base):
    __tablename__ = "chip_ledger"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(Integer, ForeignKey("accounts.id"), nullable=False)
    delta: Mapped[int] = mapped_column(Integer, nullable=False)
    balance_after: Mapped[int] = mapped_column(Integer, nullable=False)
    reason_type: Mapped[LedgerReasonType] = mapped_column(Enum(LedgerReasonType), nullable=False)
    reason_text: Mapped[str | None] = mapped_column(String(256), nullable=True)
    ref_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ref_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    account: Mapped["Account"] = relationship(back_populates="ledger_entries")
