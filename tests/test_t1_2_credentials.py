import pytest
from httpx import AsyncClient

from app.config import settings
from app.core.crypto import verify_secret

ADMIN_HEADERS = {"Authorization": f"Bearer {settings.ADMIN_PASSWORD}"}


async def create_account(client: AsyncClient, nickname: str) -> int:
    r = await client.post("/admin/accounts", json={"nickname": nickname}, headers=ADMIN_HEADERS)
    assert r.status_code == 201
    return r.json()["id"]


@pytest.mark.asyncio
async def test_issue_credential(client: AsyncClient):
    acc_id = await create_account(client, "bot_cred1")
    r = await client.post(f"/admin/accounts/{acc_id}/credentials", headers=ADMIN_HEADERS)
    assert r.status_code == 201
    data = r.json()
    assert data["api_key"].startswith("pk_live_")
    assert data["secret_key"].startswith("sk_live_")
    assert data["status"] == "ACTIVE"


@pytest.mark.asyncio
async def test_secret_key_not_in_list(client: AsyncClient):
    acc_id = await create_account(client, "bot_cred2")
    await client.post(f"/admin/accounts/{acc_id}/credentials", headers=ADMIN_HEADERS)
    r = await client.get(f"/admin/accounts/{acc_id}/credentials", headers=ADMIN_HEADERS)
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 1
    assert "secret_key" not in data[0]
    assert data[0]["status"] == "ACTIVE"


@pytest.mark.asyncio
async def test_revoke_credential(client: AsyncClient):
    acc_id = await create_account(client, "bot_cred3")
    issue_r = await client.post(f"/admin/accounts/{acc_id}/credentials", headers=ADMIN_HEADERS)
    api_key = issue_r.json()["api_key"]

    r = await client.post(f"/admin/accounts/{acc_id}/credentials/revoke", headers=ADMIN_HEADERS)
    assert r.status_code == 200

    list_r = await client.get(f"/admin/accounts/{acc_id}/credentials", headers=ADMIN_HEADERS)
    cred = list_r.json()[0]
    assert cred["status"] == "REVOKED"
    assert cred["revoked_at"] is not None


@pytest.mark.asyncio
async def test_reissue_revokes_old(client: AsyncClient):
    acc_id = await create_account(client, "bot_cred4")
    r1 = await client.post(f"/admin/accounts/{acc_id}/credentials", headers=ADMIN_HEADERS)
    old_api_key = r1.json()["api_key"]

    r2 = await client.post(f"/admin/accounts/{acc_id}/credentials", headers=ADMIN_HEADERS)
    new_api_key = r2.json()["api_key"]

    assert old_api_key != new_api_key

    list_r = await client.get(f"/admin/accounts/{acc_id}/credentials", headers=ADMIN_HEADERS)
    statuses = {c["api_key"]: c["status"] for c in list_r.json()}
    assert statuses[old_api_key] == "REVOKED"
    assert statuses[new_api_key] == "ACTIVE"


@pytest.mark.asyncio
async def test_revoke_no_active_key(client: AsyncClient):
    acc_id = await create_account(client, "bot_cred5")
    r = await client.post(f"/admin/accounts/{acc_id}/credentials/revoke", headers=ADMIN_HEADERS)
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_credential_not_found_account(client: AsyncClient):
    r = await client.post("/admin/accounts/99999/credentials", headers=ADMIN_HEADERS)
    assert r.status_code == 404
