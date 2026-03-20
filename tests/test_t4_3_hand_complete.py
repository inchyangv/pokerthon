"""Tests for hand completion (T4.3)."""
from __future__ import annotations

import asyncio
import json
from unittest.mock import patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import Account, AccountStatus
from app.models.chip import ChipLedger, LedgerReasonType
from app.models.hand import Hand, HandAction, HandPlayer, HandResult, HandStatus, TableSnapshot
from app.models.table import SeatStatus, Table, TableSeat, TableStatus
from app.services.hand_completion import complete_hand
from app.services.hand_service import start_hand


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _make_account(session: AsyncSession, nickname: str) -> Account:
    acc = Account(nickname=nickname, status=AccountStatus.ACTIVE, wallet_balance=100)
    session.add(acc)
    await session.flush()
    return acc


async def _setup_hand(
    session: AsyncSession,
    players_data: list,  # [(seat_no, stack, seat_status)]
    table_no: int = 800,
) -> tuple[Table, Hand, dict[int, TableSeat], dict[int, HandPlayer]]:
    table = Table(
        table_no=table_no, status=TableStatus.OPEN, max_seats=9,
        small_blind=1, big_blind=2, buy_in=40,
    )
    session.add(table)
    await session.flush()

    seat_map: dict[int, TableSeat] = {}
    acc_map: dict[int, Account] = {}
    for i, (seat_no, stack, seat_status) in enumerate(players_data):
        acc = await _make_account(session, f"hc{table_no}_{i}")
        seat = TableSeat(
            table_id=table.id, seat_no=seat_no,
            account_id=acc.id, seat_status=seat_status, stack=stack,
        )
        session.add(seat)
        seat_map[seat_no] = seat
        acc_map[seat_no] = acc

    # empty remaining seats
    used = {s for s, _, _ in players_data}
    for i in range(1, 10):
        if i not in used:
            session.add(TableSeat(table_id=table.id, seat_no=i, seat_status=SeatStatus.EMPTY, stack=0))

    await session.flush()

    hand = Hand(
        table_id=table.id, hand_no=1, status=HandStatus.IN_PROGRESS,
        button_seat_no=players_data[0][0],
        small_blind_seat_no=None, big_blind_seat_no=None,
        street="showdown", board_json=json.dumps(["2h", "7c", "Jd", "Ks", "3s"]),
        current_bet=0, action_seat_no=None,
    )
    session.add(hand)
    await session.flush()

    hp_map: dict[int, HandPlayer] = {}
    for i, (seat_no, stack, seat_status) in enumerate(players_data):
        acc = acc_map[seat_no]
        hp = HandPlayer(
            hand_id=hand.id, account_id=acc.id, seat_no=seat_no,
            hole_cards_json=json.dumps(["Ah", "Kh"]),
            starting_stack=40, ending_stack=stack,
            folded=(seat_status == SeatStatus.EMPTY),
            all_in=(stack == 0),
            round_contribution=0, hand_contribution=40 - stack,
        )
        session.add(hp)
        hp_map[seat_no] = hp

    await session.commit()
    return table, hand, seat_map, hp_map


_dummy_result: dict = {
    "pot_view": {"main_pot": 40, "side_pots": [], "uncalled_return": None},
    "awards": {1: 40},
    "summaries": [{"type": "fold_win", "winners": [1], "amount": 40}],
}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_hand_status_finished(db_session: AsyncSession):
    """핸드 종료 시 status=FINISHED, finished_at 기록."""
    # suppress background next-hand task
    with patch("app.services.hand_completion.asyncio.ensure_future"):
        table, hand, seat_map, hp_map = await _setup_hand(
            db_session,
            [(1, 40, SeatStatus.SEATED), (2, 0, SeatStatus.SEATED)],
            table_no=800,
        )
        await complete_hand(db_session, hand, _dummy_result)

    await db_session.refresh(hand)
    assert hand.status == HandStatus.FINISHED
    assert hand.finished_at is not None


@pytest.mark.asyncio
async def test_hand_result_saved(db_session: AsyncSession):
    """hand_results에 결과 JSON 저장."""
    with patch("app.services.hand_completion.asyncio.ensure_future"):
        table, hand, seat_map, hp_map = await _setup_hand(
            db_session,
            [(1, 40, SeatStatus.SEATED), (2, 0, SeatStatus.SEATED)],
            table_no=801,
        )
        await complete_hand(db_session, hand, _dummy_result)

    result_q = await db_session.execute(
        select(HandResult).where(HandResult.hand_id == hand.id)
    )
    hr = result_q.scalar_one_or_none()
    assert hr is not None
    data = json.loads(hr.result_json)
    assert "board" in data
    assert "awards" in data


@pytest.mark.asyncio
async def test_hand_finished_action_logged(db_session: AsyncSession):
    """HAND_FINISHED 액션 로그 기록."""
    with patch("app.services.hand_completion.asyncio.ensure_future"):
        table, hand, seat_map, hp_map = await _setup_hand(
            db_session,
            [(1, 40, SeatStatus.SEATED), (2, 0, SeatStatus.SEATED)],
            table_no=802,
        )
        await complete_hand(db_session, hand, _dummy_result)

    action_q = await db_session.execute(
        select(HandAction).where(
            HandAction.hand_id == hand.id,
            HandAction.action_type == "HAND_FINISHED",
        )
    )
    assert action_q.scalar_one_or_none() is not None


