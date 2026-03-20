from datetime import datetime

from pydantic import BaseModel, field_validator

from app.models.chip import LedgerReasonType


class ChipGrantRequest(BaseModel):
    amount: int
    reason: str = ""

    @field_validator("amount")
    @classmethod
    def amount_must_be_positive(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("amount must be a positive integer")
        return v


class ChipDeductRequest(BaseModel):
    amount: int
    reason: str = ""

    @field_validator("amount")
    @classmethod
    def amount_must_be_positive(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("amount must be a positive integer")
        return v


class LedgerEntry(BaseModel):
    id: int
    account_id: int
    delta: int
    balance_after: int
    reason_type: LedgerReasonType
    reason_text: str | None
    ref_type: str | None
    ref_id: int | None
    created_at: datetime

    model_config = {"from_attributes": True}
