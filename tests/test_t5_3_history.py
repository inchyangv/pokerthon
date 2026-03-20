"""Tests for hand history and action log APIs (T5.3)."""
from __future__ import annotations

import json
from unittest.mock import patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.signature import sign_request
from app.models.account import Account, AccountStatus
from app.models.hand import Hand, HandPlayer, HandStatus
from app.models.table import SeatStatus, Table, TableSeat, TableStatus
from app.services.hand_completion import complete_hand
from app.services.showdown_service import resolve_showdown

ADMIN_HEADERS = {"Authorization": f"Bearer {settings.ADMIN_PASSWORD}"}
BOARD = ["2h", "7c", "Jd", "Ks", "3s"]


async def _create_player(client: AsyncClient, nickname: str) -> tuple[int, str, str]:
    r = await client.post("/admin/accounts", json={"nickname": nickname}, headers=ADMIN_HEADERS)
    acc_id = r.json()["id"]
    await client.post(f"/admin/accounts/{acc_id}/grant", json={"amount": 200}, headers=ADMIN_HEADERS)
    r2 = await client.post(f"/admin/accounts/{acc_id}/credentials", headers=ADMIN_HEADERS)
    return acc_id, r2.json()["api_key"], r2.json()["secret_key"]


async def _build_finished_hand(
    session: AsyncSession,
    table_no: int,
    players_data: list,  # [(seat_no, hole_cards, contribution, folded, stack)]
    button_seat_no: int = 1,
) -> tuple[Table, Hand]:
    """Create a table + hand already at showdown and complete it."""
    table = Table(
        table_no=table_no, status=TableStatus.OPEN, max_seats=9,
        small_blind=1, big_blind=2, buy_in=40,
    )
    session.add(table)
    await session.flush()

    accs = []
    for i, (seat_no, _, contrib, folded, stack) in enumerate(players_data):
        acc = Account(nickname=f"hist{table_no}_{i}", status=AccountStatus.ACTIVE, wallet_balance=0)
        session.add(acc)
        await session.flush()
        accs.append(acc)
        seat = TableSeat(
            table_id=table.id, seat_no=seat_no, account_id=acc.id,
            seat_status=SeatStatus.SEATED, stack=stack,
        )
        session.add(seat)

    for i in range(1, 10):
        if i not in {s for s, *_ in players_data}:
            session.add(TableSeat(table_id=table.id, seat_no=i, seat_status=SeatStatus.EMPTY, stack=0))

    await session.flush()

    hand = Hand(
        table_id=table.id, hand_no=1, status=HandStatus.IN_PROGRESS,
        button_seat_no=button_seat_no, small_blind_seat_no=None, big_blind_seat_no=None,
        street="showdown", board_json=json.dumps(BOARD),
        current_bet=0, action_seat_no=None,
    )
    session.add(hand)
    await session.flush()

    for i, (seat_no, hole_cards, contrib, folded, stack) in enumerate(players_data):
        hp = HandPlayer(
            hand_id=hand.id, account_id=accs[i].id, seat_no=seat_no,
            hole_cards_json=json.dumps(hole_cards),
            starting_stack=stack + contrib,
            ending_stack=stack,
            folded=folded, all_in=(stack == 0),
            round_contribution=0, hand_contribution=contrib,
        )
        session.add(hp)

    await session.commit()

    # Resolve and complete
    with patch("app.services.hand_completion.asyncio.ensure_future"):
        result = await resolve_showdown(session, hand)
        await complete_hand(session, hand, result)

    return table, hand


@pytest.mark.asyncio
async def test_hand_list(client: AsyncClient, db_session: AsyncSession):
    """완료된 핸드 목록 조회."""
    table, hand = await _build_finished_hand(
        db_session, 701,
        [(1, ["Ah", "Kh"], 20, False, 20), (2, ["9d", "8d"], 20, False, 20)],
    )

    r = await client.get(f"/v1/public/tables/701/hands")
    assert r.status_code == 200
    data = r.json()
    assert len(data["items"]) >= 1
    item = data["items"][0]
    assert item["hand_id"] == hand.id
    assert "board" in item
    assert "winners" in item


@pytest.mark.asyncio
async def test_hand_detail_showdown(client: AsyncClient, db_session: AsyncSession):
    """쇼다운 핸드 → 홀카드 공개 확인."""
    table, hand = await _build_finished_hand(
        db_session, 702,
        [(1, ["Ah", "Kh"], 20, False, 20), (2, ["9d", "8d"], 20, False, 20)],
    )

    r = await client.get(f"/v1/public/tables/702/hands/{hand.id}")
    assert r.status_code == 200
    data = r.json()
    for p in data["players"]:
        if not p["folded"]:
            assert p["hole_cards"] is not None, "Showdown players should have hole cards revealed"