@pytest.mark.asyncio
async def test_stack_zero_auto_evict(db_session: AsyncSession):
    """스택 0 플레이어 자동 이석 + TABLE_CASHOUT(delta=0) 원장 기록."""
    with patch("app.services.hand_completion.asyncio.ensure_future"):
        table, hand, seat_map, hp_map = await _setup_hand(
            db_session,
            [(1, 40, SeatStatus.SEATED), (2, 0, SeatStatus.SEATED)],  # P2 stack=0
            table_no=803,
        )
        await complete_hand(db_session, hand, _dummy_result)

    await db_session.refresh(seat_map[2])
    assert seat_map[2].seat_status == SeatStatus.EMPTY
    assert seat_map[2].account_id is None

    # TABLE_CASHOUT ledger with delta=0
    acc_id = hp_map[2].account_id
    ledger_q = await db_session.execute(
        select(ChipLedger).where(
            ChipLedger.account_id == acc_id,
            ChipLedger.reason_type == LedgerReasonType.TABLE_CASHOUT,
        )
    )
    entry = ledger_q.scalars().first()
    assert entry is not None
    assert entry.delta == 0


@pytest.mark.asyncio
async def test_leaving_after_hand_evict(db_session: AsyncSession):
    """LEAVING_AFTER_HAND 플레이어 → 이석 + 칩 반환."""
    with patch("app.services.hand_completion.asyncio.ensure_future"):
        table, hand, seat_map, hp_map = await _setup_hand(
            db_session,
            [
                (1, 40, SeatStatus.SEATED),
                (2, 30, SeatStatus.LEAVING_AFTER_HAND),  # wants to leave
            ],
            table_no=804,
        )
        # give the account some wallet so we can verify balance increases
        acc_id = hp_map[2].account_id
        acc_q = await db_session.execute(select(Account).where(Account.id == acc_id))
        acc = acc_q.scalar_one()
        before_balance = acc.wallet_balance

        await complete_hand(db_session, hand, _dummy_result)

    await db_session.refresh(seat_map[2])
    assert seat_map[2].seat_status == SeatStatus.EMPTY
    assert seat_map[2].account_id is None

    await db_session.refresh(acc)
    assert acc.wallet_balance == before_balance + 30


@pytest.mark.asyncio
async def test_snapshot_bumped(db_session: AsyncSession):
    """table_snapshot version 증가."""
    with patch("app.services.hand_completion.asyncio.ensure_future"):
        table, hand, seat_map, hp_map = await _setup_hand(
            db_session,
            [(1, 40, SeatStatus.SEATED), (2, 20, SeatStatus.SEATED)],
            table_no=805,
        )
        await complete_hand(db_session, hand, _dummy_result)

    snap_q = await db_session.execute(
        select(TableSnapshot).where(TableSnapshot.table_id == table.id)
    )
    snap = snap_q.scalar_one_or_none()
    assert snap is not None
    assert snap.version >= 1


@pytest.mark.asyncio
async def test_next_hand_not_started_paused(db_session: AsyncSession):
    """PAUSED 테이블 → 다음 핸드 미시작."""
    with patch("app.services.hand_completion.asyncio.ensure_future") as mock_future:
        table, hand, seat_map, hp_map = await _setup_hand(
            db_session,
            [(1, 40, SeatStatus.SEATED), (2, 20, SeatStatus.SEATED)],
            table_no=806,
        )
        # pause the table
        table.status = TableStatus.PAUSED
        await db_session.commit()

        await db_session.refresh(table)
        await complete_hand(db_session, hand, _dummy_result)

        # ensure_future should NOT be called for paused table
        mock_future.assert_not_called()


@pytest.mark.asyncio
async def test_next_hand_trigger_open_table(db_session: AsyncSession):
    """2명 이상 남음 + OPEN 테이블 → ensure_future 호출."""
    with patch("app.services.hand_completion.asyncio.ensure_future") as mock_future:
        table, hand, seat_map, hp_map = await _setup_hand(
            db_session,
            [(1, 40, SeatStatus.SEATED), (2, 20, SeatStatus.SEATED)],
            table_no=807,
        )
        await complete_hand(db_session, hand, _dummy_result)

        mock_future.assert_called_once()


@pytest.mark.asyncio
async def test_next_hand_auto_start_integration(db_session: AsyncSession):
    """start_hand 통합: 조건 충족 시 다음 핸드 시작 가능 확인."""
    # Directly test start_hand after complete_hand cleans up
    with patch("app.services.hand_completion.asyncio.ensure_future"):
        table, hand, seat_map, hp_map = await _setup_hand(
            db_session,
            [(1, 40, SeatStatus.SEATED), (2, 20, SeatStatus.SEATED)],
            table_no=808,
        )
        await complete_hand(db_session, hand, _dummy_result)

    # After completion, seats still have stacks → start_hand should succeed
    new_hand = await start_hand(db_session, table.id)
    assert new_hand is not None
    assert new_hand.hand_no == 2


@pytest.mark.asyncio
async def test_one_player_no_next_hand(db_session: AsyncSession):
    """1명만 남음 → 다음 핸드 미시작."""
    with patch("app.services.hand_completion.asyncio.ensure_future") as mock_future:
        table, hand, seat_map, hp_map = await _setup_hand(
            db_session,
            [(1, 40, SeatStatus.SEATED), (2, 0, SeatStatus.SEATED)],  # P2 will be evicted
            table_no=809,
        )
        await complete_hand(db_session, hand, _dummy_result)

        # P2 evicted (stack=0), only P1 left → no next hand
        mock_future.assert_not_called()
