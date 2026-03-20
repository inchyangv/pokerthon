"""Tests for admin web UI — table and game management (T7.2)."""
from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.config import settings

ADMIN_PASSWORD = settings.ADMIN_PASSWORD


async def _login(client: AsyncClient) -> None:
    await client.post("/admin/login", data={"password": ADMIN_PASSWORD})


@pytest.mark.asyncio
async def test_tables_list_page(client: AsyncClient):
    """테이블 목록 페이지."""
    await _login(client)
    r = await client.get("/admin/tables")
    assert r.status_code == 200
    assert "테이블" in r.text


@pytest.mark.asyncio
async def test_create_table_via_ui(client: AsyncClient):
    """테이블 생성 버튼."""
    await _login(client)
    r = await client.post("/admin/tables/create", data={"table_no": "201"}, follow_redirects=True)
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_table_detail_page(client: AsyncClient):
    """테이블 상세 페이지."""
    await _login(client)
    await client.post("/admin/tables/create", data={"table_no": "202"})
    r = await client.get("/admin/tables/202")
    assert r.status_code == 200
    assert "202" in r.text


@pytest.mark.asyncio
async def test_table_pause_resume(client: AsyncClient):
    """일시정지 / 재개 버튼."""
    await _login(client)
    await client.post("/admin/tables/create", data={"table_no": "203"})

    r_pause = await client.post("/admin/tables/203/pause", follow_redirects=True)
    assert r_pause.status_code == 200

    r_resume = await client.post("/admin/tables/203/resume", follow_redirects=True)
    assert r_resume.status_code == 200


@pytest.mark.asyncio
async def test_table_close(client: AsyncClient):
    """테이블 종료 버튼."""
    await _login(client)
    await client.post("/admin/tables/create", data={"table_no": "204"})
    r = await client.post("/admin/tables/204/close", follow_redirects=True)
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_hand_detail_page(client: AsyncClient, db_session):
    """핸드 상세 페이지 (관리자 전용 홀카드 포함)."""
    from unittest.mock import patch
    from sqlalchemy import select
    from app.models.account import Account, AccountStatus
    from app.models.hand import Hand, HandPlayer, HandStatus
    from app.models.table import SeatStatus, Table, TableSeat, TableStatus
    from app.services.showdown_service import resolve_showdown
    from app.services.hand_completion import complete_hand
    import json

    await _login(client)

    # Build a completed hand directly via db_session
    acc1 = Account(nickname="t72_p1", status=AccountStatus.ACTIVE, wallet_balance=0)
    acc2 = Account(nickname="t72_p2", status=AccountStatus.ACTIVE, wallet_balance=0)
    db_session.add_all([acc1, acc2])
    await db_session.flush()

    table = Table(table_no=205, status=TableStatus.OPEN, max_seats=9, small_blind=1, big_blind=2, buy_in=40)
    db_session.add(table)
    await db_session.flush()

    for i, (acc_id, sn) in enumerate([(acc1.id, 1), (acc2.id, 2)]):
        db_session.add(TableSeat(table_id=table.id, seat_no=sn, account_id=acc_id, seat_status=SeatStatus.SEATED, stack=20))
    for i in range(3, 10):
        db_session.add(TableSeat(table_id=table.id, seat_no=i, seat_status=SeatStatus.EMPTY, stack=0))
    await db_session.flush()

    hand = Hand(
        table_id=table.id, hand_no=1, status=HandStatus.IN_PROGRESS,
        button_seat_no=1, small_blind_seat_no=None, big_blind_seat_no=None,
        street="showdown", board_json=json.dumps(["2h", "7c", "Jd", "Ks", "3s"]),
        current_bet=0, action_seat_no=None,
    )
    db_session.add(hand)
    await db_session.flush()

    hp1 = HandPlayer(hand_id=hand.id, account_id=acc1.id, seat_no=1,
                     hole_cards_json=json.dumps(["Ah", "Kh"]), starting_stack=40, ending_stack=20,
                     folded=False, all_in=False, round_contribution=0, hand_contribution=20)
    hp2 = HandPlayer(hand_id=hand.id, account_id=acc2.id, seat_no=2,
                     hole_cards_json=json.dumps(["9d", "8d"]), starting_stack=40, ending_stack=20,
                     folded=False, all_in=False, round_contribution=0, hand_contribution=20)
    db_session.add_all([hp1, hp2])
    await db_session.commit()

    with patch("app.services.hand_completion.asyncio.ensure_future"):
        result = await resolve_showdown(db_session, hand)
        await complete_hand(db_session, hand, result)

    r = await client.get(f"/admin/tables/205/hands/{hand.id}")
    assert r.status_code == 200
    assert "홀카드" in r.text or "hand_no" in r.text or "#1" in r.text
