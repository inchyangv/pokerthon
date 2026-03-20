"""Public game state endpoint — no hole cards exposed."""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.pot_calculator import calculate_pots
from app.database import get_session
from app.models.account import Account
from app.models.hand import Hand, HandPlayer, HandStatus
from app.models.table import SeatStatus, Table, TableSeat
from app.schemas.game_state import PotView, SidePot, UncalledReturn
from app.services.snapshot_service import get_snapshot_version

router = APIRouter(prefix="/v1/public/tables", tags=["public-state"])


class PublicSeatState(BaseModel):
    seat_no: int
    nickname: str | None
    stack: int
    folded: bool
    all_in: bool
    seat_status: str


class PublicGameState(BaseModel):
    table_no: int
    status: str
    hand_id: int | None
    street: str | None
    board: list[str]
    seats: list[PublicSeatState]
    button_seat_no: int | None
    action_seat_no: int | None
    current_bet: int
    pot_view: PotView
    action_deadline_at: str | None  # ISO 8601
    state_version: int


@router.get("/{table_no}/state", response_model=PublicGameState)
async def get_public_game_state(
    table_no: int,
    session: AsyncSession = Depends(get_session),
):
    table_result = await session.execute(select(Table).where(Table.table_no == table_no))
    table = table_result.scalar_one_or_none()
    if not table:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Table not found"})

    state_version = await get_snapshot_version(session, table.id)

    # Load seats
    seats_result = await session.execute(select(TableSeat).where(TableSeat.table_id == table.id))
    seats = list(seats_result.scalars().all())

    acc_ids = [s.account_id for s in seats if s.account_id]
    nickname_map: dict[int, str] = {}
    if acc_ids:
        acc_result = await session.execute(select(Account).where(Account.id.in_(acc_ids)))
        for acc in acc_result.scalars().all():
            nickname_map[acc.id] = acc.nickname

    # Active hand
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
            action_seat_no=None,
            current_bet=0,
            pot_view=PotView(main_pot=0, side_pots=[], uncalled_return=None),
            action_deadline_at=None,
            state_version=state_version,
        )

    # Hand in progress
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
        action_seat_no=hand.action_seat_no,
        current_bet=hand.current_bet,
        pot_view=pot_view,
        action_deadline_at=deadline_str,
        state_version=state_version,
    )
