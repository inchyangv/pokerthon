"""Public game state endpoint — no hole cards exposed."""
from __future__ import annotations

import asyncio
import json
from typing import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.pot_calculator import calculate_pots
from app.database import async_session_factory, get_session
from app.models.account import Account
from app.models.hand import Hand, HandPlayer, HandStatus, TableSnapshot
from app.models.table import SeatStatus, Table, TableSeat
from app.schemas.game_state import PotView, SidePot, UncalledReturn
from app.services.snapshot_service import get_snapshot_version, wait_for_change

router = APIRouter(prefix="/v1/public/tables", tags=["public-state"])

# In-process caches — survive across requests within the same process
_table_id_cache: dict[int, int] = {}           # table_no → table_id (permanent)
_state_cache: dict[int, tuple[int, str]] = {}  # table_id → (version, state_json)


class PublicSeatState(BaseModel):
    seat_no: int
    nickname: str | None
    stack: int
    folded: bool
    all_in: bool
    seat_status: str
    round_contribution: int  # chips committed this street (0 when no hand)


class PublicGameState(BaseModel):
    table_no: int
    status: str
    hand_id: int | None
    street: str | None
    board: list[str]
    seats: list[PublicSeatState]
    button_seat_no: int | None
    small_blind_seat_no: int | None
    big_blind_seat_no: int | None
    action_seat_no: int | None
    current_bet: int
    pot_view: PotView
    action_deadline_at: str | None  # ISO 8601
    state_version: int


async def _compute_state(
    session: AsyncSession,
    table: Table,
    state_version: int,
) -> PublicGameState:
    """Build PublicGameState by running up to 4 DB queries."""
    seats_result = await session.execute(select(TableSeat).where(TableSeat.table_id == table.id))
    seats = list(seats_result.scalars().all())

    acc_ids = [s.account_id for s in seats if s.account_id]
    nickname_map: dict[int, str] = {}
    if acc_ids:
        acc_result = await session.execute(select(Account).where(Account.id.in_(acc_ids)))
        for acc in acc_result.scalars().all():
            nickname_map[acc.id] = acc.nickname

    hand_result = await session.execute(
        select(Hand).where(Hand.table_id == table.id, Hand.status == HandStatus.IN_PROGRESS)
    )
    hand: Hand | None = hand_result.scalar_one_or_none()

    if hand is None:
        seat_states = [
            PublicSeatState(
                seat_no=s.seat_no,
                nickname=nickname_map.get(s.account_id) if s.account_id else None,
                stack=s.stack,
                folded=False,
                all_in=False,
                seat_status=s.seat_status.value,
                round_contribution=0,
            )
            for s in sorted(seats, key=lambda x: x.seat_no)
        ]
        return PublicGameState(
            table_no=table.table_no,
            status=table.status.value,
            hand_id=None,
            street=None,
            board=[],
            seats=seat_states,
            button_seat_no=None,
            small_blind_seat_no=None,
            big_blind_seat_no=None,
            action_seat_no=None,
            current_bet=0,
            pot_view=PotView(main_pot=0, side_pots=[], uncalled_return=None),
            action_deadline_at=None,
            state_version=state_version,
        )

    players_result = await session.execute(
        select(HandPlayer).where(HandPlayer.hand_id == hand.id)
    )
    players = {p.seat_no: p for p in players_result.scalars().all()}

    seat_states = []
    for s in sorted(seats, key=lambda x: x.seat_no):
        hp = players.get(s.seat_no)
        seat_states.append(PublicSeatState(
            seat_no=s.seat_no,
            nickname=nickname_map.get(s.account_id) if s.account_id else None,
            stack=s.stack,
            folded=hp.folded if hp else False,
            all_in=hp.all_in if hp else False,
            seat_status=s.seat_status.value,
            round_contribution=hp.round_contribution if hp else 0,
        ))

    pot_input = [
        {"seat_no": p.seat_no, "hand_contribution": p.hand_contribution, "folded": p.folded}
        for p in players.values()
    ]
    raw_pot = calculate_pots(pot_input)
    ur = raw_pot["uncalled_return"]
    pot_view = PotView(
        main_pot=raw_pot["main_pot"],
        side_pots=[SidePot(**sp) for sp in raw_pot["side_pots"]],
        uncalled_return=UncalledReturn(**ur) if ur else None,
    )

    deadline_str = None
    if hand.action_deadline_at:
        deadline_str = hand.action_deadline_at.isoformat()

    return PublicGameState(
        table_no=table.table_no,
        status=table.status.value,
        hand_id=hand.id,
        street=hand.street,
        board=json.loads(hand.board_json),
        seats=seat_states,
        button_seat_no=hand.button_seat_no,
        small_blind_seat_no=hand.small_blind_seat_no,
        big_blind_seat_no=hand.big_blind_seat_no,
        action_seat_no=hand.action_seat_no,
        current_bet=hand.current_bet,
        pot_view=pot_view,
        action_deadline_at=deadline_str,
        state_version=state_version,
    )


