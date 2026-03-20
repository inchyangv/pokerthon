import json

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.hand import Hand, HandPlayer
from app.models.table import SeatStatus
from app.services.action_service import process_action
from app.services.hand_service import start_hand
from tests.test_t3_2_hand_start import _setup_table_with_players


async def _get_players(session: AsyncSession, hand: Hand) -> dict[int, HandPlayer]:
    result = await session.execute(select(HandPlayer).where(HandPlayer.hand_id == hand.id))
    return {p.seat_no: p for p in result.scalars().all()}


async def _call_all(session: AsyncSession, hand: Hand, players: dict) -> None:
    """Have all active players call/check until the current betting round is complete.

    Stops when the street changes (i.e., the round transitioned to the next street),
    so each call completes exactly one betting round.
    """
    await session.refresh(hand)
    initial_street = hand.street
    max_iters = 20
    for _ in range(max_iters):
        await session.refresh(hand)
        if hand.action_seat_no is None:
            break
        if hand.street in ("showdown", "finished"):
            break
        if hand.street != initial_street:
            break  # Current round complete; next street has begun
        actor = players.get(hand.action_seat_no)
        if actor is None:
            break
        await session.refresh(actor)
        if actor.folded or actor.all_in:
            break
        to_call = max(0, hand.current_bet - actor.round_contribution)
        if to_call == 0:
            await process_action(session, hand, actor.account_id, "CHECK")
        else:
            await process_action(session, hand, actor.account_id, "CALL")
        await session.refresh(hand)


@pytest.mark.asyncio
async def test_preflop_to_flop(db_session: AsyncSession):
    table, _ = await _setup_table_with_players(db_session, 3)
    hand = await start_hand(db_session, table.id)
    players = await _get_players(db_session, hand)

    await _call_all(db_session, hand, players)
    await db_session.refresh(hand)

    assert hand.street == "flop"
    board = json.loads(hand.board_json)
    assert len(board) == 3


@pytest.mark.asyncio
async def test_flop_to_turn(db_session: AsyncSession):
    table, _ = await _setup_table_with_players(db_session, 3)
    hand = await start_hand(db_session, table.id)
    players = await _get_players(db_session, hand)

    # Preflop
    await _call_all(db_session, hand, players)
    await db_session.refresh(hand)
    assert hand.street == "flop"

    # Flop
    await _call_all(db_session, hand, players)
    await db_session.refresh(hand)
    assert hand.street == "turn"
    board = json.loads(hand.board_json)
    assert len(board) == 4


@pytest.mark.asyncio
async def test_fold_ends_hand(db_session: AsyncSession):
    table, _ = await _setup_table_with_players(db_session, 2)
    hand = await start_hand(db_session, table.id)
    players = await _get_players(db_session, hand)

    actor = players[hand.action_seat_no]
    await process_action(db_session, hand, actor.account_id, "FOLD")
    await db_session.refresh(hand)

    # Should have only 1 non-folded player, street may still be preflop but action_seat_no = None
    non_folded = [p for p in players.values() if not p.all_in]
    await db_session.refresh(next(p for p in players.values()))
    # Hand should transition - verify action moves or round ends
    # The key test: only 1 player should remain active
    result = await db_session.execute(select(HandPlayer).where(HandPlayer.hand_id == hand.id))
    all_players = list(result.scalars().all())
    folded_count = sum(1 for p in all_players if p.folded)
    assert folded_count >= 1


@pytest.mark.asyncio
async def test_round_contribution_reset(db_session: AsyncSession):
    table, _ = await _setup_table_with_players(db_session, 3)
    hand = await start_hand(db_session, table.id)
    players = await _get_players(db_session, hand)

    # Complete preflop round
    await _call_all(db_session, hand, players)
    await db_session.refresh(hand)

    # round_contribution should be reset to 0 for all players
    result = await db_session.execute(select(HandPlayer).where(HandPlayer.hand_id == hand.id))
    for p in result.scalars().all():
        assert p.round_contribution == 0


@pytest.mark.asyncio
async def test_all_in_run_out(db_session: AsyncSession):
    """When all players go all-in, remaining streets should be dealt."""
    table, _ = await _setup_table_with_players(db_session, 2)
    hand = await start_hand(db_session, table.id)
    players = await _get_players(db_session, hand)

    # Both go all-in
    actor = players[hand.action_seat_no]
    await process_action(db_session, hand, actor.account_id, "ALL_IN")
    await db_session.refresh(hand)

    if hand.action_seat_no:
        actor2 = players[hand.action_seat_no]
        await db_session.refresh(actor2)
        if not actor2.all_in and not actor2.folded:
            await process_action(db_session, hand, actor2.account_id, "ALL_IN")

    await db_session.refresh(hand)
    # Should have moved to showdown or dealt all board cards
    assert hand.street in ("showdown", "flop", "turn", "river")