@pytest.mark.asyncio
async def test_hand_detail_fold_win_no_reveal(client: AsyncClient, db_session: AsyncSession):
    """폴드 승리 핸드 → 폴드 플레이어 홀카드 비공개."""
    table, hand = await _build_finished_hand(
        db_session, 703,
        [
            (1, ["Ah", "Kh"], 20, False, 20),   # winner
            (2, ["Qd", "Jd"], 20, True, 20),    # folded
        ],
    )

    r = await client.get(f"/v1/public/tables/703/hands/{hand.id}")
    assert r.status_code == 200
    data = r.json()
    folded_players = [p for p in data["players"] if p["folded"]]
    for p in folded_players:
        assert p["hole_cards"] is None, "Folded players in fold-win should not reveal hole cards"


@pytest.mark.asyncio
async def test_hand_actions(client: AsyncClient, db_session: AsyncSession):
    """핸드별 액션 로그 조회."""
    table, hand = await _build_finished_hand(
        db_session, 704,
        [(1, ["Ah", "Kh"], 20, False, 20), (2, ["9d", "8d"], 20, False, 20)],
    )

    r = await client.get(f"/v1/public/tables/704/hands/{hand.id}/actions")
    assert r.status_code == 200
    actions = r.json()
    assert isinstance(actions, list)
    assert len(actions) > 0
    # All should have seq
    seqs = [a["seq"] for a in actions]
    assert seqs == sorted(seqs)


@pytest.mark.asyncio
async def test_table_actions_pagination(client: AsyncClient, db_session: AsyncSession):
    """테이블 전체 액션 로그 페이지네이션."""
    table, hand = await _build_finished_hand(
        db_session, 705,
        [(1, ["Ah", "Kh"], 20, False, 20), (2, ["9d", "8d"], 20, False, 20)],
    )

    r = await client.get("/v1/public/tables/705/actions?limit=5")
    assert r.status_code == 200
    data = r.json()
    assert "items" in data
    assert "has_more" in data


@pytest.mark.asyncio
async def test_hand_not_found(client: AsyncClient, db_session: AsyncSession):
    """존재하지 않는 hand_id → 404."""
    await client.post("/admin/tables", json={"table_no": 706}, headers=ADMIN_HEADERS)
    r = await client.get("/v1/public/tables/706/hands/99999")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_me_hands(client: AsyncClient, db_session: AsyncSession):
    """/me/hands → 자기 카드 포함 확인."""
    acc_id, ak, sk = await _create_player(client, "hist_me_bot")

    # Build a finished hand with this player
    acc_result = await db_session.execute(select(Account).where(Account.id == acc_id))
    acc = acc_result.scalar_one()

    table = Table(
        table_no=707, status=TableStatus.OPEN, max_seats=9,
        small_blind=1, big_blind=2, buy_in=40,
    )
    db_session.add(table)
    await db_session.flush()

    other_acc = Account(nickname="hist_other_707", status=AccountStatus.ACTIVE, wallet_balance=0)
    db_session.add(other_acc)
    await db_session.flush()

    seat1 = TableSeat(table_id=table.id, seat_no=1, account_id=acc.id, seat_status=SeatStatus.SEATED, stack=20)
    seat2 = TableSeat(table_id=table.id, seat_no=2, account_id=other_acc.id, seat_status=SeatStatus.SEATED, stack=20)
    db_session.add_all([seat1, seat2])
    for i in range(3, 10):
        db_session.add(TableSeat(table_id=table.id, seat_no=i, seat_status=SeatStatus.EMPTY, stack=0))

    await db_session.flush()

    hand = Hand(
        table_id=table.id, hand_no=1, status=HandStatus.IN_PROGRESS,
        button_seat_no=1, small_blind_seat_no=None, big_blind_seat_no=None,
        street="showdown", board_json=json.dumps(BOARD),
        current_bet=0, action_seat_no=None,
    )
    db_session.add(hand)
    await db_session.flush()

    hp1 = HandPlayer(
        hand_id=hand.id, account_id=acc.id, seat_no=1,
        hole_cards_json=json.dumps(["Ah", "Kh"]),
        starting_stack=40, ending_stack=20,
        folded=False, all_in=False, round_contribution=0, hand_contribution=20,
    )
    hp2 = HandPlayer(
        hand_id=hand.id, account_id=other_acc.id, seat_no=2,
        hole_cards_json=json.dumps(["9d", "8d"]),
        starting_stack=40, ending_stack=20,
        folded=False, all_in=False, round_contribution=0, hand_contribution=20,
    )
    db_session.add_all([hp1, hp2])
    await db_session.commit()

    with patch("app.services.hand_completion.asyncio.ensure_future"):
        result = await resolve_showdown(db_session, hand)
        await complete_hand(db_session, hand, result)

    h = sign_request(ak, sk, "GET", "/v1/private/me/hands")
    r = await client.get("/v1/private/me/hands", headers=h)
    assert r.status_code == 200
    data = r.json()
    assert len(data["items"]) >= 1
    item = data["items"][0]
    assert "my_hole_cards" in item
    assert len(item["my_hole_cards"]) == 2
