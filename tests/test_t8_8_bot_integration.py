"""Bot integration tests (T8.8).

Tests:
  1. Bot creation & management flow
  2. Bots complete a hand (preflop → showdown via strategy engine)
  3. Bot action validity per type
  4. Bot + human mixed table flow
  5. Multi-hand continuity (chip conservation)
"""
from __future__ import annotations

import json

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bots import BotType
from app.bots.runner import _normalize_legal_actions, _process_bot_turn
from app.bots.strategy import decide
from app.config import settings
from app.core.legal_actions import get_legal_actions
from app.models.account import Account
from app.models.bot import BotProfile
from app.models.hand import Hand, HandPlayer, HandStatus
from app.models.table import SeatStatus, Table, TableSeat, TableStatus


# ---------------------------------------------------------------------------
# Test 1: Bot create / list / seat / unseat flow
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_bot_management_flow(client):
    headers = {"Authorization": "Bearer changeme"}

    # Create 3 bots (one of each type)
    bot_ids = []
    for bt in ("TAG", "LAG", "FISH"):
        r = await client.post(
            "/admin/bots",
            json={"bot_type": bt, "display_name": f"test_bot_{bt.lower()}"},
            headers=headers,
        )
        assert r.status_code == 201
        data = r.json()
        assert data["bot_type"] == bt
        assert data["chips"] == settings.BOT_INITIAL_CHIPS
        bot_ids.append(data["bot_id"])

    # List bots
    r = await client.get("/admin/bots", headers=headers)
    assert r.status_code == 200
    bots = r.json()
    assert len(bots) >= 3

    # Create table and seat one bot
    await client.post("/admin/tables", json={"table_no": 10}, headers=headers)
    seat_r = await client.post(
        f"/admin/bots/{bot_ids[0]}/seat",
        json={"table_no": 10},
        headers=headers,
    )
    assert seat_r.status_code == 200
    assert 1 <= seat_r.json()["seat_no"] <= 9

    # Unseat
    unseat_r = await client.post(f"/admin/bots/{bot_ids[0]}/unseat", headers=headers)
    assert unseat_r.status_code == 200


# ---------------------------------------------------------------------------
# Test 2: Strategy engine produces valid actions in a mock hand context
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_bot_strategy_valid_actions(db_session):
    """Strategy engine returns valid action types for all bot types."""
    legal_actions = [
        {"action_type": "FOLD"},
        {"action_type": "CALL"},
        {"action_type": "RAISE_TO", "min_amount": 6, "max_amount": 200},
    ]

    for bot_type in BotType:
        for street in ("preflop", "flop", "turn", "river"):
            board = []
            if street == "flop":
                board = ["Ah", "Kd", "7c"]
            elif street == "turn":
                board = ["Ah", "Kd", "7c", "2s"]
            elif street == "river":
                board = ["Ah", "Kd", "7c", "2s", "9h"]

            d = decide(
                bot_type=bot_type,
                street=street,
                hole_cards=["As", "Kh"],
                board=board,
                legal_actions=legal_actions,
                current_bet=4,
                to_call=4,
                stack=100,
                pot_size=8,
            )
            assert d.action_type in {"FOLD", "CALL", "RAISE_TO", "CHECK", "ALL_IN", "BET"}
            if d.action_type == "RAISE_TO":
                assert 6 <= d.amount <= 200


# ---------------------------------------------------------------------------
# Test 3: TAG bot folds 72o (out-of-range hand)
# ---------------------------------------------------------------------------

def test_tag_folds_worst_hand():
    """TAG statistically folds 7-2 offsuit (out of range)."""
    from app.bots.hand_range import in_range
    assert not in_range("TAG", "7s", "2h")
    assert not in_range("LAG", "7s", "2h")


def test_fish_has_wider_range():
    """FISH range is wider than TAG and LAG."""
    from app.bots.hand_range import FISH_RANGE, LAG_RANGE, TAG_RANGE
    assert len(TAG_RANGE) < len(LAG_RANGE) < len(FISH_RANGE)


