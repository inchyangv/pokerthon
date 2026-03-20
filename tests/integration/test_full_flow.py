"""Integration tests: full game flow scenarios (T7.4).

Scenario 1: 2-player full flow (preflop → showdown, chip conservation)
Scenario 2: 3-player multi all-in (side pots)
Scenario 3: Timeout auto-fold
Scenario 4: Stand during hand (LEAVING_AFTER_HAND)
Scenario 5: Multi-table concurrent play
Regression: chip conservation, action log seq order, public API hole card privacy
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.signature import sign_request
from app.models.account import Account, AccountStatus
from app.models.hand import Hand, HandAction, HandPlayer, HandStatus
from app.models.table import SeatStatus, Table, TableSeat, TableStatus
from app.services.hand_service import start_hand
from app.tasks.timeout_checker import _auto_fold

ADMIN = {"Authorization": f"Bearer {settings.ADMIN_PASSWORD}"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _setup_player(
    client: AsyncClient,
    nickname: str,
    chips: int = 200,
) -> tuple[int, str, str]:
    """Create account, issue credentials, grant chips."""
    r = await client.post("/admin/accounts", json={"nickname": nickname}, headers=ADMIN)
    assert r.status_code in (200, 201), r.text
    acc_id = r.json()["id"]
    r2 = await client.post(f"/admin/accounts/{acc_id}/credentials", headers=ADMIN)
    api_key = r2.json()["api_key"]
    secret_key = r2.json()["secret_key"]
    r3 = await client.post(
        f"/admin/accounts/{acc_id}/grant",
        json={"amount": chips, "reason": "test"},
        headers=ADMIN,
    )
    assert r3.status_code == 200, r3.text
    return acc_id, api_key, secret_key


async def _sit(
    client: AsyncClient,
    table_no: int,
    api_key: str,
    secret_key: str,
    seat_no: int | None = None,
) -> None:
    path = f"/v1/private/tables/{table_no}/sit"
    body_dict: dict = {}
    if seat_no is not None:
        body_dict["seat_no"] = seat_no
    payload = json.dumps(body_dict).encode()
    hdrs = sign_request(api_key, secret_key, "POST", path, body=payload)
    hdrs["Content-Type"] = "application/json"
    r = await client.post(path, content=payload, headers=hdrs)
    assert r.status_code == 200, f"sit failed: {r.text}"


async def _stand(
    client: AsyncClient,
    table_no: int,
    api_key: str,
    secret_key: str,
) -> int:
    path = f"/v1/private/tables/{table_no}/stand"
    payload = b""
    hdrs = sign_request(api_key, secret_key, "POST", path, body=payload)
    hdrs["Content-Type"] = "application/json"
    r = await client.post(path, content=payload, headers=hdrs)
    return r.status_code


async def _submit_action(
    client: AsyncClient,
    table_no: int,
    api_key: str,
    secret_key: str,
    hand_id: int,
    action: dict,
) -> dict:
    path = f"/v1/private/tables/{table_no}/action"
    payload = json.dumps({"hand_id": hand_id, "action": action}).encode()
    hdrs = sign_request(api_key, secret_key, "POST", path, body=payload)
    hdrs["Content-Type"] = "application/json"
    r = await client.post(path, content=payload, headers=hdrs)
    assert r.status_code == 200, f"action failed ({action}): {r.text}"
    return r.json()


async def _get_current_hand(session: AsyncSession, table_id: int) -> Hand | None:
    result = await session.execute(
        select(Hand).where(Hand.table_id == table_id, Hand.status == HandStatus.IN_PROGRESS)
    )
    return result.scalar_one_or_none()


async def _get_finished_hand(session: AsyncSession, hand_id: int) -> Hand | None:
    result = await session.execute(select(Hand).where(Hand.id == hand_id))
    return result.scalar_one_or_none()


async def _get_wallet(session: AsyncSession, acc_id: int) -> int:
    result = await session.execute(select(Account).where(Account.id == acc_id))
    acc = result.scalar_one_or_none()
    return acc.wallet_balance if acc else 0


async def _get_stack(session: AsyncSession, table_id: int, acc_id: int) -> int:
    result = await session.execute(
        select(TableSeat).where(
            TableSeat.table_id == table_id, TableSeat.account_id == acc_id
        )
    )
    seat = result.scalar_one_or_none()
    return seat.stack if seat else 0


async def _drive_hand_to_finish(
    client: AsyncClient,
    session: AsyncSession,
    table_no: int,
    table_id: int,
    creds: dict[int, tuple[str, str]],
    max_actions: int = 80,
) -> None:
    """Submit CALL/CHECK for each player's turn until the hand finishes."""
    for _ in range(max_actions):
        session.expire_all()  # force fresh DB read after each client action
        hand = await _get_current_hand(session, table_id)
        if hand is None:
            return  # hand finished

        if hand.action_seat_no is None:
            return

        hp_r = await session.execute(
            select(HandPlayer).where(
                HandPlayer.hand_id == hand.id,
                HandPlayer.seat_no == hand.action_seat_no,
            )
        )
        hp = hp_r.scalar_one_or_none()
        if hp is None:
            return

        api_key, secret_key = creds[hp.account_id]
        to_call = max(0, hand.current_bet - hp.round_contribution)
        action = {"type": "CHECK"} if to_call == 0 else {"type": "CALL"}

        await _submit_action(client, table_no, api_key, secret_key, hand.id, action)

    pytest.fail("Hand did not complete within max_actions")


