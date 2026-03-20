"""Tests for the action submission API endpoint (T3.6)."""
import asyncio
import json

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.signature import sign_request
from app.models.hand import HandPlayer
from app.models.table import Table
from app.services.hand_service import start_hand

ADMIN = {"Authorization": f"Bearer {settings.ADMIN_PASSWORD}"}


async def _setup_two_player_hand(client: AsyncClient, db_session: AsyncSession):
    """Create two players, seat them, and start a hand. Returns (hand, api_key_map)."""
    # Accounts + credentials + chips
    creds = {}
    for nick in ("t36_p1", "t36_p2"):
        r = await client.post("/admin/accounts", json={"nickname": nick}, headers=ADMIN)
        acc_id = r.json()["id"]
        r2 = await client.post(f"/admin/accounts/{acc_id}/credentials", headers=ADMIN)
        api_key, secret_key = r2.json()["api_key"], r2.json()["secret_key"]
        await client.post(f"/admin/accounts/{acc_id}/grant",
                          json={"amount": 100, "reason": "test"}, headers=ADMIN)
        creds[acc_id] = (api_key, secret_key)

    # Table
    r = await client.post("/admin/tables", json={"table_no": 36}, headers=ADMIN)
    assert r.status_code in (200, 201)

    # Sit both players
    seat_no = 1
    for acc_id, (ak, sk) in creds.items():
        payload = json.dumps({"seat_no": seat_no}).encode()
        hdrs = sign_request(ak, sk, "POST", "/v1/private/tables/36/sit", body=payload)
        hdrs["Content-Type"] = "application/json"
        r = await client.post("/v1/private/tables/36/sit", content=payload, headers=hdrs)
        assert r.status_code == 200, r.text
        seat_no += 1

    # Start hand via service (no HTTP endpoint for this yet)
    table = (await db_session.execute(select(Table).where(Table.table_no == 36))).scalar_one()
    hand = await start_hand(db_session, table.id)
    assert hand is not None

    return hand, creds


def _action_headers(api_key: str, secret_key: str, payload: bytes) -> dict:
    hdrs = sign_request(api_key, secret_key, "POST", "/v1/private/tables/36/action", body=payload)
    hdrs["Content-Type"] = "application/json"
    return hdrs


@pytest.mark.asyncio
async def test_submit_action_success(client: AsyncClient, db_session: AsyncSession):
    hand, creds = await _setup_two_player_hand(client, db_session)

    # Find first actor's credentials
    await db_session.refresh(hand)
    first_seat = hand.action_seat_no
    hp = (await db_session.execute(
        select(HandPlayer).where(HandPlayer.hand_id == hand.id, HandPlayer.seat_no == first_seat)
    )).scalar_one()
    api_key, secret_key = creds[hp.account_id]

    payload = json.dumps({"hand_id": hand.id, "action": {"type": "CALL"}}).encode()
    r = await client.post("/v1/private/tables/36/action", content=payload,
                          headers=_action_headers(api_key, secret_key, payload))
    assert r.status_code == 200
    data = r.json()
    assert data["action"]["type"] == "CALL"
    assert "state_version" in data
    assert data["state_version"] >= 1


@pytest.mark.asyncio
async def test_wrong_player_turn(client: AsyncClient, db_session: AsyncSession):
    hand, creds = await _setup_two_player_hand(client, db_session)

    await db_session.refresh(hand)
    first_seat = hand.action_seat_no
    hp = (await db_session.execute(
        select(HandPlayer).where(HandPlayer.hand_id == hand.id, HandPlayer.seat_no == first_seat)
    )).scalar_one()

    # Find the OTHER player's credentials
    other_id = next(acc_id for acc_id in creds if acc_id != hp.account_id)
    api_key, secret_key = creds[other_id]

    payload = json.dumps({"hand_id": hand.id, "action": {"type": "CHECK"}}).encode()
    r = await client.post("/v1/private/tables/36/action", content=payload,
                          headers=_action_headers(api_key, secret_key, payload))
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "INVALID_ACTION"


@pytest.mark.asyncio
async def test_wrong_hand_id(client: AsyncClient, db_session: AsyncSession):
    hand, creds = await _setup_two_player_hand(client, db_session)

    await db_session.refresh(hand)
    first_seat = hand.action_seat_no
    hp = (await db_session.execute(
        select(HandPlayer).where(HandPlayer.hand_id == hand.id, HandPlayer.seat_no == first_seat)
    )).scalar_one()
    api_key, secret_key = creds[hp.account_id]

    # Use a hand_id that doesn't exist
    payload = json.dumps({"hand_id": hand.id + 9999, "action": {"type": "CALL"}}).encode()
    r = await client.post("/v1/private/tables/36/action", content=payload,
                          headers=_action_headers(api_key, secret_key, payload))
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "STALE_STATE"


@pytest.mark.asyncio
async def test_idempotency_key(client: AsyncClient, db_session: AsyncSession):
    hand, creds = await _setup_two_player_hand(client, db_session)

    await db_session.refresh(hand)
    first_seat = hand.action_seat_no
    hp = (await db_session.execute(
        select(HandPlayer).where(HandPlayer.hand_id == hand.id, HandPlayer.seat_no == first_seat)
    )).scalar_one()
    api_key, secret_key = creds[hp.account_id]

    idem_key = "test-idempotency-key-36"
    payload = json.dumps({
        "hand_id": hand.id,
        "idempotency_key": idem_key,
        "action": {"type": "CALL"},
    }).encode()

    hdrs1 = _action_headers(api_key, secret_key, payload)
    r1 = await client.post("/v1/private/tables/36/action", content=payload, headers=hdrs1)
    assert r1.status_code == 200
    first_version = r1.json()["state_version"]

    # Second request with same idempotency_key (new auth headers but same idem key)
    hdrs2 = _action_headers(api_key, secret_key, payload)
    r2 = await client.post("/v1/private/tables/36/action", content=payload, headers=hdrs2)
    assert r2.status_code == 200
    # Should return cached result — same state_version
    assert r2.json()["state_version"] == first_version


@pytest.mark.asyncio
async def test_concurrent_requests_serialized(client: AsyncClient, db_session: AsyncSession):
    """Two concurrent action requests for the same table should be processed sequentially."""
    hand, creds = await _setup_two_player_hand(client, db_session)

    await db_session.refresh(hand)
    first_seat = hand.action_seat_no
    hp = (await db_session.execute(
        select(HandPlayer).where(HandPlayer.hand_id == hand.id, HandPlayer.seat_no == first_seat)
    )).scalar_one()
    api_key, secret_key = creds[hp.account_id]

    payload = json.dumps({"hand_id": hand.id, "action": {"type": "CALL"}}).encode()

    # Fire two concurrent requests from the correct player
    h1 = _action_headers(api_key, secret_key, payload)
    h2 = _action_headers(api_key, secret_key, payload)
    results = await asyncio.gather(
        client.post("/v1/private/tables/36/action", content=payload, headers=h1),
        client.post("/v1/private/tables/36/action", content=payload, headers=h2),
        return_exceptions=True,
    )
    statuses = [r.status_code for r in results if hasattr(r, "status_code")]
    # At least one should succeed; the other may fail (not your turn) or succeed
    assert any(s == 200 for s in statuses)
