import pytest
from httpx import AsyncClient

from app.config import settings

ADMIN_HEADERS = {"Authorization": f"Bearer {settings.ADMIN_PASSWORD}"}


@pytest.mark.asyncio
async def test_create_account(client: AsyncClient):
    r = await client.post("/admin/accounts", json={"nickname": "bot_alpha"}, headers=ADMIN_HEADERS)
    assert r.status_code == 201
    data = r.json()
    assert data["nickname"] == "bot_alpha"
    assert data["wallet_balance"] == 0
    assert data["status"] == "ACTIVE"
    assert "id" in data


@pytest.mark.asyncio
async def test_create_account_duplicate(client: AsyncClient):
    await client.post("/admin/accounts", json={"nickname": "bot_dup"}, headers=ADMIN_HEADERS)
    r = await client.post("/admin/accounts", json={"nickname": "bot_dup"}, headers=ADMIN_HEADERS)
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "CONFLICT"


@pytest.mark.asyncio
async def test_create_account_empty_nickname(client: AsyncClient):
    r = await client.post("/admin/accounts", json={"nickname": ""}, headers=ADMIN_HEADERS)
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_list_accounts(client: AsyncClient):
    await client.post("/admin/accounts", json={"nickname": "bot_a"}, headers=ADMIN_HEADERS)
    await client.post("/admin/accounts", json={"nickname": "bot_b"}, headers=ADMIN_HEADERS)
    r = await client.get("/admin/accounts", headers=ADMIN_HEADERS)
    assert r.status_code == 200
    assert len(r.json()) >= 2


@pytest.mark.asyncio
async def test_get_account(client: AsyncClient):
    create = await client.post("/admin/accounts", json={"nickname": "bot_get"}, headers=ADMIN_HEADERS)
    account_id = create.json()["id"]
    r = await client.get(f"/admin/accounts/{account_id}", headers=ADMIN_HEADERS)
    assert r.status_code == 200
    assert r.json()["nickname"] == "bot_get"


@pytest.mark.asyncio
async def test_get_account_not_found(client: AsyncClient):
    r = await client.get("/admin/accounts/99999", headers=ADMIN_HEADERS)
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_admin_auth_missing(client: AsyncClient):
    r = await client.post("/admin/accounts", json={"nickname": "x"})
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_admin_auth_wrong_password(client: AsyncClient):
    r = await client.post("/admin/accounts", json={"nickname": "x"}, headers={"Authorization": "Bearer wrong"})
    assert r.status_code == 401
