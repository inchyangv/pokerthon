"""Tests for private game state API (T5.1)."""
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


async def _start_hand_for_table(session: AsyncSession, table_no: int) -> None:
    result = await session.execute(select(Table).where(Table.table_no == table_no))
    table = result.scalar_one()
    await start_hand(session, table.id)


@pytest.mark.asyncio
async def test_state_no_hand(client: AsyncClient, db_session: AsyncSession):
    """핸드 없을 때 → null 필드 확인."""
    _, api_key, secret_key = await _create_player(client, "st_bot1")
    await client.post("/admin/tables", json={"table_no": 501}, headers=ADMIN_HEADERS)
    h = sign_request(api_key, secret_key, "POST", "/v1/private/tables/501/sit")
    await client.post("/v1/private/tables/501/sit", headers=h)

    h2 = sign_request(api_key, secret_key, "GET", "/v1/private/tables/501/state")
    r = await client.get("/v1/private/tables/501/state", headers=h2)
    assert r.status_code == 200
    data = r.json()
    assert data["hand_id"] is None
    assert data["street"] is None
    assert data["board"] == []
    assert data["legal_actions"] == []
    assert data["hole_cards"] == []


@pytest.mark.asyncio
async def test_state_with_hand_own_hole_cards(client: AsyncClient, db_session: AsyncSession):
    """착석 + 핸드 시작 → 자기 홀카드 포함 확인."""
    _, ak1, sk1 = await _create_player(client, "st_bot2a")
    _, ak2, sk2 = await _create_player(client, "st_bot2b")
    await client.post("/admin/tables", json={"table_no": 502}, headers=ADMIN_HEADERS)

    h1 = sign_request(ak1, sk1, "POST", "/v1/private/tables/502/sit")
    h2 = sign_request(ak2, sk2, "POST", "/v1/private/tables/502/sit")
    await client.post("/v1/private/tables/502/sit", headers=h1)
    await client.post("/v1/private/tables/502/sit", headers=h2)

    await _start_hand_for_table(db_session, 502)

    # Request state as player 1
    h3 = sign_request(ak1, sk1, "GET", "/v1/private/tables/502/state")
    r = await client.get("/v1/private/tables/502/state", headers=h3)
    assert r.status_code == 200
    data = r.json()
    assert data["hand_id"] is not None
    assert data["street"] == "preflop"
    assert len(data["hole_cards"]) == 2, "Own hole cards should be returned"
    assert len(data["board"]) == 0


@pytest.mark.asyncio
async def test_state_other_player_no_hole_cards(client: AsyncClient, db_session: AsyncSession):
    """다른 플레이어 관점 → 타인 홀카드 미포함 확인."""
    _, ak1, sk1 = await _create_player(client, "st_bot3a")
    _, ak2, sk2 = await _create_player(client, "st_bot3b")
    _, ak3, sk3 = await _create_player(client, "st_bot3c")  # spectator
    await client.post("/admin/tables", json={"table_no": 503}, headers=ADMIN_HEADERS)

    h1 = sign_request(ak1, sk1, "POST", "/v1/private/tables/503/sit")
    h2 = sign_request(ak2, sk2, "POST", "/v1/private/tables/503/sit")
    await client.post("/v1/private/tables/503/sit", headers=h1)
    await client.post("/v1/private/tables/503/sit", headers=h2)

    await _start_hand_for_table(db_session, 503)

    # Spectator (not seated) requests state
    h3 = sign_request(ak3, sk3, "GET", "/v1/private/tables/503/state")
    r = await client.get("/v1/private/tables/503/state", headers=h3)
    assert r.status_code == 200
    data = r.json()
    assert data["hole_cards"] == [], "Non-seated player should get empty hole_cards"
    for seat in data["seats"]:
        assert "hole_cards" not in seat


@pytest.mark.asyncio
async def test_state_legal_actions_included(client: AsyncClient, db_session: AsyncSession):
    """legal_actions + pot_view 포함 확인."""
    _, ak1, sk1 = await _create_player(client, "st_bot4a")
    _, ak2, sk2 = await _create_player(client, "st_bot4b")
    await client.post("/admin/tables", json={"table_no": 504}, headers=ADMIN_HEADERS)

    h1 = sign_request(ak1, sk1, "POST", "/v1/private/tables/504/sit")
    h2 = sign_request(ak2, sk2, "POST", "/v1/private/tables/504/sit")
    await client.post("/v1/private/tables/504/sit", headers=h1)
    await client.post("/v1/private/tables/504/sit", headers=h2)

    await _start_hand_for_table(db_session, 504)

    # Determine which player acts first by querying state
    h_1 = sign_request(ak1, sk1, "GET", "/v1/private/tables/504/state")
    r1 = await client.get("/v1/private/tables/504/state", headers=h_1)
    data1 = r1.json()

    h_2 = sign_request(ak2, sk2, "GET", "/v1/private/tables/504/state")
    r2 = await client.get("/v1/private/tables/504/state", headers=h_2)
    data2 = r2.json()

    # At least one player should have legal_actions
    has_actions = len(data1["legal_actions"]) > 0 or len(data2["legal_actions"]) > 0
    assert has_actions, "At least the acting player should have legal actions"

    # pot_view should be present
    assert "pot_view" in data1
    assert data1["pot_view"]["main_pot"] >= 0


@pytest.mark.asyncio
async def test_state_table_not_found(client: AsyncClient, db_session: AsyncSession):
    """존재하지 않는 table_no → 404."""
    _, ak, sk = await _create_player(client, "st_bot5")
    h = sign_request(ak, sk, "GET", "/v1/private/tables/9999/state")
    r = await client.get("/v1/private/tables/9999/state", headers=h)
    assert r.status_code == 404
