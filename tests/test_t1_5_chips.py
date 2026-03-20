import pytest
from httpx import AsyncClient

from app.config import settings

ADMIN_HEADERS = {"Authorization": f"Bearer {settings.ADMIN_PASSWORD}"}


async def create_account(client: AsyncClient, nickname: str) -> int:
    r = await client.post("/admin/accounts", json={"nickname": nickname}, headers=ADMIN_HEADERS)
    assert r.status_code == 201
    return r.json()["id"]


@pytest.mark.asyncio
async def test_grant_chips(client: AsyncClient):
    acc_id = await create_account(client, "bot_chip1")
    r = await client.post(f"/admin/accounts/{acc_id}/grant", json={"amount": 200, "reason": "test"}, headers=ADMIN_HEADERS)
    assert r.status_code == 200
    assert r.json()["wallet_balance"] == 200


@pytest.mark.asyncio
async def test_deduct_chips(client: AsyncClient):
    acc_id = await create_account(client, "bot_chip2")
    await client.post(f"/admin/accounts/{acc_id}/grant", json={"amount": 100}, headers=ADMIN_HEADERS)
    r = await client.post(f"/admin/accounts/{acc_id}/deduct", json={"amount": 50}, headers=ADMIN_HEADERS)
    assert r.status_code == 200
    assert r.json()["wallet_balance"] == 50


@pytest.mark.asyncio
async def test_deduct_insufficient(client: AsyncClient):
    acc_id = await create_account(client, "bot_chip3")
    await client.post(f"/admin/accounts/{acc_id}/grant", json={"amount": 30}, headers=ADMIN_HEADERS)
    r = await client.post(f"/admin/accounts/{acc_id}/deduct", json={"amount": 50}, headers=ADMIN_HEADERS)
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "INSUFFICIENT_BALANCE"


@pytest.mark.asyncio
async def test_wallet_never_negative(client: AsyncClient):
    acc_id = await create_account(client, "bot_chip4")
    r = await client.post(f"/admin/accounts/{acc_id}/deduct", json={"amount": 1}, headers=ADMIN_HEADERS)
    assert r.status_code == 422
    info = await client.get(f"/admin/accounts/{acc_id}", headers=ADMIN_HEADERS)
    assert info.json()["wallet_balance"] == 0


@pytest.mark.asyncio
async def test_ledger_records(client: AsyncClient):
    acc_id = await create_account(client, "bot_chip5")
    await client.post(f"/admin/accounts/{acc_id}/grant", json={"amount": 100}, headers=ADMIN_HEADERS)
    await client.post(f"/admin/accounts/{acc_id}/deduct", json={"amount": 30}, headers=ADMIN_HEADERS)
    r = await client.get(f"/admin/accounts/{acc_id}/ledger", headers=ADMIN_HEADERS)
    assert r.status_code == 200
    entries = r.json()
    assert len(entries) == 2
    # Most recent first
    assert entries[0]["delta"] == -30
    assert entries[1]["delta"] == 100


@pytest.mark.asyncio
async def test_invalid_amount_zero(client: AsyncClient):
    acc_id = await create_account(client, "bot_chip6")
    r = await client.post(f"/admin/accounts/{acc_id}/grant", json={"amount": 0}, headers=ADMIN_HEADERS)
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_invalid_amount_negative(client: AsyncClient):
    acc_id = await create_account(client, "bot_chip7")
    r = await client.post(f"/admin/accounts/{acc_id}/grant", json={"amount": -5}, headers=ADMIN_HEADERS)
    assert r.status_code == 422
