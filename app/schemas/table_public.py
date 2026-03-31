from pydantic import BaseModel

from app.models.table import SeatStatus, TableStatus


class PublicSeatView(BaseModel):
    seat_no: int
    nickname: str | None
    stack: int
    seat_status: SeatStatus

    model_config = {"from_attributes": True}


class PublicTableDetail(BaseModel):
    table_no: int
    status: TableStatus
    max_seats: int
    seated_count: int
    seats: list[PublicSeatView]

    model_config = {"from_attributes": True}


class PublicTableList(BaseModel):
    table_no: int
    status: TableStatus
    seated_count: int
    max_seats: int
    small_blind: int
    big_blind: int
    hand_id: int | None

    model_config = {"from_attributes": True}


class MeResponse(BaseModel):
    account_id: int
    nickname: str
    wallet_balance: int
    current_table_no: int | None
