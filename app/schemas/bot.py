from pydantic import BaseModel


class BotCreate(BaseModel):
    bot_type: str  # TAG | LAG | FISH
    display_name: str


class BotSeatRequest(BaseModel):
    table_no: int
    seat_no: int | None = None


class BotResponse(BaseModel):
    bot_id: int
    account_id: int
    bot_type: str
    display_name: str
    chips: int

    model_config = {"from_attributes": True}


class BotListItem(BaseModel):
    bot_id: int
    account_id: int
    bot_type: str
    display_name: str
    is_active: bool
    wallet_balance: int
    table_no: int | None = None
    seat_no: int | None = None
    stack: int | None = None

    model_config = {"from_attributes": True}