async def _create_table(client: AsyncClient, table_no: int) -> None:
    r = await client.post("/admin/tables", json={"table_no": table_no}, headers=ADMIN)
    assert r.status_code in (200, 201), r.text


# ---------------------------------------------------------------------------
# Scenario 1: 2-player full flow
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_scenario1_two_player_full_flow(client: AsyncClient, db_session: AsyncSession):
    """계정 생성→키 발급→칩 지급→테이블→착석→핸드→showdown, 칩 보존 검증."""
    TABLE_NO = 1001

    acc1_id, ak1, sk1 = await _setup_player(client, "s1_p1")
    acc2_id, ak2, sk2 = await _setup_player(client, "s1_p2")
    creds = {acc1_id: (ak1, sk1), acc2_id: (ak2, sk2)}

    await _create_table(client, TABLE_NO)
    await _sit(client, TABLE_NO, ak1, sk1, seat_no=1)
    await _sit(client, TABLE_NO, ak2, sk2, seat_no=2)

    table_r = await db_session.execute(select(Table).where(Table.table_no == TABLE_NO))
    table = table_r.scalar_one()
    table_id = table.id

    # Record total chips before hand
    w1_before = await _get_wallet(db_session, acc1_id)
    w2_before = await _get_wallet(db_session, acc2_id)
    s1_before = await _get_stack(db_session, table_id, acc1_id)
    s2_before = await _get_stack(db_session, table_id, acc2_id)
    total_before = w1_before + w2_before + s1_before + s2_before

    with patch("app.services.hand_completion.asyncio.ensure_future"):
        hand = await start_hand(db_session, table_id)
        assert hand is not None, "hand should start with 2 seated players"
        assert hand.street == "preflop"
        hand_id = hand.id

        await _drive_hand_to_finish(client, db_session, TABLE_NO, table_id, creds)

    # Verify hand is now finished (fresh query)
    finished = await _get_finished_hand(db_session, hand_id)
    assert finished is not None
    assert finished.status == HandStatus.FINISHED

    # Chip conservation
    w1_after = await _get_wallet(db_session, acc1_id)
    w2_after = await _get_wallet(db_session, acc2_id)
    s1_after = await _get_stack(db_session, table_id, acc1_id)
    s2_after = await _get_stack(db_session, table_id, acc2_id)
    total_after = w1_after + w2_after + s1_after + s2_after
    assert total_before == total_after, (
        f"Chip conservation failed: before={total_before}, after={total_after}"
    )


