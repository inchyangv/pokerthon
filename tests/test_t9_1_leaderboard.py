"""Tests for leaderboard statistics API (T9.1)."""
import pytest


@pytest.mark.asyncio
async def test_leaderboard_empty(client):
    r = await client.get("/v1/public/leaderboard")
    assert r.status_code == 200
    data = r.json()
    assert "items" in data
    assert "updated_at" in data
    assert data["items"] == []


@pytest.mark.asyncio
async def test_leaderboard_with_accounts(client):
    headers = {"Authorization": "Bearer changeme"}

    # Create 2 accounts with chips
    for nick in ("lb_alice", "lb_bob"):
        r = await client.post("/admin/accounts", json={"nickname": nick}, headers=headers)
        acc_id = r.json()["id"]
        await client.post(
            f"/admin/accounts/{acc_id}/grant",
            json={"amount": 500, "reason": "test"},
            headers=headers,
        )

    r = await client.get("/v1/public/leaderboard")
    assert r.status_code == 200
    data = r.json()
    items = data["items"]
    assert len(items) >= 2

    # Should be sorted by chips desc
    chips = [item["total_chips"] for item in items]
    assert chips == sorted(chips, reverse=True)

    # Rank should be sequential
    ranks = [item["rank"] for item in items]
    assert ranks[0] == 1


@pytest.mark.asyncio
async def test_leaderboard_sort_by_profit(client):
    r = await client.get("/v1/public/leaderboard?sort_by=profit")
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_leaderboard_include_bots_false(client):
    headers = {"Authorization": "Bearer changeme"}

    # Create a bot
    await client.post(
        "/admin/bots",
        json={"bot_type": "TAG", "display_name": "lb_bot_filter"},
        headers=headers,
    )
    # Create a human account
    r = await client.post("/admin/accounts", json={"nickname": "lb_human_filter"}, headers=headers)
    acc_id = r.json()["id"]
    await client.post(f"/admin/accounts/{acc_id}/grant", json={"amount": 100}, headers=headers)

    # With bots excluded
    r = await client.get("/v1/public/leaderboard?include_bots=false")
    assert r.status_code == 200
    data = r.json()
    assert all(not item["is_bot"] for item in data["items"])

    # With bots included
    r = await client.get("/v1/public/leaderboard?include_bots=true")
    data = r.json()
    has_bot = any(item["is_bot"] for item in data["items"])
    assert has_bot


@pytest.mark.asyncio
async def test_leaderboard_invalid_sort_by(client):
    r = await client.get("/v1/public/leaderboard?sort_by=invalid")
    assert r.status_code == 422
