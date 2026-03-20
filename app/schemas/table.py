from datetime import datetime

from pydantic import BaseModel

from app.models.table import SeatStatus, TableStatus


class TableCreate(BaseModel):
    table_no: int


class SeatResponse(BaseModel):
    seat_no: int
    seat_status: SeatStatus
    account_id: int | None
    stack: int

    model_config = {"from_attributes": True}


class TableResponse(BaseModel):
    id: int
    table_no: int
    status: TableStatus
    max_seats: int
    small_blind: int
    big_blind: int
    buy_in: int
    created_at: datetime
    seats: list[SeatResponse] = []

    model_config = {"from_attributes": True}


class TableListItem(BaseModel):
    id: int
    table_no: int
    status: TableStatus
    max_seats: int
    created_at: datetime

    model_config = {"from_attributes": True}