# ---------------------------------------------------------------------------
# Scenario 2: 3-player multi all-in with side pots
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_scenario2_three_player_allin_side_pots(
    client: AsyncClient, db_session: AsyncSession
):
    """3명 다른 스택 → 전원 올인 → 칩 보존 검증."""
    TABLE_NO = 1002

    acc1_id, ak1, sk1 = await _setup_player(client, "s2_p1", chips=400)
    acc2_id, ak2, sk2 = await _setup_player(client, "s2_p2", chips=400)
    acc3_id, ak3, sk3 = await _setup_player(client, "s2_p3", chips=400)
    creds = {
        acc1_id: (ak1, sk1),
        acc2_id: (ak2, sk2),
        acc3_id: (ak3, sk3),
    }

    await _create_table(client, TABLE_NO)
    await _sit(client, TABLE_NO, ak1, sk1, seat_no=1)
    await _sit(client, TABLE_NO, ak2, sk2, seat_no=2)
    await _sit(client, TABLE_NO, ak3, sk3, seat_no=3)

    table_r = await db_session.execute(select(Table).where(Table.table_no == TABLE_NO))
    table = table_r.scalar_one()
    table_id = table.id

    # Directly set different stack sizes
    for acc_id, stack in [(acc1_id, 10), (acc2_id, 20), (acc3_id, 40)]:
        seat_r = await db_session.execute(
            select(TableSeat).where(
                TableSeat.table_id == table_id, TableSeat.account_id == acc_id
            )
        )
        seat = seat_r.scalar_one()
        seat.stack = stack
    await db_session.commit()

    # Record totals
    w1 = await _get_wallet(db_session, acc1_id)
    w2 = await _get_wallet(db_session, acc2_id)
    w3 = await _get_wallet(db_session, acc3_id)
    total_before = w1 + w2 + w3 + 10 + 20 + 40

    with patch("app.services.hand_completion.asyncio.ensure_future"):
        hand = await start_hand(db_session, table_id)
        assert hand is not None
        hand_id = hand.id

        for _ in range(30):
            db_session.expire_all()
            h = await _get_current_hand(db_session, table_id)
            if h is None:
                break
            if h.action_seat_no is None:
                break
            hp_r = await db_session.execute(
                select(HandPlayer).where(
                    HandPlayer.hand_id == h.id,
                    HandPlayer.seat_no == h.action_seat_no,
                )
            )
            hp = hp_r.scalar_one_or_none()
            if hp is None:
                break
            api_key, secret_key = creds[hp.account_id]
            await _submit_action(client, TABLE_NO, api_key, secret_key, h.id, {"type": "ALL_IN"})

    # Chip conservation
    w1_after = await _get_wallet(db_session, acc1_id)
    w2_after = await _get_wallet(db_session, acc2_id)
    w3_after = await _get_wallet(db_session, acc3_id)
    s1_after = await _get_stack(db_session, table_id, acc1_id)
    s2_after = await _get_stack(db_session, table_id, acc2_id)
    s3_after = await _get_stack(db_session, table_id, acc3_id)
    total_after = w1_after + w2_after + w3_after + s1_after + s2_after + s3_after
    assert total_before == total_after, (
        f"Chip conservation failed: before={total_before}, after={total_after}"
    )


