"""Private game state endpoint with optional long-poll."""
from __future__ import annotations

import json
import math

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.legal_actions import get_legal_actions
from app.core.pot_calculator import calculate_pots
from app.database import get_session
from app.middleware.hmac_auth import require_hmac_auth
from app.models.account import Account
from app.models.hand import Hand, HandPlayer, HandStatus, TableSnapshot
from app.models.table import SeatStatus, Table, TableSeat
from app.schemas.game_state import PrivateGameState, PotView, SeatState, SidePot, UncalledReturn
from app.services.snapshot_service import get_snapshot_version, wait_for_change

router = APIRouter(prefix="/v1/private/tables", tags=["private-state"])


@router.get("/{table_no}/state", response_model=PrivateGameState)
async def get_game_state(
    table_no: int,
    since_version: int | None = Query(default=None),
    wait_ms: int = Query(default=0, ge=0, le=30000),
    session: AsyncSession = Depends(get_session),
    account_id: int = Depends(require_hmac_auth),
):
    # Load table
    table_result = await session.execute(select(Table).where(Table.table_no == table_no))
    table = table_result.scalar_one_or_none()
    if not table:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Table not found"})

    # Long-poll: wait if since_version matches current version
    if since_version is not None and wait_ms > 0:
        current_version = await get_snapshot_version(session, table.id)
        if since_version >= current_version:
            await wait_for_change(table.id, current_version, wait_ms)

    return await _build_state(session, table, account_id)


async def _build_state(
    session: AsyncSession,
    table: Table,
    account_id: int,
) -> PrivateGameState:
    # Snapshot version
    state_version = await get_snapshot_version(session, table.id)

    # Load all seats (with account nicknames)
    seats_result = await session.execute(
        select(TableSeat).where(TableSeat.table_id == table.id)
    )
    seats = list(seats_result.scalars().all())

    # Build nickname map
    acc_ids = [s.account_id for s in seats if s.account_id is not None]
    nickname_map: dict[int, str] = {}
    if acc_ids:
        acc_result = await session.execute(
            select(Account).where(Account.id.in_(acc_ids))
        )
        for acc in acc_result.scalars().all():
            nickname_map[acc.id] = acc.nickname

    # Active hand
    hand_result = await session.execute(
        select(Hand).where(Hand.table_id == table.id, Hand.status == HandStatus.IN_PROGRESS)
    )
    hand: Hand | None = hand_result.scalar_one_or_none()

    if hand is None:
        # No active hand
        seat_states = [
            SeatState(
                seat_no=s.seat_no,
                nickname=nickname_map.get(s.account_id) if s.account_id else None,
                stack=s.stack,
                folded=False,
                all_in=False,
                round_contribution=0,
                hand_contribution=0,
                seat_status=s.seat_status.value,
            )
            for s in sorted(seats, key=lambda x: x.seat_no)
        ]
        return PrivateGameState(
            table_no=table.table_no,
            hand_id=None,
            street=None,
            hole_cards=[],
            board=[],
            seats=seat_states,
            button_seat_no=None,
            action_seat_no=None,
            current_bet=0,
            to_call=0,
            legal_actions=[],
            min_raise_to=None,
            max_raise_to=None,
            pot_view=PotView(main_pot=0, side_pots=[], uncalled_return=None),
            action_deadline_at=None,
            state_version=state_version,
        )

    # Load hand players
    players_result = await session.execute(
        select(HandPlayer).where(HandPlayer.hand_id == hand.id)
    )
    players = list(players_result.scalars().all())
    player_map: dict[int, HandPlayer] = {p.seat_no: p for p in players}

    # Find caller's player record
    my_player: HandPlayer | None = next((p for p in players if p.account_id == account_id), None)

    # Hole cards (only caller's own)
    hole_cards: list[str] = []
    if my_player:
        hole_cards = json.loads(my_player.hole_cards_json)

    # Board
    board: list[str] = json.loads(hand.board_json)

    # Seat states (merge with hand player info)
    seat_states = []
    for s in sorted(seats, key=lambda x: x.seat_no):
        hp = player_map.get(s.seat_no)
        seat_states.append(SeatState(
            seat_no=s.seat_no,
            nickname=nickname_map.get(s.account_id) if s.account_id else None,
            stack=s.stack,
            folded=hp.folded if hp else False,
            all_in=hp.all_in if hp else False,
            round_contribution=hp.round_contribution if hp else 0,
            hand_contribution=hp.hand_contribution if hp else 0,
            seat_status=s.seat_status.value,
        ))

    # Legal actions and call amount for calling player
    to_call = 0
    legal_actions: list[dict] = []
    min_raise_to: int | None = None
    max_raise_to: int | None = None
    if my_player and hand.action_seat_no == my_player.seat_no:
        to_call = max(0, hand.current_bet - my_player.round_contribution)
        legal_actions = get_legal_actions(hand, my_player)
        if hand.current_bet > 0:
            min_raise_to = math.ceil(hand.current_bet * 1.5)
            max_raise_to = my_player.ending_stack + my_player.round_contribution
    elif my_player:
        to_call = max(0, hand.current_bet - my_player.round_contribution)

    # Pot view
    pot_input = [
        {"seat_no": p.seat_no, "hand_contribution": p.hand_contribution, "folded": p.folded}
        for p in players
    ]
    raw_pot = calculate_pots(pot_input)
    ur = raw_pot["uncalled_return"]
    pot_view = PotView(
        main_pot=raw_pot["main_pot"],
        side_pots=[SidePot(**sp) for sp in raw_pot["side_pots"]],
        uncalled_return=UncalledReturn(**ur) if ur else None,
    )

    return PrivateGameState(
        table_no=table.table_no,
        hand_id=hand.id,
        street=hand.street,
        hole_cards=hole_cards,
        board=board,
        seats=seat_states,
        button_seat_no=hand.button_seat_no,
        action_seat_no=hand.action_seat_no,
        current_bet=hand.current_bet,
        to_call=to_call,
        legal_actions=legal_actions,
        min_raise_to=min_raise_to,
        max_raise_to=max_raise_to,
        pot_view=pot_view,
        action_deadline_at=hand.action_deadline_at,
        state_version=state_version,
    )
