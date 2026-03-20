from datetime import datetime

from pydantic import BaseModel, field_validator

from app.models.account import AccountStatus


class AccountCreate(BaseModel):
    nickname: str

    @field_validator("nickname")
    @classmethod
    def nickname_not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("nickname must not be empty")
        return v.strip()


class AccountResponse(BaseModel):
    id: int
    nickname: str
    status: AccountStatus
    wallet_balance: int
    created_at: datetime

    model_config = {"from_attributes": True}
