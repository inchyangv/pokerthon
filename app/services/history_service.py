"""Hand history and action log query service."""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.account import Account
from app.models.hand import Hand, HandAction, HandPlayer, HandResult, HandStatus
from app.models.table import Table


async def _nickname_map(session: AsyncSession, account_ids: list[int]) -> dict[int, str]:
    if not account_ids:
        return {}
    result = await session.execute(select(Account).where(Account.id.in_(account_ids)))
    return {a.id: a.nickname for a in result.scalars().all()}


def _parse_result(result_json: str) -> dict[str, Any]:
    try:
        return json.loads(result_json)
    except Exception:
        return {}


async def get_hand_list(
    session: AsyncSession,
    table_id: int,
    limit: int = 50,
    cursor: int | None = None,
) -> dict[str, Any]:
    q = (
        select(Hand)
        .where(Hand.table_id == table_id, Hand.status == HandStatus.FINISHED)
        .options(selectinload(Hand.result))
        .order_by(Hand.id.desc())
        .limit(limit + 1)
    )
    if cursor is not None:
        q = q.where(Hand.id < cursor)
    result = await session.execute(q)
    hands = list(result.scalars().all())

    has_more = len(hands) > limit
    hands = hands[:limit]

    items = []
    for h in hands:
        result_data = {}
        if h.result:
            result_data = _parse_result(h.result.result_json)

        # Extract winners (seat numbers from awards or summaries)
        winners = []
        awards = result_data.get("awards", {})
        if awards:
            winners = [int(k) for k in awards.keys()]

        items.append({
            "hand_id": h.id,
            "hand_no": h.hand_no,
            "started_at": h.started_at,
            "finished_at": h.finished_at,
            "board": json.loads(h.board_json),
            "winners": winners,
            "pot_summary": result_data.get("pot_view", {}),
        })

    next_cursor = hands[-1].id if has_more and hands else None
    return {"items": items, "next_cursor": next_cursor, "has_more": has_more}


async def get_hand_detail(
    session: AsyncSession,
    table_id: int,
    hand_id: int,
) -> dict[str, Any] | None:
    hand_result = await session.execute(
        select(Hand)
        .where(Hand.id == hand_id, Hand.table_id == table_id)
        .options(selectinload(Hand.result))
    )
    hand = hand_result.scalar_one_or_none()
    if not hand:
        return None

    # Load table
    table_result = await session.execute(select(Table).where(Table.id == table_id))
    table = table_result.scalar_one()

    players_result = await session.execute(
        select(HandPlayer).where(HandPlayer.hand_id == hand_id)
    )
    players = list(players_result.scalars().all())

    acc_ids = [p.account_id for p in players]
    nicknames = await _nickname_map(session, acc_ids)

    result_data: dict[str, Any] = {}
    if hand.result:
        result_data = _parse_result(hand.result.result_json)

    # Determine which players went to showdown (not folded)
    # Fold-win hands: losing players' hole cards not revealed
    summaries = result_data.get("summaries", [])
    is_showdown = any(s.get("type") not in ("fold_win", "uncalled_return") for s in summaries)

    players_out = []
    for p in players:
        reveal = (not p.folded) and is_showdown
        players_out.append({
            "seat_no": p.seat_no,
            "nickname": nicknames.get(p.account_id),
            "starting_stack": p.starting_stack,
            "ending_stack": p.ending_stack,
            "folded": p.folded,
            "hole_cards": json.loads(p.hole_cards_json) if reveal else None,
        })

    awards = result_data.get("awards", {})
    winners = [int(k) for k in awards.keys()]

    return {
        "hand_id": hand.id,
        "hand_no": hand.hand_no,
        "table_no": table.table_no,
        "started_at": hand.started_at,
        "finished_at": hand.finished_at,
        "board": json.loads(hand.board_json),
        "players": players_out,
        "pot_summary": result_data.get("pot_view", {}),
        "winners": winners,
    }


