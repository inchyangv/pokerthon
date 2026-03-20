"""Tests for public game state API (T5.2)."""
from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.signature import sign_request
from app.models.table import Table
from app.services.hand_service import start_hand

ADMIN_HEADERS = {"Authorization": f"Bearer {settings.ADMIN_PASSWORD}"}


async def _create_player(client: AsyncClient, nickname: str) -> tuple[int, str, str]:
    r = await client.post("/admin/accounts", json={"nickname": nickname}, headers=ADMIN_HEADERS)
    acc_id = r.json()["id"]
    await client.post(f"/admin/accounts/{acc_id}/grant", json={"amount": 200}, headers=ADMIN_HEADERS)
    r2 = await client.post(f"/admin/accounts/{acc_id}/credentials", headers=ADMIN_HEADERS)
    return acc_id, r2.json()["api_key"], r2.json()["secret_key"]


@pytest.mark.asyncio
async def test_public_state_no_hand(client: AsyncClient):
    """핸드 없을 때 조회 → 좌석 정보만 확인."""
    _, ak, sk = await _create_player(client, "pb_bot1")
    await client.post("/admin/tables", json={"table_no": 601}, headers=ADMIN_HEADERS)
    h = sign_request(ak, sk, "POST", "/v1/private/tables/601/sit")
    await client.post("/v1/private/tables/601/sit", headers=h)

    r = await client.get("/v1/public/tables/601/state")
    assert r.status_code == 200
    data = r.json()
    assert data["hand_id"] is None
    assert data["street"] is None
    assert data["board"] == []
    seated = [s for s in data["seats"] if s["seat_status"] != "EMPTY"]
    assert len(seated) == 1


@pytest.mark.asyncio
async def test_public_state_no_hole_cards(client: AsyncClient, db_session: AsyncSession):
    """핸드 진행 중 조회 → 홀카드 없음 확인."""
    _, ak1, sk1 = await _create_player(client, "pb_bot2a")
    _, ak2, sk2 = await _create_player(client, "pb_bot2b")
    await client.post("/admin/tables", json={"table_no": 602}, headers=ADMIN_HEADERS)

    h1 = sign_request(ak1, sk1, "POST", "/v1/private/tables/602/sit")
    h2 = sign_request(ak2, sk2, "POST", "/v1/private/tables/602/sit")
    await client.post("/v1/private/tables/602/sit", headers=h1)
    await client.post("/v1/private/tables/602/sit", headers=h2)

    table_r = await db_session.execute(select(Table).where(Table.table_no == 602))
    table = table_r.scalar_one()
    await start_hand(db_session, table.id)

    r = await client.get("/v1/public/tables/602/state")
    assert r.status_code == 200
    data = r.json()
    assert data["hand_id"] is not None
    assert data["street"] == "preflop"
    # No hole_cards field in public state seats
    for seat in data["seats"]:
        assert "hole_cards" not in seat
    # board should be empty (preflop)
    assert data["board"] == []


@pytest.mark.asyncio
async def test_public_state_pot_view(client: AsyncClient, db_session: AsyncSession):
    """pot_view 포함 확인."""
    _, ak1, sk1 = await _create_player(client, "pb_bot3a")
    _, ak2, sk2 = await _create_player(client, "pb_bot3b")
    await client.post("/admin/tables", json={"table_no": 603}, headers=ADMIN_HEADERS)

    h1 = sign_request(ak1, sk1, "POST", "/v1/private/tables/603/sit")
    h2 = sign_request(ak2, sk2, "POST", "/v1/private/tables/603/sit")
    await client.post("/v1/private/tables/603/sit", headers=h1)
    await client.post("/v1/private/tables/603/sit", headers=h2)

    table_r = await db_session.execute(select(Table).where(Table.table_no == 603))
    table = table_r.scalar_one()
    await start_hand(db_session, table.id)

    r = await client.get("/v1/public/tables/603/state")
    assert r.status_code == 200
    data = r.json()
    assert "pot_view" in data
    pv = data["pot_view"]
    assert "main_pot" in pv
    assert "side_pots" in pv
    # After blinds: SB=1, BB=2. BB's extra 1 chip is uncalled → main_pot=2
    assert pv["main_pot"] == 2


@pytest.mark.asyncio
async def test_public_state_not_found(client: AsyncClient):
    """존재하지 않는 table_no → 404."""
    r = await client.get("/v1/public/tables/9999/state")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_public_state_no_auth_required(client: AsyncClient):
    """인증 없이 접근 가능."""
    await client.post("/admin/tables", json={"table_no": 604}, headers=ADMIN_HEADERS)
    r = await client.get("/v1/public/tables/604/state")
    assert r.status_code == 200
