import time

import pytest
from fastapi import Depends
from httpx import AsyncClient

from app.config import settings
from app.core.signature import build_canonical_query_string, build_canonical_string, compute_signature, sha256_hex, sign_request
from app.middleware.hmac_auth import require_hmac_auth

ADMIN_HEADERS = {"Authorization": f"Bearer {settings.ADMIN_PASSWORD}"}


async def create_account_and_credential(client: AsyncClient, nickname: str) -> tuple[int, str, str]:
    r = await client.post("/admin/accounts", json={"nickname": nickname}, headers=ADMIN_HEADERS)
    acc_id = r.json()["id"]
    r2 = await client.post(f"/admin/accounts/{acc_id}/credentials", headers=ADMIN_HEADERS)
    data = r2.json()
    return acc_id, data["api_key"], data["secret_key"]


@pytest.fixture(autouse=True)
def add_test_private_route(client):
    """Register a test route that uses require_hmac_auth dependency."""
    from app.main import app

    @app.get("/v1/private/ping-test")
    async def ping(account_id: int = Depends(require_hmac_auth)):
        return {"account_id": account_id}


@pytest.mark.asyncio
async def test_valid_signature(client: AsyncClient):
    _, api_key, secret_key = await create_account_and_credential(client, "bot_hmac1")
    headers = sign_request(api_key, secret_key, "GET", "/v1/private/ping-test")
    r = await client.get("/v1/private/ping-test", headers=headers)
    assert r.status_code == 200
    assert "account_id" in r.json()


@pytest.mark.asyncio
async def test_invalid_signature(client: AsyncClient):
    _, api_key, secret_key = await create_account_and_credential(client, "bot_hmac2")
    headers = sign_request(api_key, secret_key, "GET", "/v1/private/ping-test")
    headers["X-SIGNATURE"] = "badbadbadbad"
    r = await client.get("/v1/private/ping-test", headers=headers)
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_expired_timestamp(client: AsyncClient):
    _, api_key, secret_key = await create_account_and_credential(client, "bot_hmac3")
    ts = str(int(time.time()) - 400)
    nonce = "some-nonce-123"
    canonical = build_canonical_string(ts, nonce, "GET", "/v1/private/ping-test", "", b"")
    sig = compute_signature(sha256_hex(secret_key.encode()), canonical)
    headers = {"X-API-KEY": api_key, "X-TIMESTAMP": ts, "X-NONCE": nonce, "X-SIGNATURE": sig}
    r = await client.get("/v1/private/ping-test", headers=headers)
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_nonce_reuse(client: AsyncClient):
    _, api_key, secret_key = await create_account_and_credential(client, "bot_hmac4")
    headers = sign_request(api_key, secret_key, "GET", "/v1/private/ping-test")
    r1 = await client.get("/v1/private/ping-test", headers=headers)
    assert r1.status_code == 200
    r2 = await client.get("/v1/private/ping-test", headers=headers)
    assert r2.status_code == 401


@pytest.mark.asyncio
async def test_revoked_key(client: AsyncClient):
    acc_id, api_key, secret_key = await create_account_and_credential(client, "bot_hmac5")
    await client.post(f"/admin/accounts/{acc_id}/credentials/revoke", headers=ADMIN_HEADERS)
    headers = sign_request(api_key, secret_key, "GET", "/v1/private/ping-test")
    r = await client.get("/v1/private/ping-test", headers=headers)
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_public_no_auth(client: AsyncClient):
    r = await client.get("/v1/public/tables")
    assert r.status_code != 401
