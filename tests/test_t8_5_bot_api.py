"""Tests for admin bot management API."""
import pytest
import pytest_asyncio


# --- Bot creation ---

@pytest.mark.asyncio
async def test_create_bot(client):
    resp = await client.post(
        "/admin/bots",
        json={"bot_type": "TAG", "display_name": "bot_tag_test"},
        headers={"Authorization": "Bearer changeme"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["bot_type"] == "TAG"
    assert data["display_name"] == "bot_tag_test"
    assert data["chips"] == 1000  # BOT_INITIAL_CHIPS default


@pytest.mark.asyncio
async def test_create_bot_duplicate_409(client):
    await client.post(
        "/admin/bots",
        json={"bot_type": "LAG", "display_name": "dup_bot"},
        headers={"Authorization": "Bearer changeme"},
    )
    resp = await client.post(
        "/admin/bots",
        json={"bot_type": "FISH", "display_name": "dup_bot"},
        headers={"Authorization": "Bearer changeme"},
    )
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_create_bot_invalid_type(client):
    resp = await client.post(
        "/admin/bots",
        json={"bot_type": "SUPER", "display_name": "invalid_type_bot"},
        headers={"Authorization": "Bearer changeme"},
    )
    assert resp.status_code == 422


# --- List bots ---

@pytest.mark.asyncio
async def test_list_bots_empty(client):
    resp = await client.get("/admin/bots", headers={"Authorization": "Bearer changeme"})
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_list_bots_after_creation(client):
    await client.post(
        "/admin/bots",
        json={"bot_type": "TAG", "display_name": "list_bot_1"},
        headers={"Authorization": "Bearer changeme"},
    )
    await client.post(
        "/admin/bots",
        json={"bot_type": "LAG", "display_name": "list_bot_2"},
        headers={"Authorization": "Bearer changeme"},
    )
    resp = await client.get("/admin/bots", headers={"Authorization": "Bearer changeme"})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) >= 2
    types = {b["bot_type"] for b in data}
    assert "TAG" in types
    assert "LAG" in types


@pytest.mark.asyncio
async def test_list_bots_active_filter(client):
    await client.post(
        "/admin/bots",
        json={"bot_type": "FISH", "display_name": "filter_bot"},
        headers={"Authorization": "Bearer changeme"},
    )
    resp = await client.get(
        "/admin/bots?is_active=true", headers={"Authorization": "Bearer changeme"}
    )
    assert resp.status_code == 200
    data = resp.json()
    assert all(b["is_active"] for b in data)


# --- Seat / Unseat ---

@pytest.mark.asyncio
async def test_seat_and_unseat_bot(client):
    # Create table
    await client.post(
        "/admin/tables",
        json={"table_no": 1},
        headers={"Authorization": "Bearer changeme"},
    )

    # Create bot
    create_resp = await client.post(
        "/admin/bots",
        json={"bot_type": "TAG", "display_name": "seat_bot"},
        headers={"Authorization": "Bearer changeme"},
    )
    bot_id = create_resp.json()["bot_id"]

    # Seat bot
    seat_resp = await client.post(
        f"/admin/bots/{bot_id}/seat",
        json={"table_no": 1},
        headers={"Authorization": "Bearer changeme"},
    )
    assert seat_resp.status_code == 200
    assert seat_resp.json()["seat_no"] in range(1, 10)

    # Unseat bot
    unseat_resp = await client.post(
        f"/admin/bots/{bot_id}/unseat",
        headers={"Authorization": "Bearer changeme"},
    )
    assert unseat_resp.status_code == 200


@pytest.mark.asyncio
async def test_unseat_not_seated_404(client):
    create_resp = await client.post(
        "/admin/bots",
        json={"bot_type": "FISH", "display_name": "notseat_bot"},
        headers={"Authorization": "Bearer changeme"},
    )
    bot_id = create_resp.json()["bot_id"]

    resp = await client.post(
        f"/admin/bots/{bot_id}/unseat",
        headers={"Authorization": "Bearer changeme"},
    )
    assert resp.status_code == 404


# --- Deactivate ---

@pytest.mark.asyncio
async def test_deactivate_bot(client):
    create_resp = await client.post(
        "/admin/bots",
        json={"bot_type": "LAG", "display_name": "deact_bot"},
        headers={"Authorization": "Bearer changeme"},
    )
    bot_id = create_resp.json()["bot_id"]

    resp = await client.delete(
        f"/admin/bots/{bot_id}",
        headers={"Authorization": "Bearer changeme"},
    )
    assert resp.status_code == 204

    # Now it should show as inactive
    list_resp = await client.get(
        "/admin/bots?is_active=false", headers={"Authorization": "Bearer changeme"}
    )
    inactive = [b for b in list_resp.json() if b["bot_id"] == bot_id]
    assert len(inactive) == 1
    assert not inactive[0]["is_active"]


@pytest.mark.asyncio
async def test_deactivate_nonexistent_bot(client):
    resp = await client.delete(
        "/admin/bots/99999",
        headers={"Authorization": "Bearer changeme"},
    )
    assert resp.status_code == 404
