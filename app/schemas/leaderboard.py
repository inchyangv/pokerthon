from datetime import datetime
from pydantic import BaseModel


class LeaderboardItem(BaseModel):
    rank: int
    nickname: str
    is_bot: bool
    total_chips: int
    wallet_balance: int
    table_stack: int
    hands_played: int
    hands_won: int
    win_rate: float
    total_profit: int
    biggest_pot_won: int
    current_table: int | None

    model_config = {"from_attributes": True}


class LeaderboardResponse(BaseModel):
    items: list[LeaderboardItem]
    updated_at: datetime
