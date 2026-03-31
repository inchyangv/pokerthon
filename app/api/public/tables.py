from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_session
from app.models.account import Account
from app.models.table import SeatStatus, Table, TableSeat
from app.schemas.table_public import PublicSeatView, PublicTableDetail, PublicTableList

router = APIRouter(prefix="/v1/public/tables", tags=["public-tables"])


@router.get("", response_model=list[PublicTableList])
async def list_public_tables(session: AsyncSession = Depends(get_session)):
    result = await session.execute(
        select(Table).options(selectinload(Table.seats)).order_by(Table.table_no)
    )
    tables = result.scalars().all()
    out = []
    for t in tables:
        seated = sum(1 for s in t.seats if s.seat_status != SeatStatus.EMPTY)
        out.append(PublicTableList(
            table_no=t.table_no,
            status=t.status,
            seated_count=seated,
            max_seats=t.max_seats,
        ))
    return out


@router.get("/{table_no}", response_model=PublicTableDetail)
async def get_public_table(table_no: int, session: AsyncSession = Depends(get_session)):
    result = await session.execute(
        select(Table).where(Table.table_no == table_no).options(selectinload(Table.seats))
    )
    table = result.scalar_one_or_none()
    if not table:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Table not found"})

    # Batch-load nicknames for all seated players (1 query)
    acc_ids = [s.account_id for s in table.seats if s.account_id]
    nickname_map: dict[int, str] = {}
    if acc_ids:
        acc_result = await session.execute(select(Account).where(Account.id.in_(acc_ids)))
        nickname_map = {a.id: a.nickname for a in acc_result.scalars().all()}

    seats_out = []
    for seat in table.seats:
        seats_out.append(PublicSeatView(
            seat_no=seat.seat_no,
            nickname=nickname_map.get(seat.account_id) if seat.account_id else None,
            stack=seat.stack,
            seat_status=seat.seat_status,
        ))

    seated = sum(1 for s in table.seats if s.seat_status != SeatStatus.EMPTY)
    return PublicTableDetail(
        table_no=table.table_no,
        status=table.status,
        max_seats=table.max_seats,
        seated_count=seated,
        seats=seats_out,
    )