@router.get("/{table_no}/state")
async def get_public_game_state(
    table_no: int,
    since_version: int | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
) -> Response:
    # 1. Resolve table_no → table_id (permanent in-process cache)
    if table_no not in _table_id_cache:
        table_result = await session.execute(select(Table).where(Table.table_no == table_no))
        table = table_result.scalar_one_or_none()
        if not table:
            raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Table not found"})
        _table_id_cache[table_no] = table.id
        loaded_table: Table | None = table
    else:
        loaded_table = None  # lazy — only fetch if we need a full rebuild

    table_id = _table_id_cache[table_no]

    # 2. Get current snapshot version (1 DB query)
    state_version = await get_snapshot_version(session, table_id)

    # 3. 304 when client is already up-to-date
    if since_version is not None and since_version == state_version:
        return Response(status_code=304)

    # 4. Serve from in-process cache when version matches
    cached = _state_cache.get(table_id)
    if cached and cached[0] == state_version:
        return Response(content=cached[1], media_type="application/json")

    # 5. Cache miss — run the remaining queries and build full state
    if loaded_table is None:
        table_result = await session.execute(select(Table).where(Table.table_no == table_no))
        loaded_table = table_result.scalar_one_or_none()

    state = await _compute_state(session, loaded_table, state_version)
    state_json = state.model_dump_json()
    _state_cache[table_id] = (state_version, state_json)
    return Response(content=state_json, media_type="application/json")


def invalidate_state_cache(table_id: int) -> None:
    """Clear cached state for a table (call after committing state changes)."""
    _state_cache.pop(table_id, None)


# ── SSE stream ───────────────────────────────────────────────────────────────

_SSE_WAIT_MS = 30_000   # max wait per iteration before sending heartbeat
_SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "X-Accel-Buffering": "no",  # disable nginx buffering
}


async def _state_event(table_id: int, table_no_hint: int) -> str | None:
    """Return SSE 'state' event string, using cache when available."""
    cached = _state_cache.get(table_id)
    version = await get_snapshot_version_direct(table_id)
    if cached and cached[0] == version:
        state_json = cached[1]
    else:
        async with async_session_factory() as sess:
            table_result = await sess.execute(
                select(Table).where(Table.table_no == table_no_hint)
            )
            table = table_result.scalar_one_or_none()
            if not table:
                return None
            state = await _compute_state(sess, table, version)
            state_json = state.model_dump_json()
            _state_cache[table_id] = (version, state_json)
    return f"event: state\ndata: {state_json}\n\n"


async def get_snapshot_version_direct(table_id: int) -> int:
    """Read snapshot version using a fresh session (for use outside request context)."""
    async with async_session_factory() as sess:
        return await get_snapshot_version(sess, table_id)


async def _sse_generator(table_id: int, table_no: int) -> AsyncIterator[str]:
    """Yield SSE events for a live table."""
    # Send current state immediately on connect
    event = await _state_event(table_id, table_no)
    if event:
        yield event

    current_version = await get_snapshot_version_direct(table_id)

    while True:
        changed = await wait_for_change(table_id, current_version, wait_ms=_SSE_WAIT_MS)
        if not changed:
            # Heartbeat keeps the connection alive through proxies
            yield ": heartbeat\n\n"
            continue

        new_version = await get_snapshot_version_direct(table_id)
        if new_version == current_version:
            continue

        current_version = new_version
        event = await _state_event(table_id, table_no)
        if event:
            yield event


@router.get("/{table_no}/stream")
async def stream_table_state(
    table_no: int,
    session: AsyncSession = Depends(get_session),
) -> StreamingResponse:
    """Server-Sent Events endpoint — pushes state updates in real time."""
    # Resolve table existence and cache table_id
    if table_no not in _table_id_cache:
        table_result = await session.execute(select(Table).where(Table.table_no == table_no))
        table = table_result.scalar_one_or_none()
        if not table:
            raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Table not found"})
        _table_id_cache[table_no] = table.id

    table_id = _table_id_cache[table_no]

    return StreamingResponse(
        _sse_generator(table_id, table_no),
        media_type="text/event-stream",
        headers=_SSE_HEADERS,
    )