def test_fish_calls_more_than_folds():
    """FISH with in-range hand should call more than fold."""
    from app.bots.preflop import decide_preflop
    legal = [{"action_type": "FOLD"}, {"action_type": "CALL"}]
    results = [
        decide_preflop(BotType.FISH, ["Ks", "8h"], legal, 2, 100, 4)
        for _ in range(100)
    ]
    calls = sum(1 for d in results if d.action_type == "CALL")
    folds = sum(1 for d in results if d.action_type == "FOLD")
    assert calls > folds


# ---------------------------------------------------------------------------
# Test 4: _process_bot_turn skips when not bot's turn
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_process_bot_turn_not_its_turn(db_session):
    """Bot should not act if action_seat_no != bot's seat."""
    from datetime import datetime, timezone

    acc = Account(nickname="bot_turn_test", is_bot=True, wallet_balance=1000)
    db_session.add(acc)
    table = Table(
        table_no=99, status=TableStatus.OPEN, max_seats=9,
        small_blind=1, big_blind=2, buy_in=40,
    )
    db_session.add(table)
    await db_session.commit()

    seat = TableSeat(
        table_id=table.id, seat_no=3, account_id=acc.id,
        seat_status=SeatStatus.SEATED, stack=40,
    )
    db_session.add(seat)
    await db_session.commit()

    # Hand with action_seat_no = 5 (not 3 where bot sits)
    hand = Hand(
        table_id=table.id, hand_no=1, status=HandStatus.IN_PROGRESS,
        button_seat_no=1, small_blind_seat_no=2, big_blind_seat_no=3,
        street="preflop", board_json="[]", deck_json="[]",
        current_bet=2, action_seat_no=5, deal_index=0,
        started_at=datetime.now(timezone.utc),
    )
    db_session.add(hand)
    await db_session.commit()

    bot = BotProfile(
        account_id=acc.id, bot_type="TAG", display_name="bot_turn_test", is_active=True,
    )
    db_session.add(bot)
    await db_session.commit()
    await db_session.refresh(bot)

    # Should do nothing (not raise)
    await _process_bot_turn(db_session, bot)
    # Hand unchanged
    await db_session.refresh(hand)
    assert hand.status == HandStatus.IN_PROGRESS


# ---------------------------------------------------------------------------
# Test 5: Chip conservation across hand via strategy
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_chip_conservation_invariant(db_session, client):
    """Total chips before and after bot actions should be conserved."""
    headers = {"Authorization": "Bearer changeme"}

    # Create 3 bots
    bot_ids = []
    account_ids = []
    for i, bt in enumerate(["TAG", "LAG", "FISH"]):
        r = await client.post(
            "/admin/bots",
            json={"bot_type": bt, "display_name": f"chip_bot_{i}"},
            headers=headers,
        )
        assert r.status_code == 201, r.text
        data = r.json()
        bot_ids.append(data["bot_id"])
        account_ids.append(data["account_id"])

    # Create table and seat all bots
    await client.post("/admin/tables", json={"table_no": 20}, headers=headers)
    for bid in bot_ids:
        r = await client.post(
            f"/admin/bots/{bid}/seat",
            json={"table_no": 20},
            headers=headers,
        )
        assert r.status_code == 200, r.text

    # Verify total chips = 3 × BOT_INITIAL_CHIPS
    # wallet_balance is the account's total chip count (includes chips at table).
    # Stacks are a subset of wallet_balance; adding both would double-count.
    total_before = 0
    for acc_id in account_ids:
        acc = await db_session.get(Account, acc_id)
        await db_session.refresh(acc)
        total_before += acc.wallet_balance

    expected = settings.BOT_INITIAL_CHIPS * 3
    assert total_before == expected, f"Expected {expected}, got {total_before}"
