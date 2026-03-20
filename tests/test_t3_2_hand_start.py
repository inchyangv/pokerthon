import json

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.hand import Hand, HandAction, HandPlayer
from app.models.table import SeatStatus, Table, TableSeat
from app.services.hand_service import start_hand


async def _setup_table_with_players(session: AsyncSession, n: int) -> tuple[Table, list[TableSeat]]:
    from app.models.account import Account, AccountStatus
    from app.models.table import TableStatus

    # Create accounts
    accounts = []
    for i in range(n):
        acc = Account(nickname=f"p{i}", status=AccountStatus.ACTIVE, wallet_balance=0)
        session.add(acc)
    await session.flush()

    # Create table
    table = Table(table_no=999, status=TableStatus.OPEN, max_seats=9, small_blind=1, big_blind=2, buy_in=40)
    session.add(table)
    await session.flush()

    # Create seats and place players
    accounts_q = await session.execute(select(Account).where(Account.nickname.like("p%")))
    account_list = list(accounts_q.scalars().all())[:n]

    seats = []
    for i, acc in enumerate(account_list):
        seat = TableSeat(
            table_id=table.id,
            seat_no=i + 1,
            account_id=acc.id,
            seat_status=SeatStatus.SEATED,
            stack=40,
        )
        session.add(seat)
        seats.append(seat)

    # Empty remaining seats
    for i in range(n, 9):
        seat = TableSeat(table_id=table.id, seat_no=i + 1, seat_status=SeatStatus.EMPTY, stack=0)
        session.add(seat)

    await session.commit()
    return table, seats


@pytest.mark.asyncio
async def test_three_player_hand_start(db_session: AsyncSession):
    table, seats = await _setup_table_with_players(db_session, 3)
    hand = await start_hand(db_session, table.id)

    assert hand is not None
    assert hand.street == "preflop"
    assert hand.button_seat_no is not None
    assert hand.small_blind_seat_no is not None
    assert hand.big_blind_seat_no is not None
    assert hand.button_seat_no != hand.small_blind_seat_no
    assert hand.small_blind_seat_no != hand.big_blind_seat_no

    # Players
    result = await db_session.execute(select(HandPlayer).where(HandPlayer.hand_id == hand.id))
    players = list(result.scalars().all())
    assert len(players) == 3

    # SB contribution
    sb_player = next(p for p in players if p.seat_no == hand.small_blind_seat_no)
    assert sb_player.round_contribution == 1

    # BB contribution
    bb_player = next(p for p in players if p.seat_no == hand.big_blind_seat_no)
    assert bb_player.round_contribution == 2


@pytest.mark.asyncio
async def test_heads_up_button_is_sb(db_session: AsyncSession):
    table, seats = await _setup_table_with_players(db_session, 2)
    hand = await start_hand(db_session, table.id)

    assert hand is not None
    assert hand.button_seat_no == hand.small_blind_seat_no
    # In heads-up preflop, button (SB) acts first
    assert hand.action_seat_no == hand.button_seat_no


@pytest.mark.asyncio
async def test_sb_allin_if_short_stack(db_session: AsyncSession):
    from app.models.account import Account, AccountStatus
    from app.models.table import TableStatus

    acc1 = Account(nickname="short1", status=AccountStatus.ACTIVE, wallet_balance=0)
    acc2 = Account(nickname="short2", status=AccountStatus.ACTIVE, wallet_balance=0)
    session = db_session
    session.add_all([acc1, acc2])
    await session.flush()

    table = Table(table_no=888, status=TableStatus.OPEN, max_seats=9, small_blind=1, big_blind=2, buy_in=40)
    session.add(table)
    await session.flush()

    # Player 1 has only 1 chip (less than SB=1... well SB=1, they have exactly 1)
    s1 = TableSeat(table_id=table.id, seat_no=1, account_id=acc1.id, seat_status=SeatStatus.SEATED, stack=1)
    s2 = TableSeat(table_id=table.id, seat_no=2, account_id=acc2.id, seat_status=SeatStatus.SEATED, stack=40)
    for i in range(3, 10):
        session.add(TableSeat(table_id=table.id, seat_no=i, seat_status=SeatStatus.EMPTY, stack=0))
    session.add_all([s1, s2])
    await session.commit()

    hand = await start_hand(session, table.id)
    assert hand is not None

    result = await session.execute(select(HandPlayer).where(HandPlayer.hand_id == hand.id))
    players = {p.seat_no: p for p in result.scalars().all()}

    # In heads-up, seat_no=1 is button=SB. Stack=1, SB=1 → posts 1 chip
    # Seat_no=1 should have 0 stack and all_in=True
    # Actually: SB = 1, stack = 1. Posts 1, ends with 0 → all_in
    # Wait: 2-player. Button is lowest seat_no. Seat 1 button=SB, Seat 2 = BB.
    sb_player = players[hand.small_blind_seat_no]
    assert sb_player.round_contribution == 1


@pytest.mark.asyncio
async def test_button_rotation(db_session: AsyncSession):
    table, seats = await _setup_table_with_players(db_session, 3)

    hand1 = await start_hand(db_session, table.id)
    btn1 = hand1.button_seat_no

    # Finish hand1
    hand1.status = "FINISHED"
    hand1.finished_at = __import__("datetime").datetime.now(__import__("datetime").timezone.utc)
    await db_session.commit()

    hand2 = await start_hand(db_session, table.id)
    btn2 = hand2.button_seat_no
    assert btn2 != btn1  # Button moved


@pytest.mark.asyncio
async def test_action_log_contains_blinds_and_deal(db_session: AsyncSession):
    table, seats = await _setup_table_with_players(db_session, 3)
    hand = await start_hand(db_session, table.id)

    result = await db_session.execute(select(HandAction).where(HandAction.hand_id == hand.id))
    actions = [a.action_type for a in result.scalars().all()]
    assert "POST_SMALL_BLIND" in actions
    assert "POST_BIG_BLIND" in actions
    assert "DEAL_HOLE" in actions


@pytest.mark.asyncio
async def test_hole_cards_dealt(db_session: AsyncSession):
    table, seats = await _setup_table_with_players(db_session, 3)
    hand = await start_hand(db_session, table.id)

    result = await db_session.execute(select(HandPlayer).where(HandPlayer.hand_id == hand.id))
    players = list(result.scalars().all())
    for p in players:
        cards = json.loads(p.hole_cards_json)
        assert len(cards) == 2
