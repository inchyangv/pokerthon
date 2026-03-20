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
