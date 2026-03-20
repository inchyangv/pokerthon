"""Tests for bot runner turn detection and action submission."""
import json
import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from app.bots import BotType
from app.bots.runner import _normalize_legal_actions, _process_bot_turn


# --- normalize_legal_actions ---

def test_normalize_fold():
    raw = [{"type": "FOLD"}]
    result = _normalize_legal_actions(raw)
    assert result[0]["action_type"] == "FOLD"


def test_normalize_raise_with_min_max():
    raw = [{"type": "RAISE_TO", "min": 10, "max": 100}]
    result = _normalize_legal_actions(raw)
    assert result[0]["action_type"] == "RAISE_TO"
    assert result[0]["min_amount"] == 10
    assert result[0]["max_amount"] == 100


def test_normalize_call_with_amount():
    raw = [{"type": "CALL", "amount": 8}]
    result = _normalize_legal_actions(raw)
    assert result[0]["action_type"] == "CALL"
    assert result[0]["amount"] == 8


def test_normalize_all_types():
    raw = [
        {"type": "FOLD"},
        {"type": "CALL", "amount": 5},
        {"type": "RAISE_TO", "min": 10, "max": 200},
        {"type": "ALL_IN", "amount": 150},
    ]
    result = _normalize_legal_actions(raw)
    assert len(result) == 4
    types = [a["action_type"] for a in result]
    assert "FOLD" in types
    assert "CALL" in types
    assert "RAISE_TO" in types
    assert "ALL_IN" in types


# --- _process_bot_turn: not seated ---

@pytest.mark.asyncio
async def test_process_bot_turn_not_seated(db_session):
    """Bot not seated anywhere → no action."""
    from app.models.account import Account
    from app.models.bot import BotProfile

    acc = Account(nickname="bot_test", is_bot=True, wallet_balance=1000)
    db_session.add(acc)
    await db_session.commit()
    await db_session.refresh(acc)

    bot = BotProfile(
        account_id=acc.id,
        bot_type="TAG",
        display_name="bot_test",
        is_active=True,
    )
    db_session.add(bot)
    await db_session.commit()
    await db_session.refresh(bot)

    # Should not raise or do anything
    await _process_bot_turn(db_session, bot)


@pytest.mark.asyncio
async def test_process_bot_turn_no_active_hand(db_session):
    """Bot seated but no active hand → no action."""
    from app.models.account import Account
    from app.models.bot import BotProfile
    from app.models.table import Table, TableSeat, SeatStatus, TableStatus

    acc = Account(nickname="bot_test2", is_bot=True, wallet_balance=1000)
    db_session.add(acc)
    table = Table(table_no=99, status=TableStatus.OPEN, max_seats=9, small_blind=1, big_blind=2, buy_in=40)
    db_session.add(table)
    await db_session.commit()

    seat = TableSeat(
        table_id=table.id, seat_no=1, account_id=acc.id,
        seat_status=SeatStatus.SEATED, stack=40,
    )
    db_session.add(seat)
    await db_session.commit()

    bot = BotProfile(
        account_id=acc.id, bot_type="TAG", display_name="bot_test2", is_active=True,
    )
    db_session.add(bot)
    await db_session.commit()
    await db_session.refresh(bot)

    # No hand exists → should return without error
    await _process_bot_turn(db_session, bot)