# ---------------------------------------------------------------------------
# Scenario 3: Timeout auto-fold
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_scenario3_timeout_auto_fold(db_session: AsyncSession):
    """플레이어 액션 데드라인 경과 → AUTO_FOLD_TIMEOUT 발생, 게임 진행."""
    TABLE_NO = 1003

    acc1 = Account(nickname="s3_p1", status=AccountStatus.ACTIVE, wallet_balance=0)
    acc2 = Account(nickname="s3_p2", status=AccountStatus.ACTIVE, wallet_balance=0)
    db_session.add_all([acc1, acc2])
    await db_session.flush()

    table = Table(
        table_no=TABLE_NO, status=TableStatus.OPEN, max_seats=9,
        small_blind=1, big_blind=2, buy_in=40,
    )
    db_session.add(table)
    await db_session.flush()
    table_id = table.id

    seat1 = TableSeat(
        table_id=table_id, seat_no=1, account_id=acc1.id,
        seat_status=SeatStatus.SEATED, stack=38,
    )
    seat2 = TableSeat(
        table_id=table_id, seat_no=2, account_id=acc2.id,
        seat_status=SeatStatus.SEATED, stack=38,
    )
    for i in range(3, 10):
        db_session.add(TableSeat(
            table_id=table_id, seat_no=i, seat_status=SeatStatus.EMPTY, stack=0
        ))
    db_session.add_all([seat1, seat2])
    await db_session.flush()

    # Create hand with already-expired deadline
    expired = datetime.now(timezone.utc) - timedelta(seconds=30)
    hand = Hand(
        table_id=table_id, hand_no=1, status=HandStatus.IN_PROGRESS,
        button_seat_no=1, small_blind_seat_no=1, big_blind_seat_no=2,
        street="preflop", board_json="[]",
        current_bet=2, action_seat_no=1,
        action_deadline_at=expired,
    )
    db_session.add(hand)
    await db_session.flush()
    hand_id = hand.id
    acc1_id = acc1.id

    hp1 = HandPlayer(
        hand_id=hand_id, account_id=acc1.id, seat_no=1,
        hole_cards_json=json.dumps(["Ah", "Kh"]),
        starting_stack=40, ending_stack=38,
        folded=False, all_in=False, round_contribution=1, hand_contribution=1,
    )
    hp2 = HandPlayer(
        hand_id=hand_id, account_id=acc2.id, seat_no=2,
        hole_cards_json=json.dumps(["Qd", "Jd"]),
        starting_stack=40, ending_stack=38,
        folded=False, all_in=False, round_contribution=2, hand_contribution=2,
    )
    db_session.add_all([hp1, hp2])
    await db_session.commit()

    with patch("app.services.hand_completion.asyncio.ensure_future"):
        await _auto_fold(db_session, hand, acc1_id)

    # Verify: acc1 is folded (fresh query)
    hp1_r = await db_session.execute(
        select(HandPlayer).where(
            HandPlayer.hand_id == hand_id, HandPlayer.account_id == acc1_id
        )
    )
    hp1_result = hp1_r.scalar_one()
    assert hp1_result.folded is True

    # Verify: AUTO_FOLD_TIMEOUT action logged
    action_r = await db_session.execute(
        select(HandAction).where(
            HandAction.hand_id == hand_id,
            HandAction.action_type == "AUTO_FOLD_TIMEOUT",
        )
    )
    assert action_r.scalar_one_or_none() is not None, "AUTO_FOLD_TIMEOUT not logged"

    # Verify: hand is finished (only 2 players, one folded = immediate win)
    hand_r = await db_session.execute(select(Hand).where(Hand.id == hand_id))
    h = hand_r.scalar_one()
    assert h.status == HandStatus.FINISHED


# ---------------------------------------------------------------------------
# Scenario 4: Stand during hand → LEAVING_AFTER_HAND → chip return
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_scenario4_stand_during_hand(client: AsyncClient, db_session: AsyncSession):
    """핸드 중 이석 요청 → LEAVING_AFTER_HAND → 핸드 종료 후 이석 + 칩 반환."""
    TABLE_NO = 1004

    acc1_id, ak1, sk1 = await _setup_player(client, "s4_p1")
    acc2_id, ak2, sk2 = await _setup_player(client, "s4_p2")
    creds = {acc1_id: (ak1, sk1), acc2_id: (ak2, sk2)}

    await _create_table(client, TABLE_NO)
    await _sit(client, TABLE_NO, ak1, sk1, seat_no=1)
    await _sit(client, TABLE_NO, ak2, sk2, seat_no=2)

    table_r = await db_session.execute(select(Table).where(Table.table_no == TABLE_NO))
    table = table_r.scalar_one()
    table_id = table.id

    with patch("app.services.hand_completion.asyncio.ensure_future"):
        hand = await start_hand(db_session, table_id)
        assert hand is not None
        hand_id = hand.id

        # Player 2 requests to stand during the hand
        status_code = await _stand(client, TABLE_NO, ak2, sk2)
        assert status_code == 200

        # Verify: seat 2 is now LEAVING_AFTER_HAND
        db_session.expire_all()
        seat2_r = await db_session.execute(
            select(TableSeat).where(
                TableSeat.table_id == table_id, TableSeat.account_id == acc2_id
            )
        )
        seat2 = seat2_r.scalar_one()
        assert seat2.seat_status == SeatStatus.LEAVING_AFTER_HAND

        # Record wallet before hand completion
        w2_before = await _get_wallet(db_session, acc2_id)

        # Drive hand to completion
        await _drive_hand_to_finish(client, db_session, TABLE_NO, table_id, creds)

    # After hand: seat 2 should be EMPTY
    seat2_r = await db_session.execute(
        select(TableSeat).where(
            TableSeat.table_id == table_id, TableSeat.seat_no == 2
        )
    )
    seat2 = seat2_r.scalar_one()
    assert seat2.seat_status == SeatStatus.EMPTY, "Seat should be empty after hand"
    assert seat2.account_id is None

    # Wallet should have increased (stack returned after hand)
    w2_after = await _get_wallet(db_session, acc2_id)
    assert w2_after >= w2_before, "Wallet should increase after stack cashout"


