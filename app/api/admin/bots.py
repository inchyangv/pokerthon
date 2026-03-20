"""Admin API for bot management."""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.schemas.bot import BotCreate, BotListItem, BotResponse, BotSeatRequest
from app.services.bot_service import (
    create_bot,
    deactivate_bot,
    list_bots,
    seat_bot,
    unseat_bot,
)

router = APIRouter(prefix="/admin/bots", tags=["admin-bots"])


@router.post("", status_code=201)
async def create_bot_endpoint(
    body: BotCreate,
    session: AsyncSession = Depends(get_session),
):
    try:
        return await create_bot(session, body.bot_type, body.display_name)
    except ValueError as e:
        msg = str(e)
        if "CONFLICT" in msg:
            raise HTTPException(status_code=409, detail={"code": "CONFLICT", "message": msg})
        raise HTTPException(status_code=422, detail={"code": "INVALID", "message": msg})


@router.get("", response_model=list[BotListItem])
async def list_bots_endpoint(
    is_active: bool | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
):
    return await list_bots(session, is_active=is_active)


@router.post("/{bot_id}/seat", status_code=200)
async def seat_bot_endpoint(
    bot_id: int,
    body: BotSeatRequest,
    session: AsyncSession = Depends(get_session),
):
    try:
        seat = await seat_bot(session, bot_id, body.table_no, body.seat_no)
        return {"seat_no": seat.seat_no, "stack": seat.stack}
    except LookupError as e:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": str(e)})
    except ValueError as e:
        msg = str(e)
        if "CONFLICT" in msg:
            raise HTTPException(status_code=409, detail={"code": "CONFLICT", "message": msg})
        raise HTTPException(status_code=422, detail={"code": "INVALID", "message": msg})


@router.post("/{bot_id}/unseat", status_code=200)
async def unseat_bot_endpoint(
    bot_id: int,
    session: AsyncSession = Depends(get_session),
):
    try:
        result = await unseat_bot(session, bot_id)
        return result
    except LookupError as e:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": str(e)})


@router.delete("/{bot_id}", status_code=204)
async def deactivate_bot_endpoint(
    bot_id: int,
    session: AsyncSession = Depends(get_session),
):
    try:
        await deactivate_bot(session, bot_id)
    except LookupError as e:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": str(e)})
