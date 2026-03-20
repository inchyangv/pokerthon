"""Spectator viewer routes — public, no auth required."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from app.database import get_session
from app.models.hand import Hand, HandStatus
from app.models.table import SeatStatus, Table, TableSeat
from app.services.leaderboard_service import get_leaderboard

router = APIRouter(prefix="/viewer", tags=["viewer"])
templates = Jinja2Templates(directory="app/templates")


@router.get("/tables/{table_no}", response_class=HTMLResponse)
async def table_live(
    request: Request,
    table_no: int,
    session: AsyncSession = Depends(get_session),
):
    table_result = await session.execute(select(Table).where(Table.table_no == table_no))
    table = table_result.scalar_one_or_none()
    if not table:
        raise HTTPException(status_code=404, detail="Table not found")

    return templates.TemplateResponse(request, "viewer/table_live.html", {
        "table_no": table_no,
    })


@router.get("/", response_class=HTMLResponse)
async def lobby(request: Request, session: AsyncSession = Depends(get_session)):
    tables_result = await session.execute(select(Table).order_by(Table.table_no))
    all_tables = list(tables_result.scalars().all())

    tables_out = []
    for t in all_tables:
        seats_r = await session.execute(select(TableSeat).where(TableSeat.table_id == t.id))
        seats = list(seats_r.scalars().all())
        seated = sum(1 for s in seats if s.seat_status != SeatStatus.EMPTY)

        hand_r = await session.execute(
            select(Hand).where(Hand.table_id == t.id, Hand.status == HandStatus.IN_PROGRESS)
        )
        hand = hand_r.scalar_one_or_none()

        tables_out.append({
            "table_no": t.table_no,
            "status": t.status.value,
            "seated_count": seated,
            "max_seats": t.max_seats,
            "small_blind": t.small_blind,
            "big_blind": t.big_blind,
            "has_active_hand": hand is not None,
        })

    leaderboard = await get_leaderboard(session, sort_by="chips", limit=5)

    return templates.TemplateResponse(request, "viewer/lobby.html", {
        "tables": tables_out,
        "leaderboard": leaderboard,
    })