# ---------------------------------------------------------------------------
# Scenario 5: Multi-table concurrent play
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_scenario5_multi_table_concurrent(
    client: AsyncClient, db_session: AsyncSession
):
    """테이블 2개에서 동시에 핸드 진행 → 각 테이블 독립 동작 확인."""
    TABLE_A = 1005
    TABLE_B = 1006

    acc_a1_id, ak_a1, sk_a1 = await _setup_player(client, "s5_a1")
    acc_a2_id, ak_a2, sk_a2 = await _setup_player(client, "s5_a2")
    creds_a = {acc_a1_id: (ak_a1, sk_a1), acc_a2_id: (ak_a2, sk_a2)}

    acc_b1_id, ak_b1, sk_b1 = await _setup_player(client, "s5_b1")
    acc_b2_id, ak_b2, sk_b2 = await _setup_player(client, "s5_b2")
    creds_b = {acc_b1_id: (ak_b1, sk_b1), acc_b2_id: (ak_b2, sk_b2)}

    await _create_table(client, TABLE_A)
    await _create_table(client, TABLE_B)

    await _sit(client, TABLE_A, ak_a1, sk_a1, seat_no=1)
    await _sit(client, TABLE_A, ak_a2, sk_a2, seat_no=2)
    await _sit(client, TABLE_B, ak_b1, sk_b1, seat_no=1)
    await _sit(client, TABLE_B, ak_b2, sk_b2, seat_no=2)

    table_a_r = await db_session.execute(select(Table).where(Table.table_no == TABLE_A))
    table_a = table_a_r.scalar_one()
    table_b_r = await db_session.execute(select(Table).where(Table.table_no == TABLE_B))
    table_b = table_b_r.scalar_one()
    table_a_id = table_a.id
    table_b_id = table_b.id

    # Record chip totals
    total_a_before = (
        (await _get_wallet(db_session, acc_a1_id))
        + (await _get_wallet(db_session, acc_a2_id))
        + (await _get_stack(db_session, table_a_id, acc_a1_id))
        + (await _get_stack(db_session, table_a_id, acc_a2_id))
    )
    total_b_before = (
        (await _get_wallet(db_session, acc_b1_id))
        + (await _get_wallet(db_session, acc_b2_id))
        + (await _get_stack(db_session, table_b_id, acc_b1_id))
        + (await _get_stack(db_session, table_b_id, acc_b2_id))
    )

    with patch("app.services.hand_completion.asyncio.ensure_future"):
        hand_a = await start_hand(db_session, table_a_id)
        hand_b = await start_hand(db_session, table_b_id)

        assert hand_a is not None, "Table A hand should start"
        assert hand_b is not None, "Table B hand should start"
        assert hand_a.id != hand_b.id, "Hands should be different"
        hand_a_id = hand_a.id
        hand_b_id = hand_b.id

        await _drive_hand_to_finish(client, db_session, TABLE_A, table_a_id, creds_a)
        await _drive_hand_to_finish(client, db_session, TABLE_B, table_b_id, creds_b)

    # Both hands should be finished
    fa_r = await db_session.execute(select(Hand).where(Hand.id == hand_a_id))
    fb_r = await db_session.execute(select(Hand).where(Hand.id == hand_b_id))
    assert fa_r.scalar_one().status == HandStatus.FINISHED
    assert fb_r.scalar_one().status == HandStatus.FINISHED

    # Chip conservation per table
    total_a_after = (
        (await _get_wallet(db_session, acc_a1_id))
        + (await _get_wallet(db_session, acc_a2_id))
        + (await _get_stack(db_session, table_a_id, acc_a1_id))
        + (await _get_stack(db_session, table_a_id, acc_a2_id))
    )
    total_b_after = (
        (await _get_wallet(db_session, acc_b1_id))
        + (await _get_wallet(db_session, acc_b2_id))
        + (await _get_stack(db_session, table_b_id, acc_b1_id))
        + (await _get_stack(db_session, table_b_id, acc_b2_id))
    )
    assert total_a_before == total_a_after, "Table A chip conservation failed"
    assert total_b_before == total_b_after, "Table B chip conservation failed"


