"""Action submission endpoint with per-table locking."""
from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.action_validator import ActionError
from app.core.table_lock import get_table_lock
from app.database import get_session
from app.middleware.hmac_auth import require_hmac_auth
from app.models.hand import Hand, HandStatus, HandPlayer, TableSnapshot
from app.models.table import SeatStatus, Table, TableSeat
from app.api.public.game_state import invalidate_state_cache
from app.services.action_service import process_action
from app.services.hand_service import get_active_hand
from app.services.snapshot_service import fire_table_event

router = APIRouter(prefix="/v1/private/tables", tags=["action"])

# In-memory idempotency cache: "account_id:key" -> (response, timestamp)
_IDEMPOTENCY_TTL = 300  # 5 minutes
_IDEMPOTENCY_MAX = 10000
_idempotency_cache: dict[str, tuple[dict[str, Any], float]] = {}


def _cache_get(account_id: int, key: str) -> dict[str, Any] | None:
    cache_key = f"{account_id}:{key}"
    entry = _idempotency_cache.get(cache_key)
    if entry is None:
        return None
    resp, ts = entry
    if time.monotonic() - ts > _IDEMPOTENCY_TTL:
        del _idempotency_cache[cache_key]
        return None
    return resp


def _cache_set(account_id: int, key: str, response: dict[str, Any]) -> None:
    # Evict expired entries if cache is full
    if len(_idempotency_cache) >= _IDEMPOTENCY_MAX:
        now = time.monotonic()
        expired = [k for k, (_, ts) in _idempotency_cache.items() if now - ts > _IDEMPOTENCY_TTL]
        for k in expired:
            del _idempotency_cache[k]
        # If still full, remove oldest
        if len(_idempotency_cache) >= _IDEMPOTENCY_MAX:
            oldest_key = min(_idempotency_cache, key=lambda k: _idempotency_cache[k][1])
            del _idempotency_cache[oldest_key]
    _idempotency_cache[f"{account_id}:{key}"] = (response, time.monotonic())


from typing import Literal

_ActionType = Literal["FOLD", "CHECK", "CALL", "BET_TO", "RAISE_TO", "ALL_IN"]


class ActionPayload(BaseModel):
    type: _ActionType
    amount: int | None = None

    @property
    def validated_amount(self) -> int | None:
        if self.amount is not None and self.amount < 0:
            raise ValueError("amount must be non-negative")
        return self.amount


class ActionRequest(BaseModel):
    hand_id: int
    state_version: int | None = None
    idempotency_key: str | None = None
    action: ActionPayload


@router.post("/{table_no}/action")
async def submit_action(
    table_no: int,
    body: ActionRequest,
    session: AsyncSession = Depends(get_session),
    account_id: int = Depends(require_hmac_auth),
):
    # Check idempotency before acquiring the lock (fast path)
    if body.idempotency_key:
        cached = _cache_get(account_id, body.idempotency_key)
        if cached is not None:
            return cached

    lock = get_table_lock(table_no)
    async with lock:
        # Re-check inside lock (another coroutine may have just processed it)
        if body.idempotency_key:
            cached = _cache_get(account_id, body.idempotency_key)
            if cached is not None:
                return cached

        # Load table
        table_result = await session.execute(select(Table).where(Table.table_no == table_no))
        table = table_result.scalar_one_or_none()
        if not table:
            raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Table not found"})

        # Verify player is seated at this table
        seat_result = await session.execute(
            select(TableSeat).where(
                TableSeat.table_id == table.id,
                TableSeat.account_id == account_id,
                TableSeat.seat_status.in_([SeatStatus.SEATED, SeatStatus.LEAVING_AFTER_HAND]),
            )
        )
        seat = seat_result.scalar_one_or_none()
        if not seat:
            raise HTTPException(
                status_code=403,
                detail={"code": "FORBIDDEN", "message": "Not seated at this table"},
            )

        # Load the active hand
        hand = await get_active_hand(session, table.id)
        if not hand:
            raise HTTPException(
                status_code=409,
                detail={"code": "STALE_STATE", "message": "No active hand at this table"},
            )

        # Validate hand_id matches the current active hand
        if hand.id != body.hand_id:
            raise HTTPException(
                status_code=409,
                detail={"code": "STALE_STATE", "message": "hand_id does not match the current active hand"},
            )

        # Validate state_version (optional — skip if not provided)
        if body.state_version is not None:
            snap_result = await session.execute(
                select(TableSnapshot).where(TableSnapshot.table_id == table.id)
            )
            snap = snap_result.scalar_one_or_none()
            current_version = snap.version if snap else 0
            if body.state_version != current_version:
                raise HTTPException(
                    status_code=409,
                    detail={"code": "STALE_STATE", "message": "state_version mismatch"},
                )

        # Process the action
        try:
            action = await process_action(
                session, hand, account_id, body.action.type, body.action.amount
            )
        except ActionError as e:
            raise HTTPException(
                status_code=422,
                detail={"code": e.code, "message": e.message},
            )

        # Refresh hand to get updated state after action
        await session.refresh(hand)

        if hand.status == HandStatus.FINISHED:
            # complete_hand() already bumped and committed the snapshot.
            snap_result = await session.execute(
                select(TableSnapshot).where(TableSnapshot.table_id == table.id)
            )
            snap = snap_result.scalar_one_or_none()
            state_version = snap.version if snap else 0
        else:
            # Mid-hand: bump snapshot version and notify viewers.
            from app.services.snapshot_service import bump_snapshot
            state_version = await bump_snapshot(session, table.id)
            await session.commit()
            # Invalidate in-process cache and notify SSE/long-poll waiters AFTER commit.
            invalidate_state_cache(table.id)
            fire_table_event(table.id)

        response: dict[str, Any] = {
            "action": {
                "seq": action.seq,
                "type": action.action_type,
                "amount": action.amount,
                "amount_to": action.amount_to,
                "street": action.street,
            },
            "state_version": state_version,
        }

        if body.idempotency_key:
            _cache_set(account_id, body.idempotency_key, response)

        return response
