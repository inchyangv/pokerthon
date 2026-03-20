import pytest
from httpx import AsyncClient

from app.config import settings

ADMIN_HEADERS = {"Authorization": f"Bearer {settings.ADMIN_PASSWORD}"}


@pytest.mark.asyncio
async def test_create_table(client: AsyncClient):
    r = await client.post("/admin/tables", json={"table_no": 1}, headers=ADMIN_HEADERS)
    assert r.status_code == 201
    data = r.json()
    assert data["table_no"] == 1
    assert data["status"] == "OPEN"
    assert len(data["seats"]) == 9


@pytest.mark.asyncio
async def test_create_table_duplicate(client: AsyncClient):
    await client.post("/admin/tables", json={"table_no": 2}, headers=ADMIN_HEADERS)
    r = await client.post("/admin/tables", json={"table_no": 2}, headers=ADMIN_HEADERS)
    assert r.status_code == 409


@pytest.mark.asyncio
async def test_pause_resume_close(client: AsyncClient):
    await client.post("/admin/tables", json={"table_no": 3}, headers=ADMIN_HEADERS)

    # pause
    r = await client.post("/admin/tables/3/pause", headers=ADMIN_HEADERS)
    assert r.status_code == 200
    assert r.json()["status"] == "PAUSED"

    # pause again → 409
    r = await client.post("/admin/tables/3/pause", headers=ADMIN_HEADERS)
    assert r.status_code == 409

    # resume
    r = await client.post("/admin/tables/3/resume", headers=ADMIN_HEADERS)
    assert r.status_code == 200
    assert r.json()["status"] == "OPEN"

    # resume when OPEN → 409
    r = await client.post("/admin/tables/3/resume", headers=ADMIN_HEADERS)
    assert r.status_code == 409

    # close
    r = await client.post("/admin/tables/3/close", headers=ADMIN_HEADERS)
    assert r.status_code == 200
    assert r.json()["status"] == "CLOSED"

    # close again → 409
    r = await client.post("/admin/tables/3/close", headers=ADMIN_HEADERS)
    assert r.status_code == 409


@pytest.mark.asyncio
async def test_list_tables(client: AsyncClient):
    await client.post("/admin/tables", json={"table_no": 4}, headers=ADMIN_HEADERS)
    await client.post("/admin/tables", json={"table_no": 5}, headers=ADMIN_HEADERS)
    r = await client.get("/admin/tables", headers=ADMIN_HEADERS)
    assert r.status_code == 200
    assert len(r.json()) >= 2


@pytest.mark.asyncio
async def test_get_table(client: AsyncClient):
    await client.post("/admin/tables", json={"table_no": 6}, headers=ADMIN_HEADERS)
    r = await client.get("/admin/tables/6", headers=ADMIN_HEADERS)
    assert r.status_code == 200
    assert r.json()["table_no"] == 6
    assert len(r.json()["seats"]) == 9


@pytest.mark.asyncio
async def test_table_not_found(client: AsyncClient):
    r = await client.get("/admin/tables/99", headers=ADMIN_HEADERS)
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_close_cashout(client: AsyncClient):
    # Create account, grant chips, create table, manually set a seated player
    acc_r = await client.post("/admin/accounts", json={"nickname": "closer_bot"}, headers=ADMIN_HEADERS)
    acc_id = acc_r.json()["id"]
    await client.post(f"/admin/accounts/{acc_id}/grant", json={"amount": 200}, headers=ADMIN_HEADERS)

    await client.post("/admin/tables", json={"table_no": 7}, headers=ADMIN_HEADERS)

    # Manually seat via DB (seat_service not yet implemented, test close logic via chip service)
    # Skip DB-level test for now; confirm close runs without error on empty table
    r = await client.post("/admin/tables/7/close", headers=ADMIN_HEADERS)
    assert r.status_code == 200
    assert r.json()["status"] == "CLOSED"
