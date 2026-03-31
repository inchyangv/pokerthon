from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.schemas.table import TableCreate, TableListItem, TableResponse
from app.services.table_service import (
    close_table,
    create_table,
    delete_table,
    get_table_by_no,
    list_tables,
    pause_table,
    resume_table,
)


class SetBlindsBody(BaseModel):
    small_blind: int
    big_blind: int


class MergeTablesBody(BaseModel):
    src_table_no: int
    dst_table_no: int


class AdminSeatBody(BaseModel):
    account_id: int
    seat_no: int | None = None

router = APIRouter(prefix="/admin/tables", tags=["admin-tables"])


@router.post("/{table_no}/start-hand", status_code=200)
async def start_hand_endpoint(table_no: int, session: AsyncSession = Depends(get_session)):
    """Manually start a new hand at the given table."""
    from sqlalchemy import select
    from app.models.table import Table, TableStatus
    from app.services.hand_service import start_hand, get_active_hand
    from app.core.table_lock import get_table_lock

    table_r = await session.execute(select(Table).where(Table.table_no == table_no))
    table = table_r.scalar_one_or_none()
    if not table:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Table not found"})
    if table.status != TableStatus.OPEN:
        raise HTTPException(status_code=409, detail={"code": "TABLE_NOT_OPEN", "message": f"Table is {table.status.value}"})

    async with get_table_lock(table_no):
        active = await get_active_hand(session, table.id)
        if active:
            raise HTTPException(status_code=409, detail={"code": "HAND_IN_PROGRESS", "message": "A hand is already in progress"})
        hand = await start_hand(session, table.id)
        if not hand:
            raise HTTPException(status_code=409, detail={"code": "CANNOT_START", "message": "Need at least 2 seated players with chips"})

    return {"hand_id": hand.id, "hand_no": hand.hand_no}


@router.post("", response_model=TableResponse, status_code=201)
async def create_table_endpoint(body: TableCreate, session: AsyncSession = Depends(get_session)):
    try:
        table = await create_table(session, body.table_no)
    except ValueError as e:
        raise HTTPException(status_code=409, detail={"code": "CONFLICT", "message": str(e)})
    return table


@router.get("", response_model=list[TableListItem])
async def list_tables_endpoint(session: AsyncSession = Depends(get_session)):
    return await list_tables(session)


@router.get("/{table_no}", response_model=TableResponse)
async def get_table_endpoint(table_no: int, session: AsyncSession = Depends(get_session)):
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload
    from app.models.table import Table
    result = await session.execute(
        select(Table).where(Table.table_no == table_no).options(selectinload(Table.seats))
    )
    table = result.scalar_one_or_none()
    if not table:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Table not found"})
    return table


@router.post("/{table_no}/pause", response_model=TableResponse)
async def pause_table_endpoint(table_no: int, session: AsyncSession = Depends(get_session)):
    try:
        table = await pause_table(session, table_no)
    except LookupError:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Table not found"})
    except ValueError as e:
        raise HTTPException(status_code=409, detail={"code": "CONFLICT", "message": str(e)})
    return table


@router.post("/{table_no}/resume", response_model=TableResponse)
async def resume_table_endpoint(table_no: int, session: AsyncSession = Depends(get_session)):
    try:
        table = await resume_table(session, table_no)
    except LookupError:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Table not found"})
    except ValueError as e:
        raise HTTPException(status_code=409, detail={"code": "CONFLICT", "message": str(e)})
    return table


@router.delete("/{table_no}", status_code=204)
async def delete_table_endpoint(table_no: int, session: AsyncSession = Depends(get_session)):
    try:
        await delete_table(session, table_no)
    except LookupError as e:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": str(e)})
    # Invalidate in-process caches so recreated tables resolve to the new table_id
    from app.api.public.game_state import invalidate_table_id_cache, invalidate_state_cache
    invalidate_table_id_cache(table_no)


@router.post("/{table_no}/close", response_model=TableResponse)
async def close_table_endpoint(table_no: int, session: AsyncSession = Depends(get_session)):
    try:
        table = await close_table(session, table_no)
    except LookupError:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Table not found"})
    except ValueError as e:
        raise HTTPException(status_code=409, detail={"code": "CONFLICT", "message": str(e)})
    return table


@router.post("/{table_no}/set-blinds")
async def set_blinds_endpoint(
    table_no: int,
    body: SetBlindsBody,
    session: AsyncSession = Depends(get_session),
):
    """Update small/big blind for the table. Takes effect on the next hand."""
    from sqlalchemy import select
    from app.models.table import Table
    from app.services.hand_service import get_active_hand

    if body.small_blind <= 0 or body.big_blind <= 0:
        raise HTTPException(status_code=422, detail={"code": "INVALID", "message": "Blinds must be positive"})
    if body.big_blind < body.small_blind:
        raise HTTPException(status_code=422, detail={"code": "INVALID", "message": "big_blind must be >= small_blind"})

    table_r = await session.execute(select(Table).where(Table.table_no == table_no))
    table = table_r.scalar_one_or_none()
    if not table:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Table not found"})

    active = await get_active_hand(session, table.id)
    if active:
        raise HTTPException(status_code=409, detail={"code": "HAND_IN_PROGRESS", "message": "Cannot change blinds mid-hand"})

    table.small_blind = body.small_blind
    table.big_blind = body.big_blind
    await session.commit()
    return {"table_no": table_no, "small_blind": table.small_blind, "big_blind": table.big_blind}


@router.post("/merge")
async def merge_tables_endpoint(
    body: MergeTablesBody,
    session: AsyncSession = Depends(get_session),
):
    """Move all seated players from src_table_no to dst_table_no."""
    from app.services.table_service import merge_tables
    try:
        result = await merge_tables(session, body.src_table_no, body.dst_table_no)
    except LookupError as e:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": str(e)})
    except ValueError as e:
        raise HTTPException(status_code=409, detail={"code": "CONFLICT", "message": str(e)})
    return result


@router.post("/{table_no}/stand-player")
async def admin_stand_player(
    table_no: int,
    body: AdminSeatBody,
    session: AsyncSession = Depends(get_session),
):
    """Admin: force a player to stand immediately (even if a hand is in progress)."""
    from sqlalchemy import select
    from app.models.table import Table, TableSeat, SeatStatus
    table_r = await session.execute(select(Table).where(Table.table_no == table_no))
    table = table_r.scalar_one_or_none()
    if not table:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Table not found"})
    seat_r = await session.execute(
        select(TableSeat).where(TableSeat.table_id == table.id, TableSeat.account_id == body.account_id)
    )
    seat = seat_r.scalar_one_or_none()
    if not seat or seat.seat_status == SeatStatus.EMPTY:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Player not seated at this table"})
    seat.seat_status = SeatStatus.EMPTY
    seat.account_id = None
    seat.stack = 0
    await session.commit()
    return {"table_no": table_no, "account_id": body.account_id, "stood_up": True}


@router.post("/{table_no}/seat-player")
async def admin_seat_player(
    table_no: int,
    body: AdminSeatBody,
    session: AsyncSession = Depends(get_session),
):
    """Admin: seat a player at a table without requiring HMAC auth."""
    from app.services.seat_service import sit
    try:
        seat = await sit(session, body.account_id, table_no, body.seat_no)
    except LookupError as e:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": str(e)})
    except ValueError as e:
        msg = str(e)
        code = msg.split(":")[0] if ":" in msg else "INVALID_ACTION"
        raise HTTPException(status_code=409, detail={"code": code, "message": msg})
    return {"table_no": table_no, "seat_no": seat.seat_no, "account_id": body.account_id, "stack": seat.stack}
