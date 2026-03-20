"""Tests for showdown resolution (T4.2)."""
import json

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import Account, AccountStatus
from app.models.hand import Hand, HandAction, HandPlayer, HandStatus
from app.models.table import SeatStatus, Table, TableSeat, TableStatus
from app.services.showdown_service import resolve_showdown

# Board used in most tests: 2h 7c Jd Ks 3s (no straight/flush possible)
BOARD = ["2h", "7c", "Jd", "Ks", "3s"]


async def _setup_showdown(
    session: AsyncSession,
    players_data: list,  # [(seat_no, hole_cards, contribution, folded, ending_stack_before)]
    button_seat_no: int = 1,
    table_no: int = 999,
) -> tuple[Hand, dict[int, TableSeat], dict[int, HandPlayer]]:
    """Create a minimal hand at showdown state."""
    # Accounts
    accs = []
    for i in range(len(players_data)):
        acc = Account(
            nickname=f"sd{table_no}_{i}", status=AccountStatus.ACTIVE, wallet_balance=0
        )
        session.add(acc)
    await session.flush()
    accs_q = await session.execute(
        select(Account).where(Account.nickname.like(f"sd{table_no}_%"))
    )
    accs = sorted(accs_q.scalars().all(), key=lambda a: a.nickname)

    # Table
    table = Table(
        table_no=table_no, status=TableStatus.OPEN, max_seats=9,
        small_blind=1, big_blind=2, buy_in=40,
    )
    session.add(table)
    await session.flush()

    # Seats
    seat_map: dict[int, TableSeat] = {}
    for i, (seat_no, _, contrib, _, stack) in enumerate(players_data):
        seat = TableSeat(
            table_id=table.id, seat_no=seat_no, account_id=accs[i].id,
            seat_status=SeatStatus.SEATED, stack=stack,
        )
        session.add(seat)
        seat_map[seat_no] = seat
    for i in range(len(players_data), 9):
        session.add(
            TableSeat(table_id=table.id, seat_no=i + 1, seat_status=SeatStatus.EMPTY, stack=0)
        )
    await session.flush()

    # Hand
    hand = Hand(
        table_id=table.id, hand_no=1, status=HandStatus.IN_PROGRESS,
        button_seat_no=button_seat_no, small_blind_seat_no=None, big_blind_seat_no=None,
        street="showdown", board_json=json.dumps(BOARD),
        current_bet=0, action_seat_no=None,
    )
    session.add(hand)
    await session.flush()

    # HandPlayers
    hp_map: dict[int, HandPlayer] = {}
    for i, (seat_no, hole_cards, contrib, folded, stack) in enumerate(players_data):
        hp = HandPlayer(
            hand_id=hand.id, account_id=accs[i].id, seat_no=seat_no,
            hole_cards_json=json.dumps(hole_cards),
            starting_stack=stack + contrib,
            ending_stack=stack,          # stack AFTER contributing (before winning)
            folded=folded, all_in=(stack == 0),
            round_contribution=0, hand_contribution=contrib,
        )
        session.add(hp)
        hp_map[seat_no] = hp
    await session.commit()

    return hand, seat_map, hp_map


# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_two_player_showdown(db_session: AsyncSession):
    """2인 쇼다운: 고패 A가 Q를 이김. 스택 갱신 확인."""
    # Board: 2h 7c Jd Ks 3s
    # P1 (seat 1): Ah Qh → best: A-K-Q-J-7 (high card A)
    # P2 (seat 2): 9d 8d → best: K-J-9-8-7 (high card K)
    # P1 wins
    players = [
        (1, ["Ah", "Qh"], 20, False, 20),  # seat1, hole, contrib, folded, stack_before_showdown
        (2, ["9d", "8d"], 20, False, 20),
    ]
    hand, seat_map, hp_map = await _setup_showdown(db_session, players, button_seat_no=1)

    result = await resolve_showdown(db_session, hand)
    await db_session.commit()

    # P1 wins 40 (both contributions)
    await db_session.refresh(hp_map[1])
    await db_session.refresh(hp_map[2])
    assert hp_map[1].ending_stack == 20 + 40   # 20 (stack) + 40 (pot win)
    assert hp_map[2].ending_stack == 20          # lost contribution

    # Table seat stacks updated
    await db_session.refresh(seat_map[1])
    await db_session.refresh(seat_map[2])
    assert seat_map[1].stack == 60
    assert seat_map[2].stack == 20

    # Chip conservation: 40 + 40 = 80 total starting = 60 + 20
    assert seat_map[1].stack + seat_map[2].stack == 40 + 40

    # SHOWDOWN action logged
    actions_q = await db_session.execute(
        select(HandAction).where(HandAction.hand_id == hand.id, HandAction.action_type == "SHOWDOWN")
    )
    assert actions_q.scalars().first() is not None


@pytest.mark.asyncio
async def test_split_pot(db_session: AsyncSession):
    """동점 분배: 두 플레이어가 동일 핸드 → 균등 분배."""
    # Both get A-K-Q-J-7 using board
    players = [
        (1, ["Ah", "Qs"], 20, False, 20),  # A-K-Q-J-7
        (2, ["Ac", "Qd"], 20, False, 20),  # A-K-Q-J-7 (tie)
    ]
    hand, seat_map, hp_map = await _setup_showdown(db_session, players, button_seat_no=1, table_no=998)

    await resolve_showdown(db_session, hand)
    await db_session.commit()

    await db_session.refresh(hp_map[1])
    await db_session.refresh(hp_map[2])
    # 40 / 2 = 20 each. Net: each gets back their own 20 contribution.
    assert hp_map[1].ending_stack == 40
    assert hp_map[2].ending_stack == 40


