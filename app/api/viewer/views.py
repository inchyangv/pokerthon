"""Spectator viewer routes — public, no auth required."""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from starlette.requests import Request

from app.database import get_session
from app.models.hand import Hand, HandStatus
from app.models.table import SeatStatus, Table
from app.services.leaderboard_service import get_leaderboard
from app.tasks.blind_escalation import get_blind_level_info


def _fmt_ts(ts) -> str:
    """Format a datetime to 'MM/DD HH:mm' or return '-'."""
    if not ts:
        return "-"
    if isinstance(ts, datetime):
        return ts.strftime("%m/%d %H:%M")
    if isinstance(ts, str):
        try:
            return datetime.fromisoformat(ts).strftime("%m/%d %H:%M")
        except (ValueError, TypeError):
            return ts
    return str(ts)

from app.core.templates import templates

router = APIRouter(prefix="/viewer", tags=["viewer"])


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
    # Batch load tables + seats in 2 queries instead of 2N+1
    tables_result = await session.execute(
        select(Table).options(selectinload(Table.seats)).order_by(Table.table_no)
    )
    all_tables = list(tables_result.scalars().all())

    # One query for all in-progress hands across all tables
    table_ids = [t.id for t in all_tables]
    active_hands: dict[int, bool] = {}
    if table_ids:
        hands_result = await session.execute(
            select(Hand.table_id).where(
                Hand.table_id.in_(table_ids),
                Hand.status == HandStatus.IN_PROGRESS,
            )
        )
        active_hands = {row[0]: True for row in hands_result.all()}

    tables_out = []
    for t in all_tables:
        seated = sum(1 for s in t.seats if s.seat_status != SeatStatus.EMPTY)
        tables_out.append({
            "table_no": t.table_no,
            "status": t.status.value,
            "seated_count": seated,
            "max_seats": t.max_seats,
            "small_blind": t.small_blind,
            "big_blind": t.big_blind,
            "has_active_hand": active_hands.get(t.id, False),
        })

    blind_level = get_blind_level_info()

    # Leaderboard rendered client-side via AJAX to avoid blocking page render
    return templates.TemplateResponse(request, "viewer/lobby.html", {
        "tables": tables_out,
        "blind_level": blind_level,
    })


@router.get("/tables/{table_no}/hands/{hand_id}", response_class=HTMLResponse)
async def hand_detail_viewer(
    request: Request,
    table_no: int,
    hand_id: int,
    session: AsyncSession = Depends(get_session),
):
    table_result = await session.execute(select(Table).where(Table.table_no == table_no))
    table = table_result.scalar_one_or_none()
    if not table:
        raise HTTPException(status_code=404, detail="Table not found")

    from app.services.history_service import get_hand_detail, get_hand_actions
    detail = await get_hand_detail(session, table.id, hand_id)
    if not detail:
        raise HTTPException(status_code=404, detail="Hand not found")

    actions = await get_hand_actions(session, hand_id)

    # Enrich players with profit
    players = detail.get("players", [])
    for p in players:
        p["profit"] = p.get("ending_stack", 0) - p.get("starting_stack", 0)

    winner_seats = detail.get("winners", [])
    pot_summary = detail.get("pot_summary", {})

    hand = {
        "hand_no": detail.get("hand_no"),
        "board": detail.get("board", []),
        "started_at": _fmt_ts(detail.get("started_at")),
        "finished_at": _fmt_ts(detail.get("finished_at")),
    }

    result_data = None
    if winner_seats or pot_summary:
        result_data = {"winner_seats": winner_seats, "pot_summary": pot_summary}

    return templates.TemplateResponse(request, "viewer/hand_detail.html", {
        "table_no": table_no,
        "hand": hand,
        "players": players,
        "result": result_data,
        "actions": actions,
    })


@router.get("/tables/{table_no}/hands", response_class=HTMLResponse)
async def hand_list_viewer(
    request: Request,
    table_no: int,
    cursor: int | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
):
    table_result = await session.execute(select(Table).where(Table.table_no == table_no))
    table = table_result.scalar_one_or_none()
    if not table:
        raise HTTPException(status_code=404, detail="Table not found")

    from app.services.history_service import get_hand_list
    import json

    data = await get_hand_list(session, table.id, limit=20, cursor=cursor)
    raw_hands = data.get("items", [])

    hands_out = []
    for h in raw_hands:
        board = h.get("board", [])
        pot = h.get("pot_summary", {})
        total_pot = None
        if isinstance(pot, dict):
            total_pot = pot.get("main_pot", 0) + sum(sp.get("amount", 0) for sp in pot.get("side_pots", []))
        hands_out.append({
            "hand_id": h["hand_id"],
            "hand_no": h["hand_no"],
            "board": board,
            "total_pot": total_pot,
            "started_at": _fmt_ts(h.get("started_at")),
            "finished_at": _fmt_ts(h.get("finished_at")),
        })

    return templates.TemplateResponse(request, "viewer/hand_list.html", {
        "table_no": table_no,
        "hands": hands_out,
        "next_cursor": data.get("next_cursor"),
        "prev_cursor": None,
    })


@router.get("/leaderboard", response_class=HTMLResponse)
async def leaderboard_page(
    request: Request,
    sort_by: str = Query(default="chips"),
    session: AsyncSession = Depends(get_session),
):
    valid_sorts = {"chips", "profit", "win_rate", "hands_played"}
    if sort_by not in valid_sorts:
        sort_by = "chips"

    items = await get_leaderboard(session, sort_by=sort_by, limit=200, include_bots=False)
    return templates.TemplateResponse(request, "viewer/leaderboard.html", {
        "items": items,
        "sort_by": sort_by,
    })
