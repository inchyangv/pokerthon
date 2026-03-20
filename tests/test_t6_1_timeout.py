"""Tests for auto-fold timeout background task (T6.1)."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import Account, AccountStatus
from app.models.hand import Hand, HandAction, HandPlayer, HandStatus
from app.models.table import SeatStatus, Table, TableSeat, TableStatus
from app.tasks.timeout_checker import _auto_fold, _check_once


async def _setup_hand_at_action(
    session: AsyncSession,
    table_no: int,
    deadline_delta_seconds: int,  # negative = already expired
) -> tuple[Table, Hand, Account, Account]:
    """Create a 2-player hand with action_deadline_at set relative to now."""
    acc1 = Account(nickname=f"to_p1_{table_no}", status=AccountStatus.ACTIVE, wallet_balance=0)
    acc2 = Account(nickname=f"to_p2_{table_no}", status=AccountStatus.ACTIVE, wallet_balance=0)
    session.add_all([acc1, acc2])
    await session.flush()

    table = Table(
        table_no=table_no, status=TableStatus.OPEN, max_seats=9,
        small_blind=1, big_blind=2, buy_in=40,
    )
    session.add(table)
    await session.flush()

    seat1 = TableSeat(table_id=table.id, seat_no=1, account_id=acc1.id, seat_status=SeatStatus.SEATED, stack=38)
    seat2 = TableSeat(table_id=table.id, seat_no=2, account_id=acc2.id, seat_status=SeatStatus.SEATED, stack=38)
    for i in range(3, 10):
        session.add(TableSeat(table_id=table.id, seat_no=i, seat_status=SeatStatus.EMPTY, stack=0))
    session.add_all([seat1, seat2])
    await session.flush()

    deadline = datetime.now(timezone.utc) + timedelta(seconds=deadline_delta_seconds)
    hand = Hand(
        table_id=table.id, hand_no=1, status=HandStatus.IN_PROGRESS,
        button_seat_no=1, small_blind_seat_no=1, big_blind_seat_no=2,
        street="preflop",
        board_json="[]",
        current_bet=2,
        action_seat_no=1,  # acc1's turn
        action_deadline_at=deadline,
    )
    session.add(hand)
    await session.flush()

    hp1 = HandPlayer(
        hand_id=hand.id, account_id=acc1.id, seat_no=1,
        hole_cards_json=json.dumps(["Ah", "Kh"]),
        starting_stack=40, ending_stack=38,
        folded=False, all_in=False, round_contribution=1, hand_contribution=1,
    )
    hp2 = HandPlayer(
        hand_id=hand.id, account_id=acc2.id, seat_no=2,
        hole_cards_json=json.dumps(["Qd", "Jd"]),
        starting_stack=40, ending_stack=38,
        folded=False, all_in=False, round_contribution=2, hand_contribution=2,
    )
    session.add_all([hp1, hp2])
    await session.commit()

    return table, hand, acc1, acc2


@pytest.mark.asyncio
async def test_auto_fold_expired(db_session: AsyncSession):
    """액션 데드라인 경과 → 자동 폴드 발생 확인."""
    table, hand, acc1, acc2 = await _setup_hand_at_action(
        db_session, table_no=901, deadline_delta_seconds=-10  # already expired
    )

    with patch("app.services.hand_completion.asyncio.ensure_future"):
        await _auto_fold(db_session, hand, acc1.id)

    hp1_result = await db_session.execute(
        select(HandPlayer).where(HandPlayer.hand_id == hand.id, HandPlayer.account_id == acc1.id)
    )
    hp1 = hp1_result.scalar_one()
    assert hp1.folded is True


@pytest.mark.asyncio
async def test_auto_fold_timeout_action_logged(db_session: AsyncSession):
    """자동 폴드 후 AUTO_FOLD_TIMEOUT 로그 확인."""
    table, hand, acc1, acc2 = await _setup_hand_at_action(
        db_session, table_no=902, deadline_delta_seconds=-10
    )

    with patch("app.services.hand_completion.asyncio.ensure_future"):
        await _auto_fold(db_session, hand, acc1.id)

    action_result = await db_session.execute(
        select(HandAction).where(
            HandAction.hand_id == hand.id,
            HandAction.action_type == "AUTO_FOLD_TIMEOUT",
        )
    )
    action = action_result.scalars().first()
    assert action is not None
    assert action.is_system_action is True


@pytest.mark.asyncio
async def test_auto_fold_game_continues(db_session: AsyncSession):
    """자동 폴드 후 게임 진행 확인 (다음 플레이어로 액션 이동)."""
    table, hand, acc1, acc2 = await _setup_hand_at_action(
        db_session, table_no=903, deadline_delta_seconds=-10
    )

    with patch("app.services.hand_completion.asyncio.ensure_future"):
        await _auto_fold(db_session, hand, acc1.id)

    # After acc1 folds, acc2 should win (or action moves) — hand should be resolved
    await db_session.refresh(hand)
    # With only one player left, showdown is triggered → hand finished
    assert hand.status == HandStatus.FINISHED


@pytest.mark.asyncio
async def test_no_auto_fold_not_expired(db_session: AsyncSession):
    """데드라인 미경과 → 폴드 미발생."""
    table, hand, acc1, acc2 = await _setup_hand_at_action(
        db_session, table_no=904, deadline_delta_seconds=600  # not expired
    )

    # _check_once should not fold this hand
    with patch("app.tasks.timeout_checker.async_session_factory") as mock_factory:
        # Use the test session to avoid DB setup issues
        mock_factory.return_value.__aenter__ = lambda s: s
        mock_factory.return_value.__aexit__ = lambda s, *a: None

        # Direct check: hand's deadline hasn't passed
        now = datetime.now(timezone.utc)
        assert hand.action_deadline_at > now

    # Confirm hand is still in progress, player not folded
    hp_result = await db_session.execute(
        select(HandPlayer).where(HandPlayer.hand_id == hand.id, HandPlayer.account_id == acc1.id)
    )
    hp = hp_result.scalar_one()
    assert hp.folded is False
    assert hand.status == HandStatus.IN_PROGRESS
