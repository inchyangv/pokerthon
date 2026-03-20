"""Tests for HF-2: Rate Limiting middleware."""
import pytest
from httpx import AsyncClient

from app.config import settings
from app.core.signature import sign_request
from app.middleware.rate_limit import PRIVATE_LIMIT, PUBLIC_LIMIT, _clear_buckets

ADMIN_HEADERS = {"Authorization": f"Bearer {settings.ADMIN_PASSWORD}"}


@pytest.fixture(autouse=True)
def reset_rate_limit_buckets():
    """Clear in-memory rate limit state before each test."""
    _clear_buckets()
    yield
    _clear_buckets()


async def _make_authed_account(client: AsyncClient, nickname: str) -> tuple[str, str]:
    r = await client.post("/admin/accounts", json={"nickname": nickname}, headers=ADMIN_HEADERS)
    acc_id = r.json()["id"]
    await client.post(f"/admin/accounts/{acc_id}/grant", json={"amount": 200}, headers=ADMIN_HEADERS)
    r2 = await client.post(f"/admin/accounts/{acc_id}/credentials", headers=ADMIN_HEADERS)
    return r2.json()["api_key"], r2.json()["secret_key"]


def _auth(api_key: str, secret_key: str) -> dict:
    return sign_request(api_key, secret_key, "GET", "/v1/private/me")


@pytest.mark.asyncio
async def test_private_under_limit_ok(client: AsyncClient):
    """15 requests within a minute should all succeed."""
    api_key, secret_key = await _make_authed_account(client, "rl_under")
    for i in range(PRIVATE_LIMIT):
        r = await client.get("/v1/private/me", headers=_auth(api_key, secret_key))
        assert r.status_code == 200, f"Request {i+1} failed: {r.status_code}"


@pytest.mark.asyncio
async def test_private_over_limit_429(client: AsyncClient):
    """16th request to a private endpoint returns 429."""
    api_key, secret_key = await _make_authed_account(client, "rl_over")
    for _ in range(PRIVATE_LIMIT):
        await client.get("/v1/private/me", headers=_auth(api_key, secret_key))

    r = await client.get("/v1/private/me", headers=_auth(api_key, secret_key))
    assert r.status_code == 429
    body = r.json()
    assert body["error"]["code"] == "RATE_LIMITED"
    assert "x-ratelimit-limit" in r.headers
    assert r.headers["x-ratelimit-remaining"] == "0"
    assert "retry-after" in r.headers


@pytest.mark.asyncio
async def test_private_ratelimit_headers_present(client: AsyncClient):
    """Successful private responses include X-RateLimit-* headers."""
    api_key, secret_key = await _make_authed_account(client, "rl_headers")
    r = await client.get("/v1/private/me", headers=_auth(api_key, secret_key))
    assert r.status_code == 200
    assert "x-ratelimit-limit" in r.headers
    assert "x-ratelimit-remaining" in r.headers
    assert r.headers["x-ratelimit-limit"] == str(PRIVATE_LIMIT)
    assert int(r.headers["x-ratelimit-remaining"]) == PRIVATE_LIMIT - 1


@pytest.mark.asyncio
async def test_private_limits_are_per_key(client: AsyncClient):
    """Two different API keys have independent rate limit buckets."""
    ak1, sk1 = await _make_authed_account(client, "rl_key1")
    ak2, sk2 = await _make_authed_account(client, "rl_key2")

    # Exhaust key 1
    for _ in range(PRIVATE_LIMIT):
        await client.get("/v1/private/me", headers=sign_request(ak1, sk1, "GET", "/v1/private/me"))

    # key 1 is limited
    r1 = await client.get("/v1/private/me", headers=sign_request(ak1, sk1, "GET", "/v1/private/me"))
    assert r1.status_code == 429

    # key 2 is unaffected
    r2 = await client.get("/v1/private/me", headers=sign_request(ak2, sk2, "GET", "/v1/private/me"))
    assert r2.status_code == 200


@pytest.mark.asyncio
async def test_admin_not_rate_limited(client: AsyncClient):
    """Admin endpoints are not subject to rate limiting."""
    for _ in range(PRIVATE_LIMIT + 5):
        r = await client.get("/admin/accounts", headers=ADMIN_HEADERS)
        assert r.status_code == 200


@pytest.mark.asyncio
async def test_public_not_limited_at_low_volume(client: AsyncClient):
    """Public endpoints allow up to PUBLIC_LIMIT requests."""
    for i in range(20):  # well below 60/min
        r = await client.get("/v1/public/tables")
        assert r.status_code == 200, f"Request {i+1} failed: {r.status_code}"