# ---------------------------------------------------------------------------
# Regression: action log seq order
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_regression_action_log_seq_order(client: AsyncClient, db_session: AsyncSession):
    """액션 로그 seq가 항상 오름차순인지 검증."""
    TABLE_NO = 1007
    acc1_id, ak1, sk1 = await _setup_player(client, "r1_p1")
    acc2_id, ak2, sk2 = await _setup_player(client, "r1_p2")
    creds = {acc1_id: (ak1, sk1), acc2_id: (ak2, sk2)}

    await _create_table(client, TABLE_NO)
    await _sit(client, TABLE_NO, ak1, sk1, seat_no=1)
    await _sit(client, TABLE_NO, ak2, sk2, seat_no=2)

    table_r = await db_session.execute(select(Table).where(Table.table_no == TABLE_NO))
    table = table_r.scalar_one()
    table_id = table.id

    with patch("app.services.hand_completion.asyncio.ensure_future"):
        hand = await start_hand(db_session, table_id)
        assert hand is not None
        hand_id = hand.id
        await _drive_hand_to_finish(client, db_session, TABLE_NO, table_id, creds)

    # Verify action log seq is strictly ascending
    actions_r = await db_session.execute(
        select(HandAction)
        .where(HandAction.hand_id == hand_id)
        .order_by(HandAction.seq)
    )
    actions = actions_r.scalars().all()
    assert len(actions) > 0, "Should have logged actions"
    seqs = [a.seq for a in actions]
    for i in range(1, len(seqs)):
        assert seqs[i] > seqs[i - 1], f"seq not ascending at index {i}: {seqs}"


# ---------------------------------------------------------------------------
# Regression: public API does not expose hole cards
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_regression_public_api_no_hole_cards(
    client: AsyncClient, db_session: AsyncSession
):
    """공개 API에서 홀카드가 노출되지 않는지 검증."""
    TABLE_NO = 1008
    acc1_id, ak1, sk1 = await _setup_player(client, "r2_p1")
    acc2_id, ak2, sk2 = await _setup_player(client, "r2_p2")

    await _create_table(client, TABLE_NO)
    await _sit(client, TABLE_NO, ak1, sk1, seat_no=1)
    await _sit(client, TABLE_NO, ak2, sk2, seat_no=2)

    table_r = await db_session.execute(select(Table).where(Table.table_no == TABLE_NO))
    table = table_r.scalar_one()

    with patch("app.services.hand_completion.asyncio.ensure_future"):
        hand = await start_hand(db_session, table.id)
        assert hand is not None

    # Check public state API — no hole cards for any player
    r = await client.get(f"/v1/public/tables/{TABLE_NO}")
    assert r.status_code == 200
    data = r.json()

    # Seats should not contain hole_cards
    seats = data.get("seats", [])
    for seat in seats:
        assert "hole_cards" not in seat, f"hole_cards exposed in public API: {seat}"
