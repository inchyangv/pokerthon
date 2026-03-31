"""Hand history and action log public API."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.middleware.hmac_auth import require_hmac_auth
from app.models.hand import Hand, HandStatus
from app.models.table import Table
from app.services.history_service import (
    get_hand_actions,
    get_hand_detail,
    get_hand_list,
    get_latest_hand_actions,
    get_my_hands,
    get_table_actions,
)

router = APIRouter(tags=["history"])


async def _get_table_or_404(session: AsyncSession, table_no: int) -> Table:
    result = await session.execute(select(Table).where(Table.table_no == table_no))
    table = result.scalar_one_or_none()
    if not table:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Table not found"})
    return table


async def _get_hand_or_404(session: AsyncSession, table_id: int, hand_id: int) -> Hand:
    result = await session.execute(
        select(Hand).where(Hand.id == hand_id, Hand.table_id == table_id)
    )
    hand = result.scalar_one_or_none()
    if not hand:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Hand not found"})
    return hand


@router.get("/v1/public/tables/{table_no}/hands")
async def list_hands(
    table_no: int,
    limit: int = Query(default=50, ge=1, le=200),
    cursor: int | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
) -> Any:
    table = await _get_table_or_404(session, table_no)
    return await get_hand_list(session, table.id, limit=limit, cursor=cursor)


@router.get("/v1/public/tables/{table_no}/hands/{hand_id}")
async def get_hand(
    table_no: int,
    hand_id: int,
    session: AsyncSession = Depends(get_session),
) -> Any:
    table = await _get_table_or_404(session, table_no)
    detail = await get_hand_detail(session, table.id, hand_id)
    if detail is None:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Hand not found"})
    return detail


@router.get("/v1/public/tables/{table_no}/hands/latest/actions")
async def list_latest_hand_actions(
    table_no: int,
    limit: int = Query(default=20, ge=1, le=100),
    after_seq: int | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
) -> Any:
    table = await _get_table_or_404(session, table_no)
    return await get_latest_hand_actions(session, table.id, limit=limit, after_seq=after_seq)


@router.get("/v1/public/tables/{table_no}/hands/{hand_id}/actions")
async def list_hand_actions(
    table_no: int,
    hand_id: int,
    session: AsyncSession = Depends(get_session),
) -> Any:
    table = await _get_table_or_404(session, table_no)
    await _get_hand_or_404(session, table.id, hand_id)
    return await get_hand_actions(session, hand_id)


@router.get("/v1/public/tables/{table_no}/actions")
async def list_table_actions(
    table_no: int,
    limit: int = Query(default=50, ge=1, le=200),
    cursor: int | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
) -> Any:
    table = await _get_table_or_404(session, table_no)
    return await get_table_actions(session, table.id, limit=limit, cursor=cursor)


@router.get("/v1/private/me/hands")
async def list_my_hands(
    limit: int = Query(default=50, ge=1, le=200),
    cursor: int | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
    account_id: int = Depends(require_hmac_auth),
) -> Any:
    return await get_my_hands(session, account_id, limit=limit, cursor=cursor)
