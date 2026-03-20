import json as _json

import pytest
from httpx import AsyncClient

from app.config import settings
from app.core.signature import sign_request

ADMIN_HEADERS = {"Authorization": f"Bearer {settings.ADMIN_PASSWORD}"}


def json_body(data: dict) -> bytes:
    """Serialize to bytes using the same format httpx uses."""
    return _json.dumps(data).encode()


def auth_headers(api_key: str, secret_key: str, method: str, path: str, body_bytes: bytes = b"") -> dict:
    return sign_request(api_key, secret_key, method, path, body=body_bytes)


async def setup_account_with_chips(client: AsyncClient, nickname: str, chips: int = 200) -> tuple[int, str, str]:
    r = await client.post("/admin/accounts", json={"nickname": nickname}, headers=ADMIN_HEADERS)
    acc_id = r.json()["id"]
    await client.post(f"/admin/accounts/{acc_id}/grant", json={"amount": chips}, headers=ADMIN_HEADERS)
    r2 = await client.post(f"/admin/accounts/{acc_id}/credentials", headers=ADMIN_HEADERS)
    return acc_id, r2.json()["api_key"], r2.json()["secret_key"]


async def create_table(client: AsyncClient, table_no: int):
    await client.post("/admin/tables", json={"table_no": table_no}, headers=ADMIN_HEADERS)


async def sit(client: AsyncClient, api_key: str, secret_key: str, table_no: int, data: dict | None = None) -> "Response":
    path = f"/v1/private/tables/{table_no}/sit"
    body_bytes = json_body(data) if data else b""
    headers = auth_headers(api_key, secret_key, "POST", path, body_bytes=body_bytes)
    if data:
        return await client.post(path, content=body_bytes, headers={**headers, "Content-Type": "application/json"})
    return await client.post(path, headers=headers)


@pytest.mark.asyncio
async def test_sit_and_stand(client: AsyncClient):
    acc_id, api_key, secret_key = await setup_account_with_chips(client, "bot_sit1")
    await create_table(client, 10)

    r = await sit(client, api_key, secret_key, 10)
    assert r.status_code == 200
    assert r.json()["stack"] == 40

    acc_r = await client.get(f"/admin/accounts/{acc_id}", headers=ADMIN_HEADERS)
    assert acc_r.json()["wallet_balance"] == 160

    path_stand = "/v1/private/tables/10/stand"
    headers2 = auth_headers(api_key, secret_key, "POST", path_stand)
    r2 = await client.post(path_stand, headers=headers2)
    assert r2.status_code == 200
    assert r2.json()["immediate"] is True

    acc_r2 = await client.get(f"/admin/accounts/{acc_id}", headers=ADMIN_HEADERS)
    assert acc_r2.json()["wallet_balance"] == 200


@pytest.mark.asyncio
async def test_sit_insufficient_balance(client: AsyncClient):
    acc_id, api_key, secret_key = await setup_account_with_chips(client, "bot_sit2", chips=30)
    await create_table(client, 11)

    r = await sit(client, api_key, secret_key, 11)
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "INSUFFICIENT_BALANCE"


@pytest.mark.asyncio
async def test_sit_duplicate_same_table(client: AsyncClient):
    acc_id, api_key, secret_key = await setup_account_with_chips(client, "bot_sit3")
    await create_table(client, 12)

    await sit(client, api_key, secret_key, 12)
    r = await sit(client, api_key, secret_key, 12)
    assert r.status_code == 409


@pytest.mark.asyncio
async def test_sit_specific_seat(client: AsyncClient):
    _, api_key, secret_key = await setup_account_with_chips(client, "bot_sit4")
    await create_table(client, 13)

    r = await sit(client, api_key, secret_key, 13, {"seat_no": 5})
    assert r.status_code == 200
    assert r.json()["seat_no"] == 5


@pytest.mark.asyncio
async def test_sit_auto_assign_lowest_seat(client: AsyncClient):
    _, api_key, secret_key = await setup_account_with_chips(client, "bot_sit5")
    await create_table(client, 14)

    r = await sit(client, api_key, secret_key, 14)
    assert r.status_code == 200
    assert r.json()["seat_no"] == 1


@pytest.mark.asyncio
async def test_sit_seat_taken(client: AsyncClient):
    _, api_key1, sk1 = await setup_account_with_chips(client, "bot_sit6a")
    _, api_key2, sk2 = await setup_account_with_chips(client, "bot_sit6b")
    await create_table(client, 15)

    await sit(client, api_key1, sk1, 15, {"seat_no": 3})
    r = await sit(client, api_key2, sk2, 15, {"seat_no": 3})
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "SEAT_TAKEN"


@pytest.mark.asyncio
async def test_sit_invalid_seat_no(client: AsyncClient):
    _, api_key, secret_key = await setup_account_with_chips(client, "bot_sit7")
    await create_table(client, 16)

    r = await sit(client, api_key, secret_key, 16, {"seat_no": 10})
    assert r.status_code == 422