@pytest.mark.asyncio
async def test_odd_chip_distribution(db_session: AsyncSession):
    """홀수 칩 분배: 3명 동점, 폴드된 기여금 포함 → odd chip goes to seat closest to button."""
    # P1 folded (contributed 5), P2 and P3 tied, pot = 15
    # Button at seat 1 → odd chip goes to seat 2 (first clockwise from button among winners [2,3])
    players = [
        (1, ["5c", "6c"], 5, True, 35),   # folded
        (2, ["Ah", "Qs"], 5, False, 35),  # A-K-Q-J-7
        (3, ["Ac", "Qd"], 5, False, 35),  # A-K-Q-J-7 (tie with P2)
    ]
    hand, seat_map, hp_map = await _setup_showdown(db_session, players, button_seat_no=1, table_no=997)

    await resolve_showdown(db_session, hand)
    await db_session.commit()

    await db_session.refresh(hp_map[1])
    await db_session.refresh(hp_map[2])
    await db_session.refresh(hp_map[3])

    # Total pot = 15 (5 * 3 contributions). Split between seats 2 and 3.
    # 15 / 2 = 7 remainder 1. Seat 2 gets 8 (first clockwise from button=1), seat 3 gets 7.
    assert hp_map[2].ending_stack == 35 + 8
    assert hp_map[3].ending_stack == 35 + 7
    assert hp_map[1].ending_stack == 35   # folded, no win

    # Chip conservation: starting = 40*3 = 120
    total = hp_map[1].ending_stack + hp_map[2].ending_stack + hp_map[3].ending_stack
    assert total == 40 + 40 + 40


@pytest.mark.asyncio
async def test_side_pot_showdown(db_session: AsyncSession):
    """사이드팟 쇼다운: 메인팟은 P1(all-in) 승, 사이드팟은 P2 승."""
    # Board: 2h 7c Jd Ks 3s
    # P1 (all-in for 5, strong hand): Ah Qh → A-K-Q-J-7
    # P2 (contrib 20, medium hand):  9d 8d → K-J-9-8-7
    # P3 (contrib 20, weak hand):    5d 4d → K-J-7-5-4
    # Main pot: 5*3=15, eligible=[1,2,3]. P1 wins (A > K > K).
    # Side pot: (20-5)*2=30, eligible=[2,3]. P2 wins (K-J-9-8-7 > K-J-7-5-4).
    players = [
        (1, ["Ah", "Qh"], 5,  False, 0),   # all-in
        (2, ["9d", "8d"], 20, False, 20),
        (3, ["5d", "4d"], 20, False, 20),
    ]
    hand, seat_map, hp_map = await _setup_showdown(db_session, players, button_seat_no=1, table_no=996)

    await resolve_showdown(db_session, hand)
    await db_session.commit()

    await db_session.refresh(hp_map[1])
    await db_session.refresh(hp_map[2])
    await db_session.refresh(hp_map[3])

    assert hp_map[1].ending_stack == 0 + 15   # won main pot 15
    assert hp_map[2].ending_stack == 20 + 30  # won side pot 30
    assert hp_map[3].ending_stack == 20        # lost

    # Chip conservation: P1 started with 5, P2/P3 with 40 each = 85
    total = hp_map[1].ending_stack + hp_map[2].ending_stack + hp_map[3].ending_stack
    assert total == 5 + 40 + 40


@pytest.mark.asyncio
async def test_fold_win(db_session: AsyncSession):
    """폴드 승리: 1명만 남음 → 카드 미공개, 전액 수령."""
    players = [
        (1, ["Ah", "Kh"], 20, False, 20),
        (2, ["Qd", "Jd"], 20, True,  20),   # folded
    ]
    hand, seat_map, hp_map = await _setup_showdown(db_session, players, button_seat_no=1, table_no=995)

    await resolve_showdown(db_session, hand)
    await db_session.commit()

    await db_session.refresh(hp_map[1])
    await db_session.refresh(hp_map[2])

    assert hp_map[1].ending_stack == 20 + 40   # wins entire pot
    assert hp_map[2].ending_stack == 20         # folded

    # No SHOWDOWN action (fold win → no card reveal)
    actions_q = await db_session.execute(
        select(HandAction).where(HandAction.hand_id == hand.id, HandAction.action_type == "SHOWDOWN")
    )
    assert actions_q.scalars().first() is None

    # POT_AWARDED is logged
    award_q = await db_session.execute(
        select(HandAction).where(HandAction.hand_id == hand.id, HandAction.action_type == "POT_AWARDED")
    )
    assert award_q.scalars().first() is not None


@pytest.mark.asyncio
async def test_chip_conservation(db_session: AsyncSession):
    """칩 보존 법칙: 핸드 전 총 스택 == 핸드 후 총 스택."""
    # All-in scenario with side pot
    players = [
        (1, ["Ah", "Kh"], 10, False, 0),    # all-in
        (2, ["Qd", "Jd"], 30, False, 10),
        (3, ["9s", "8s"], 30, False, 10),
        (4, ["7c", "6c"], 20, True,  20),    # folded mid-hand
    ]
    # Total starting stacks: 10 + 40 + 40 + 40 = 130
    hand, seat_map, hp_map = await _setup_showdown(db_session, players, button_seat_no=1, table_no=994)

    await resolve_showdown(db_session, hand)
    await db_session.commit()

    for p in hp_map.values():
        await db_session.refresh(p)

    total_after = sum(p.ending_stack for p in hp_map.values())
    total_before = sum(p.starting_stack for p in hp_map.values())
    assert total_after == total_before, f"Chip leak: before={total_before} after={total_after}"
