"""Admin API for bot management."""
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.models.bot import BotProfile
from app.models.hand import Hand, HandPlayer, HandStatus
from app.models.table import SeatStatus, TableSeat
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


class ResetStacksRequest(BaseModel):
    stack: int = 40


@router.post("/reset-stacks", status_code=200)
async def reset_bot_stacks_endpoint(
    body: ResetStacksRequest,
    session: AsyncSession = Depends(get_session),
):
    """Set all seated bots' stacks to the given value."""
    bots_r = await session.execute(
        select(BotProfile).where(BotProfile.is_active == True)  # noqa: E712
    )
    bots = list(bots_r.scalars().all())
    bot_account_ids = {b.account_id for b in bots}

    updated = []
    for acc_id in bot_account_ids:
        seat_r = await session.execute(
            select(TableSeat).where(
                TableSeat.account_id == acc_id,
                TableSeat.seat_status.in_([SeatStatus.SEATED, SeatStatus.LEAVING_AFTER_HAND]),
            )
        )
        seat = seat_r.scalar_one_or_none()
        if not seat:
            continue

        old_stack = seat.stack
        seat.stack = body.stack

        # Also update HandPlayer.ending_stack if there's an active hand
        hand_r = await session.execute(
            select(Hand).where(Hand.table_id == seat.table_id, Hand.status == HandStatus.IN_PROGRESS)
        )
        hand = hand_r.scalar_one_or_none()
        if hand:
            hp_r = await session.execute(
                select(HandPlayer).where(HandPlayer.hand_id == hand.id, HandPlayer.account_id == acc_id)
            )
            hp = hp_r.scalar_one_or_none()
            if hp:
                hp.ending_stack = body.stack

        updated.append({"account_id": acc_id, "seat_no": seat.seat_no, "table_id": seat.table_id, "old_stack": old_stack, "new_stack": body.stack})

    await session.commit()
    return {"updated": updated}


@router.delete("/{bot_id}", status_code=204)
async def deactivate_bot_endpoint(
    bot_id: int,
    session: AsyncSession = Depends(get_session),
):
    try:
        await deactivate_bot(session, bot_id)
    except LookupError as e:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": str(e)})
