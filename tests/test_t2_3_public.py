import pytest
from httpx import AsyncClient

from app.config import settings
from app.core.signature import sign_request

ADMIN_HEADERS = {"Authorization": f"Bearer {settings.ADMIN_PASSWORD}"}


async def setup(client: AsyncClient, nickname: str, table_no: int) -> tuple[int, str, str]:
    r = await client.post("/admin/accounts", json={"nickname": nickname}, headers=ADMIN_HEADERS)
    acc_id = r.json()["id"]
    await client.post(f"/admin/accounts/{acc_id}/grant", json={"amount": 200}, headers=ADMIN_HEADERS)
    r2 = await client.post(f"/admin/accounts/{acc_id}/credentials", headers=ADMIN_HEADERS)
    await client.post("/admin/tables", json={"table_no": table_no}, headers=ADMIN_HEADERS)
    return acc_id, r2.json()["api_key"], r2.json()["secret_key"]


@pytest.mark.asyncio
async def test_public_table_list(client: AsyncClient):
    await client.post("/admin/tables", json={"table_no": 100}, headers=ADMIN_HEADERS)
    await client.post("/admin/tables", json={"table_no": 101}, headers=ADMIN_HEADERS)
    r = await client.get("/v1/public/tables")
    assert r.status_code == 200
    table_nos = [t["table_no"] for t in r.json()]
    assert 100 in table_nos
    assert 101 in table_nos


@pytest.mark.asyncio
async def test_public_table_detail(client: AsyncClient):
    acc_id, api_key, secret_key = await setup(client, "bot_pub1", 102)
    # Sit
    headers = sign_request(api_key, secret_key, "POST", "/v1/private/tables/102/sit")
    await client.post("/v1/private/tables/102/sit", headers=headers)

    r = await client.get("/v1/public/tables/102")
    assert r.status_code == 200
    data = r.json()
    assert data["table_no"] == 102
    seated = [s for s in data["seats"] if s["seat_status"] != "EMPTY"]
    assert len(seated) == 1
    assert seated[0]["nickname"] == "bot_pub1"
    # Hole cards not exposed
    assert "hole_cards" not in data


@pytest.mark.asyncio
async def test_public_table_not_found(client: AsyncClient):
    r = await client.get("/v1/public/tables/9999")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_me_endpoint(client: AsyncClient):
    acc_id, api_key, secret_key = await setup(client, "bot_me1", 103)
    headers = sign_request(api_key, secret_key, "GET", "/v1/private/me")
    r = await client.get("/v1/private/me", headers=headers)
    assert r.status_code == 200
    data = r.json()
    assert data["nickname"] == "bot_me1"
    assert data["current_table_no"] is None

    # Sit and check table_no
    sit_headers = sign_request(api_key, secret_key, "POST", "/v1/private/tables/103/sit")
    await client.post("/v1/private/tables/103/sit", headers=sit_headers)

    headers2 = sign_request(api_key, secret_key, "GET", "/v1/private/me")
    r2 = await client.get("/v1/private/me", headers=headers2)
    assert r2.json()["current_table_no"] == 103