async def get_hand_actions(
    session: AsyncSession,
    hand_id: int,
) -> list[dict[str, Any]]:
    actions_result = await session.execute(
        select(HandAction).where(HandAction.hand_id == hand_id).order_by(HandAction.seq)
    )
    actions = list(actions_result.scalars().all())

    # Build nickname map for actors
    acc_ids = [a.actor_account_id for a in actions if a.actor_account_id]
    nicknames = await _nickname_map(session, acc_ids)

    return [
        {
            "seq": a.seq,
            "street": a.street,
            "actor_seat": a.actor_seat_no,
            "actor_nickname": nicknames.get(a.actor_account_id) if a.actor_account_id else None,
            "action_type": a.action_type,
            "amount": a.amount,
            "amount_to": a.amount_to,
            "is_system_action": a.is_system_action,
            "timestamp": a.created_at,
        }
        for a in actions
    ]


async def get_table_actions(
    session: AsyncSession,
    table_id: int,
    limit: int = 50,
    cursor: int | None = None,
) -> dict[str, Any]:
    # Get hand ids for this table
    q = (
        select(HandAction)
        .join(Hand, HandAction.hand_id == Hand.id)
        .where(Hand.table_id == table_id)
        .order_by(HandAction.id.desc())
        .limit(limit + 1)
    )
    if cursor is not None:
        q = q.where(HandAction.id < cursor)
    result = await session.execute(q)
    actions = list(result.scalars().all())

    has_more = len(actions) > limit
    actions = actions[:limit]

    acc_ids = [a.actor_account_id for a in actions if a.actor_account_id]
    nicknames = await _nickname_map(session, acc_ids)

    items = [
        {
            "seq": a.seq,
            "street": a.street,
            "actor_seat": a.actor_seat_no,
            "actor_nickname": nicknames.get(a.actor_account_id) if a.actor_account_id else None,
            "action_type": a.action_type,
            "amount": a.amount,
            "amount_to": a.amount_to,
            "is_system_action": a.is_system_action,
            "timestamp": a.created_at,
        }
        for a in actions
    ]
    next_cursor = actions[-1].id if has_more and actions else None
    return {"items": items, "next_cursor": next_cursor, "has_more": has_more}


async def get_my_hands(
    session: AsyncSession,
    account_id: int,
    limit: int = 50,
    cursor: int | None = None,
) -> dict[str, Any]:
    """Return hands where this account participated, with own hole cards always revealed."""
    q = (
        select(Hand)
        .join(HandPlayer, Hand.id == HandPlayer.hand_id)
        .where(HandPlayer.account_id == account_id, Hand.status == HandStatus.FINISHED)
        .options(selectinload(Hand.result))
        .order_by(Hand.id.desc())
        .limit(limit + 1)
    )
    if cursor is not None:
        q = q.where(Hand.id < cursor)
    result = await session.execute(q)
    hands = list(result.scalars().all())

    has_more = len(hands) > limit
    hands = hands[:limit]

    items = []
    for h in hands:
        # Get my player record for this hand
        my_hp_r = await session.execute(
            select(HandPlayer).where(HandPlayer.hand_id == h.id, HandPlayer.account_id == account_id)
        )
        my_hp = my_hp_r.scalar_one_or_none()
        result_data = _parse_result(h.result.result_json) if h.result else {}
        awards = result_data.get("awards", {})
        winners = [int(k) for k in awards.keys()]

        items.append({
            "hand_id": h.id,
            "hand_no": h.hand_no,
            "started_at": h.started_at,
            "finished_at": h.finished_at,
            "board": json.loads(h.board_json),
            "winners": winners,
            "pot_summary": result_data.get("pot_view", {}),
            "my_hole_cards": json.loads(my_hp.hole_cards_json) if my_hp else [],
            "my_ending_stack": my_hp.ending_stack if my_hp else 0,
        })

    next_cursor = hands[-1].id if has_more and hands else None
    return {"items": items, "next_cursor": next_cursor, "has_more": has_more}
