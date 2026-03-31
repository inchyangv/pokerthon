from fastapi import APIRouter, Depends, HTTPException
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


@router.post("/{table_no}/close", response_model=TableResponse)
async def close_table_endpoint(table_no: int, session: AsyncSession = Depends(get_session)):
    try:
        table = await close_table(session, table_no)
    except LookupError:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Table not found"})
    except ValueError as e:
        raise HTTPException(status_code=409, detail={"code": "CONFLICT", "message": str(e)})
    return table
